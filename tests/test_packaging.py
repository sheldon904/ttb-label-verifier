"""The two container files must stay identical.

Vercel builds from Dockerfile.vercel; everything else (CI, local docker
build, other hosts) builds from Dockerfile. A fix applied to one and not the
other would ship a different app from the one CI tested.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_vercel_dockerfile_matches_the_tested_one():
    assert (ROOT / "Dockerfile.vercel").read_bytes() == (ROOT / "Dockerfile").read_bytes()


def test_the_image_leaves_model_features_to_their_credentials():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "SECOND_OPINION=auto" in text and "TRIAGE=jev" in text
    for secret in ("OPENROUTER_API_KEY=", "ANTHROPIC_API_KEY=", "AI_GATEWAY_API_KEY="):
        assert secret not in text, "credentials belong in the host's settings, never the image"
