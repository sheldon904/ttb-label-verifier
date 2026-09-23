"""Degrades every compliant rendered label and counts what the pipeline does.

Usage:
    make stress                  # about four minutes on 8 threads
    python -m eval.stress --out eval/out/report-stress.md

The fixture sets hold a few photographs. This covers what they do not: every
compliant rendered label under three blurs, two shrinks, two JPEG qualities,
two rotations, dimming, low contrast, noise and glare in three places. Every
copy is still a compliant label, so a rejection here is a harmful outcome and
a referral is the safe answer. The run reports; it does not gate CI, because
glare that erases a line still rejects (README, Limitations).
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import REPO_ROOT
from app.extract.imageprep import UnreadableImageError
from app.extract.ocr import OcrExtractor
from app.models import ApplicationRecord
from app.pipeline import review_label

FIXTURES = REPO_ROOT / "fixtures" / "labels"


def _jpeg(img: Image.Image, quality: int) -> Image.Image:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return Image.open(io.BytesIO(buf.getvalue())).convert("RGB")


def _scale(img: Image.Image, factor: float) -> Image.Image:
    return img.resize((max(1, int(img.width * factor)), max(1, int(img.height * factor))),
                      Image.BILINEAR)


def _noise(img: Image.Image, sigma: float) -> Image.Image:
    a = np.asarray(img, dtype=np.float64)
    a = a + np.random.default_rng(0).normal(0, sigma, a.shape)
    return Image.fromarray(a.clip(0, 255).astype(np.uint8))


def _glare(img: Image.Image, cx: float, cy: float, radius: float, strength: float) -> Image.Image:
    """A soft white spot, the shape a lamp leaves on a glossy label."""
    a = np.asarray(img, dtype=np.float64)
    h, w = a.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    d = np.sqrt(((xx - cx * w) / (radius * w)) ** 2 + ((yy - cy * h) / (radius * w)) ** 2)
    g = np.clip(1 - d, 0, 1)[..., None] * strength
    return Image.fromarray((a * (1 - g) + 255 * g).clip(0, 255).astype(np.uint8))


DEGRADATIONS = {
    "blur 1.5": lambda im: im.filter(ImageFilter.GaussianBlur(1.5)),
    "blur 2.5": lambda im: im.filter(ImageFilter.GaussianBlur(2.5)),
    "blur 3.5": lambda im: im.filter(ImageFilter.GaussianBlur(3.5)),
    "shrink to 45%": lambda im: _scale(im, 0.45),
    "shrink to 30%": lambda im: _scale(im, 0.30),
    "JPEG quality 15": lambda im: _jpeg(im, 15),
    "JPEG quality 8": lambda im: _jpeg(im, 8),
    "rotate 3°": lambda im: im.rotate(3, expand=True, fillcolor=(90, 90, 90)),
    "rotate -6°": lambda im: im.rotate(-6, expand=True, fillcolor=(90, 90, 90)),
    "half brightness": lambda im: ImageEnhance.Brightness(im).enhance(0.5),
    "contrast 35%": lambda im: ImageEnhance.Contrast(im).enhance(0.35),
    "noise": lambda im: _noise(im, 25),
    "glare on the warning": lambda im: _glare(im, 0.5, 0.73, 0.35, 0.85),
    "glare mid-label": lambda im: _glare(im, 0.5, 0.35, 0.30, 0.85),
    "glare at the top": lambda im: _glare(im, 0.5, 0.13, 0.30, 0.9),
}


def compliant_fixtures() -> list[dict]:
    """Rendered labels that should pass. The photographs are degraded already."""
    out = []
    for path in sorted(FIXTURES.glob("*.truth.json")):
        truth = json.loads(path.read_text(encoding="utf-8"))
        if truth["expected_verdict"] == "pass" and not truth["id"].startswith("photo_"):
            out.append(truth)
    return out


def check(extractor: OcrExtractor, truth: dict, name: str) -> dict:
    image = Image.open(FIXTURES / f"{truth['id']}.png").convert("RGB")
    buf = io.BytesIO()
    DEGRADATIONS[name](image).save(buf, format="PNG")
    record = ApplicationRecord(**truth["record"])
    try:
        bundle = asyncio.run(review_label(buf.getvalue(), record, extractor))
    except UnreadableImageError:
        return {"id": truth["id"], "degradation": name, "verdict": "unreadable", "failed": []}
    failed = [c.field for c in bundle.result.checks if c.verdict.value == "fail"]
    return {"id": truth["id"], "degradation": name, "verdict": bundle.result.verdict.value,
            "failed": failed}


def render(results: list[dict]) -> str:
    verdicts = ("pass", "flag", "fail", "unreadable")
    intro = (f"{len(results)} copies: {len(compliant_fixtures())} compliant rendered labels "
             f"under {len(DEGRADATIONS)} degradations. Every copy is a compliant label, so a "
             "rejection is a harmful outcome and a referral is the safe answer.\n")
    lines = ["# Stress test: degraded copies of compliant labels\n", intro,
             "| degradation | pass | referred | rejected | unreadable |", "|---|---|---|---|---|"]
    for name in DEGRADATIONS:
        row = [r for r in results if r["degradation"] == name]
        counts = [sum(r["verdict"] == v for r in row) for v in verdicts]
        lines.append(f"| {name} | " + " | ".join(str(c) for c in counts) + " |")
    totals = [sum(r["verdict"] == v for r in results) for v in verdicts]
    lines.append("| **all** | " + " | ".join(f"**{c}**" for c in totals) + " |")
    rejected = [r for r in results if r["verdict"] == "fail"]
    lines += ["", "## Rejections\n"]
    if rejected:
        lines += ["| label | degradation | rows failed |", "|---|---|---|"]
        lines += [f"| `{r['id']}` | {r['degradation']} | {', '.join(r['failed'])} |"
                  for r in rejected]
    else:
        lines.append("None.")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--out", default=str(REPO_ROOT / "eval" / "out" / "report-stress.md"))
    args = parser.parse_args()

    extractor = OcrExtractor()
    jobs = [(t, name) for t in compliant_fixtures() for name in DEGRADATIONS]
    with ThreadPoolExecutor(args.workers) as pool:
        results = list(pool.map(lambda job: check(extractor, *job), jobs))

    report = render(results)
    Path(args.out).write_text(report, encoding="utf-8")
    rejected = sum(r["verdict"] == "fail" for r in results)
    print(f"{len(results)} degraded compliant labels: {rejected} rejected")
    print(f"report -> {args.out}")


if __name__ == "__main__":
    main()
