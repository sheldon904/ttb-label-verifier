"""Generates the evaluation fixture set.

Writes, per fixture:
  <id>.png         the label artwork
  <id>.truth.json  the application record, the expected extraction (ground
                   truth for the stub extractor), and the expected verdict

Run with `make fixtures`. The PNGs are committed so the eval set is reproducible
on a machine without the fonts.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fixtures.render import apply_degradation, render_label  # noqa: E402
from fixtures.spec import Fixture, build_catalog  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent / "labels"


def truth_observations(fx: Fixture) -> dict:
    """What a perfect extractor would report for this artwork.

    Note `warning_text` carries the spec's exact casing: for the title-case
    fixture the correct observation is the title-case string, because the
    extractor's job is transcription, not correction.
    """
    s = fx.spec
    notes: list[str] = []
    d = fx.degradation
    if d.rotate_deg:
        notes.append(f"label is rotated approximately {abs(d.rotate_deg):.0f} degrees")
    if d.glare:
        notes.append("specular glare across the upper portion of the label")
    if d.blur_radius:
        notes.append("image is slightly out of focus")
    if d.jpeg_quality:
        notes.append("heavy JPEG compression artifacts")
    if s.warning_point_size <= 7:
        notes.append("warning statement is set in very small type")

    return {
        "brand_name": s.brand_name,
        "class_type": s.class_type,
        "alcohol_statement": s.alcohol_statement,
        "net_contents": s.net_contents,
        "bottler_name": s.bottler_name,
        "bottler_address": s.bottler_address,
        "country_of_origin": s.country_of_origin,
        "warning_text": s.warning_text,
        "warning_prefix_is_bold": fx.truth_bold,
        # Ground truth is what is physically on the artwork. A perfect reader
        # would read every warning that is present; where OCR cannot, the
        # evaluation is supposed to show that as a miss.
        "warning_legibility": "read" if s.warning_text else "absent",
        "legibility_notes": notes,
    }


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for stale in OUT_DIR.glob("*.png"):
        stale.unlink()
    for stale in OUT_DIR.glob("*.truth.json"):
        stale.unlink()

    catalog = build_catalog()
    for fx in catalog:
        img = apply_degradation(render_label(fx.spec), fx.degradation)
        img.save(OUT_DIR / f"{fx.id}.png")
        (OUT_DIR / f"{fx.id}.truth.json").write_text(
            json.dumps({
                "id": fx.id,
                "description": fx.description,
                "record": fx.record,
                "observations": truth_observations(fx),
                "expected_verdict": fx.expected_verdict,
                "expected_failing_fields": fx.expected_failing_fields,
            }, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"  {fx.id:<28} {fx.expected_verdict.upper():<5} {fx.description}")

    print(f"\n{len(catalog)} fixtures written to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
