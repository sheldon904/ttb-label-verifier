"""The seam that answers Marcus Williams.

"Our network blocks outbound traffic to a lot of domains... During the scanning
vendor pilot, half their features didn't work because our firewall blocked
connections to their ML endpoints."

So extraction is an interface, not a hard dependency on one vendor. A cloud VLM
is the default; a local OCR implementation is the air-gapped path. Swapping them
is an env var, and the rule engine cannot tell the difference.
"""

from __future__ import annotations

from typing import Protocol

from app.models import LabelExtraction


class LabelExtractor(Protocol):
    name: str

    async def extract(self, image_bytes: bytes) -> LabelExtraction:
        """Observe the label. Never returns a verdict -- see app/models.py."""
        ...
