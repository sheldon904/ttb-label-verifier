"""Per-address rate limiting for the API, in memory.

A public deployment of an OCR endpoint with no limit is free CPU for anyone
who finds it. The OCR semaphore already caps how much work runs at once; this
caps how much of that capacity one address can take, so one script cannot
queue out every reviewer. Nothing is stored beyond a token count per address,
and idle addresses are forgotten.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


@dataclass
class _Bucket:
    tokens: float
    updated: float


class TokenBuckets:
    def __init__(self, per_minute: int, burst: int | None = None,
                 clock=time.monotonic, max_keys: int = 10_000) -> None:
        self.rate = per_minute / 60.0
        self.capacity = float(burst if burst is not None else per_minute)
        self._clock = clock
        self._max_keys = max_keys
        self._buckets: dict[str, _Bucket] = {}

    def take(self, key: str, cost: float = 1.0) -> float:
        """Spend `cost` tokens. Returns 0 on success, else seconds until it would succeed."""
        now = self._clock()
        b = self._buckets.get(key)
        if b is None:
            if len(self._buckets) >= self._max_keys:
                self._forget_idle(now)
            b = self._buckets[key] = _Bucket(self.capacity, now)
        b.tokens = min(self.capacity, b.tokens + (now - b.updated) * self.rate)
        b.updated = now
        if b.tokens >= cost:
            b.tokens -= cost
            return 0.0
        return (cost - b.tokens) / self.rate if self.rate else math.inf

    def _forget_idle(self, now: float) -> None:
        full_after = self.capacity / self.rate if self.rate else math.inf
        for k in [k for k, b in self._buckets.items() if now - b.updated >= full_after]:
            del self._buckets[k]
        if len(self._buckets) >= self._max_keys:
            self._buckets.clear()


def client_key(request: Request, trust_proxy_headers: bool) -> str:
    """The caller's address.

    Behind a host's load balancer every request arrives from the balancer, so
    the address has to come from X-Forwarded-For. The rightmost entry is the one
    the nearest proxy appended, which a client cannot forge; the leftmost is
    whatever the client claimed. Only trusted when the deployment says it sits
    behind a proxy.
    """
    if trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for", "")
        hops = [h.strip() for h in forwarded.split(",") if h.strip()]
        if hops:
            return hops[-1]
    return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, buckets: TokenBuckets, trust_proxy_headers: bool = False,
                 prefix: str = "/api/") -> None:
        super().__init__(app)
        self.buckets = buckets
        self.trust_proxy_headers = trust_proxy_headers
        self.prefix = prefix

    async def dispatch(self, request: Request, call_next):
        if request.method == "POST" and request.url.path.startswith(self.prefix):
            wait = self.buckets.take(client_key(request, self.trust_proxy_headers))
            if wait:
                seconds = max(1, math.ceil(wait))
                return JSONResponse(
                    {"detail": f"Too many requests from this address. Try again in {seconds} s."},
                    status_code=429,
                    headers={"Retry-After": str(seconds)},
                )
        return await call_next(request)
