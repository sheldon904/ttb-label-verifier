"""Test-wide settings.

The model features switch on automatically when a provider credential is
present, and a developer's .env may hold one. Tests must never make a paid or
outbound call, so both features are pinned to their local behaviour here,
before any application module reads its settings. Real environment variables
win over .env, so this holds whatever .env contains.
"""

import os

os.environ["SECOND_OPINION"] = "off"
os.environ["TRIAGE"] = "heuristic"
for name in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "AI_GATEWAY_API_KEY", "VERCEL_OIDC_TOKEN"):
    os.environ[name] = ""
