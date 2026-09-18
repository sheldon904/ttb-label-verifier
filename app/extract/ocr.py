"""Local OCR extractor -- the only extractor, and the air-gapped one.

Marcus Williams: "our network blocks outbound traffic to a lot of domains...
half their features didn't work because our firewall blocked connections to
their ML endpoints."

Nothing here leaves the machine. There is no API key, no per-label cost and no
vendor dependency, and every determination can be traced to an inspectable rule
-- which matters more than usual when the output can cause a federal rejection
of someone's application.

Reports observations only. Verdicts are the rule engine's job.
"""

from __future__ import annotations

import time

import numpy as np
import pytesseract
from PIL import Image

from app.extract import layout
from app.extract.imageprep import PreparedImage, binarize
from app.extract.layout import Line, Word

# Below this mean word confidence we say "we could not read this", never
# "this is wrong". The distinction is the whole safety argument for OCR here:
# an unreadable warning must FLAG for a human, not FAIL the applicant.
# Measured on the fixture set: legible blocks score 91-96, the 6pt block 63.
LEGIBLE_CONF = 75.0

# Type this small cannot be verified from an image at all, whatever Tesseract's
# confidence claims. Same limitation that makes the 27 CFR 16.22 size rule
# uncheckable here: a photograph carries pixels, not millimetres.
MIN_LEGIBLE_GLYPH_PX = 12

# A word must beat this to be considered detected text at all. Tesseract emits
# -1 for non-text regions and very low scores for noise.
DETECTION_CONF = 25.0

# Bold prefixes carry measurably more ink per unit area than the body copy.
#
# Calibrated against the fixture set rather than guessed:
#     bold prefixes      1.33, 1.47, 1.48
#     regular prefix     1.21
# The gap is narrow because "GOVERNMENT WARNING:" is set in capitals either
# way, and capitals are denser than the mixed-case body regardless of weight.
# With that little separation a single cutoff would be a coin flip near the
# boundary, so the band below leaves an explicit undecided zone that reports
# None and lets the result FLAG for a human.
BOLD_INK_RATIO_HIGH = 1.32   # at or above: bold
BOLD_INK_RATIO_LOW = 1.24    # at or below: regular
                             # between the two: not determinable

# A label whose brand is no larger than its body copy has not been read
# correctly -- see layout.pick_brand_and_class. Below this the photograph is
# treated as too degraded to support any rejection.
BRAND_DOMINANCE_FLOOR = 1.55

# Confidence assigned to every field of a degraded image: present, so the rule
# engine softens failures, but low enough that none of them can reject.
DEGRADED_CONFIDENCE = 0.0

TESSERACT_CONFIG = "--oem 3 --psm 4"


