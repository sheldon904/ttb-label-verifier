"""The two container files must stay identical.

Vercel builds from Dockerfile.vercel; everything else (CI, local docker
build, other hosts) builds from Dockerfile. A fix applied to one and not the
other would ship a different app from the one CI tested.
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_vercel_dockerfile_matches_the_tested_one():
    assert (ROOT / "Dockerfile.vercel").read_bytes() == (ROOT / "Dockerfile").read_bytes()


def test_the_image_leaves_model_features_to_their_credentials():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "SECOND_OPINION=auto" in text and "TRIAGE=jev" in text
    for secret in ("OPENROUTER_API_KEY=", "ANTHROPIC_API_KEY=", "AI_GATEWAY_API_KEY="):
        assert secret not in text, "credentials belong in the host's settings, never the image"


def test_the_image_carries_every_folder_the_samples_come_from():
    """The AI-generated samples were served from fixtures/ai, which the image
    did not copy: on a deployment they would vanish from the page and fifteen
    rows of the sample batch would come back "Not checked"."""
    from app import main

    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    for folder in (*main.FIXTURE_DIRS, main.SAMPLE_BATCH.parent):
        relative = folder.relative_to(ROOT).as_posix()
        assert f"COPY {relative} ./{relative}" in text, relative


def test_tesseract_gets_one_thread_per_process():
    """The container's Tesseract starts an OpenMP thread per core in every
    process, and the OCR pool runs four labels at once. The sample batch took
    346.8 s that way and 15.1 s with one thread each."""
    env = {k: v for k, v in os.environ.items() if k != "OMP_THREAD_LIMIT"}
    probe = "import os, app.extract.ocr; print(os.environ['OMP_THREAD_LIMIT'])"
    out = subprocess.run([sys.executable, "-c", probe], cwd=ROOT, env=env,
                         capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "1"