class OcrExtractor:
    name = "ocr:tesseract"

    def __init__(self, tesseract_config: str = TESSERACT_CONFIG) -> None:
        self._config = tesseract_config

    # --- low level -------------------------------------------------------

    def _words(self, image: Image.Image) -> list[Word]:
        data = pytesseract.image_to_data(
            image, config=self._config, output_type=pytesseract.Output.DICT
        )
        words: list[Word] = []
        for i, text in enumerate(data["text"]):
            text = (text or "").strip()
            if not text:
                continue
            try:
                conf = float(data["conf"][i])
            except (TypeError, ValueError):
                conf = -1.0
            if conf < DETECTION_CONF:
                continue
            words.append(Word(
                text=text,
                left=int(data["left"][i]), top=int(data["top"][i]),
                width=int(data["width"][i]), height=int(data["height"][i]),
                conf=conf,
                line_key=(int(data["block_num"][i]), int(data["par_num"][i]),
                          int(data["line_num"][i])),
            ))
        return words

    def _low_confidence_regions(self, image: Image.Image) -> int:
        """Count text-like detections Tesseract saw but could not resolve.

        This is how "there is small print here we cannot read" is distinguished
        from "there is nothing here". Without it, an out-of-focus photo of a
        perfectly compliant label would be reported as a missing warning.
        """
        data = pytesseract.image_to_data(
            image, config=self._config, output_type=pytesseract.Output.DICT
        )
        n = 0
        for i, text in enumerate(data["text"]):
            try:
                conf = float(data["conf"][i])
            except (TypeError, ValueError):
                continue
            if 0 <= conf < DETECTION_CONF and (text or "").strip():
                n += 1
        return n

    # --- typography ------------------------------------------------------

    def _ink_ratio(self, binary: np.ndarray, words: list[Word]) -> float | None:
        """Fraction of a word's bounding box that is ink.

        A measurement, not an opinion: bold glyphs of the same point size cover
        materially more of their box than regular ones. This is the part of the
        27 CFR 16.22 check that an image can honestly support.
        """
        total_dark = 0
        total_area = 0
        h, w = binary.shape
        for word in words:
            x0, y0 = max(word.left, 0), max(word.top, 0)
            x1, y1 = min(word.right, w), min(word.bottom, h)
            if x1 <= x0 or y1 <= y0:
                continue
            box = binary[y0:y1, x0:x1]
            total_dark += int((box == 0).sum())
            total_area += box.size
        if total_area == 0:
            return None
        return total_dark / total_area

    def _prefix_is_bold(self, binary: np.ndarray, block: list[Line]) -> bool | None:
        if not block:
            return None
        first = block[0]
        prefix_words = [w for w in first.words
                        if w.text.upper().strip(":").strip() in ("GOVERNMENT", "WARNING")]
        body_words = [w for ln in block for w in ln.words if w not in prefix_words]
        if len(prefix_words) < 2 or len(body_words) < 8:
            return None

        prefix_ratio = self._ink_ratio(binary, prefix_words)
        body_ratio = self._ink_ratio(binary, body_words)
        if not prefix_ratio or not body_ratio:
            return None
        # Very small type cannot be judged: antialiasing dominates the measurement.
        if first.height < MIN_LEGIBLE_GLYPH_PX:
            return None

        ratio = prefix_ratio / body_ratio
        if ratio >= BOLD_INK_RATIO_HIGH:
            return True
        if ratio <= BOLD_INK_RATIO_LOW:
            return False
        return None

    # --- interface -------------------------------------------------------

    async def extract_raw(self, raw: bytes, prepared: PreparedImage) -> tuple[dict, dict]:
        started = time.perf_counter()
        image = prepared.image

        words = self._words(image)
        lines = layout.build_lines(words)

        warning_text, warning_block = layout.extract_warning(lines)
        warning_indices = {i for i, ln in enumerate(lines) if ln in warning_block}

        brand, class_type, dominance = layout.pick_brand_and_class(lines, warning_indices)
        degraded = bool(lines) and dominance < BRAND_DOMINANCE_FLOOR
        if degraded:
            # The most prominent element on the label did not survive the
            # photograph. Nothing read from it is trustworthy, so the whole
            # label goes to a human rather than being rejected on bad evidence.
            brand = None
        alcohol = layout.pick_alcohol_statement(lines, warning_indices)
        net_contents = layout.pick_net_contents(lines, warning_indices)
        country = layout.pick_country(lines, warning_indices)
        bottler_name, bottler_address = layout.pick_bottler(
            lines, warning_indices | {i for i, ln in enumerate(lines)
                                      if ln.text.strip() in {brand, class_type}}
        )

        binary = np.asarray(binarize(image), dtype=np.uint8)
        prefix_bold = self._prefix_is_bold(binary, warning_block)

        # Legibility: did we read it, fail to read it, or is it truly absent?
        if warning_text:
            block_conf = sum(ln.conf for ln in warning_block) / len(warning_block)
            glyph_px = min(ln.height for ln in warning_block)
            legible = block_conf >= LEGIBLE_CONF and glyph_px >= MIN_LEGIBLE_GLYPH_PX
            legibility = "read" if legible else "illegible"
        elif self._low_confidence_regions(image) > 0:
            legibility = "illegible"
        else:
            legibility = "absent"

        notes: list[str] = []
        if prepared.was_deskewed:
            notes.append(f"image was rotated {abs(prepared.deskew_deg):.1f}° to straighten it")
        if prepared.upscale_factor > 1.05:
            notes.append(f"image was enlarged {prepared.upscale_factor:.1f}x to resolve small type")
        if legibility == "illegible":
            notes.append("small print was detected but could not be read reliably")
        if degraded:
            notes.append(
                "no clearly dominant brand text was found, which usually means glare or "
                "blowout has obscured part of the label; readings from this image are "
                "not reliable enough to reject it"
            )

        def line_conf(value: str | None) -> float | None:
            """Confidence of the line a field was taken from.

            None when the field was not found at all. An absent field is a
            different claim from a badly-read one: "this label has no net
            contents statement" is a finding, whereas "we could not read the
            net contents" is not. Only the latter may soften a rejection.
            """
            if not value:
                return None
            for ln in lines:
                if value in ln.text or ln.text in value:
                    return round(ln.conf, 1)
            return None

        observations = {
            "brand_name": brand,
            "class_type": class_type,
            "alcohol_statement": alcohol,
            "net_contents": net_contents,
            "bottler_name": bottler_name,
            "bottler_address": bottler_address,
            "country_of_origin": country,
            "warning_text": warning_text,
            "warning_prefix_is_bold": prefix_bold,
            "warning_legibility": legibility,
            "legibility_notes": notes,
            "field_confidence": {
                key: (DEGRADED_CONFIDENCE if degraded else value)
                for key, value in {
                    "brand_name": line_conf(brand),
                    "class_type": line_conf(class_type),
                    "alcohol_content": line_conf(alcohol),
                    "proof_consistency": line_conf(alcohol),
                    "net_contents": line_conf(net_contents),
                }.items() if value is not None or degraded
            },
        }
        telemetry = {
            "engine": self.name,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "words_detected": len(words),
            "brand_dominance": round(dominance, 2),
            "degraded": degraded,
            "mean_conf": round(sum(w.conf for w in words) / len(words), 1) if words else 0.0,
            "deskew_deg": prepared.deskew_deg,
            "upscale_factor": prepared.upscale_factor,
        }
        return observations, telemetry
