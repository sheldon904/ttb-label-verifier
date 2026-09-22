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

import asyncio
import os
import shutil
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

# Those two numbers compare a capitals prefix against a mixed-case body, and
# about 0.2 of the ratio is the capitals rather than the weight. When prefix
# and body share a case -- a body set entirely in capitals, or a title-case
# prefix over mixed case -- only weight is left, and the band has to move.
# Measured on the second fixture template and the title-case fixtures:
#     bold prefix, same case      1.08, 1.10, 1.11, 1.20
#     regular prefix, same case   0.96
# One regular sample again, so the band keeps an undecided zone.
SAME_CASE_BOLD_HIGH = 1.10
SAME_CASE_BOLD_LOW = 1.04


def _is_capitals(words) -> bool:
    letters = "".join(c for w in words for c in w.text if c.isalpha())
    return bool(letters) and sum(c.isupper() for c in letters) / len(letters) >= 0.6

# A label whose brand is no larger than its body copy has not been read
# correctly -- see layout.pick_brand_and_class. Below this the photograph is
# treated as too degraded to support any rejection.
BRAND_DOMINANCE_FLOOR = 1.55

# Confidence assigned to every field of a degraded image: present, so the rule
# engine softens failures, but low enough that none of them can reject.
DEGRADED_CONFIDENCE = 0.0

TESSERACT_CONFIG = "--oem 3 --psm 4"

# Where the Windows installer puts the binary when it is not on PATH.
_WINDOWS_TESSERACT = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)


def resolve_tesseract(explicit: str | None) -> str | None:
    """Pick the Tesseract binary: explicit setting, then PATH, then the
    Windows default install location. Returns None when nothing is found,
    and the first extraction then raises a readable error."""
    if explicit:
        return explicit
    if shutil.which("tesseract"):
        return None  # pytesseract's default already works
    for candidate in _WINDOWS_TESSERACT:
        if os.path.isfile(candidate):
            return candidate
    return None


class OcrExtractor:
    name = "ocr:tesseract"

    def __init__(self, tesseract_config: str = TESSERACT_CONFIG,
                 tesseract_cmd: str | None = None) -> None:
        self._config = tesseract_config
        resolved = resolve_tesseract(tesseract_cmd)
        if resolved:
            pytesseract.pytesseract.tesseract_cmd = resolved

    # --- low level -------------------------------------------------------

    def _read(self, image: Image.Image) -> tuple[list[Word], int, list[Word]]:
        """One Tesseract pass: the words it resolved, and a count of the
        text-like regions it saw but could not.

        The count is how "there is small print here we cannot read" is
        distinguished from "there is nothing here". Without it, an
        out-of-focus photo of a perfectly compliant label would be reported
        as a missing warning. It comes from the same pass as the words: a
        second run over the same image would double the latency of every
        label whose warning was not found.
        """
        try:
            data = pytesseract.image_to_data(
                image, config=self._config, output_type=pytesseract.Output.DICT
            )
        except pytesseract.TesseractNotFoundError as exc:
            raise RuntimeError(
                "Tesseract OCR is not installed or not on PATH. Install it (brew install "
                "tesseract, apt install tesseract-ocr, or the Windows installer) or set "
                "TESSERACT_CMD to the binary."
            ) from exc
        words: list[Word] = []
        weak: list[Word] = []
        unresolved = 0
        for i, text in enumerate(data["text"]):
            text = (text or "").strip()
            if not text:
                continue
            try:
                conf = float(data["conf"][i])
            except (TypeError, ValueError):
                conf = -1.0
            word = Word(
                text=text,
                left=int(data["left"][i]), top=int(data["top"][i]),
                width=int(data["width"][i]), height=int(data["height"][i]),
                conf=max(conf, 0.0),
                line_key=(int(data["block_num"][i]), int(data["par_num"][i]),
                          int(data["line_num"][i])),
            )
            if conf < DETECTION_CONF:
                if conf >= 0:
                    unresolved += 1
                    weak.append(word)
                continue
            words.append(word)
        return words, unresolved, weak

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
        same_case = _is_capitals(prefix_words) == _is_capitals(body_words)
        high, low = ((SAME_CASE_BOLD_HIGH, SAME_CASE_BOLD_LOW) if same_case
                     else (BOLD_INK_RATIO_HIGH, BOLD_INK_RATIO_LOW))
        if ratio >= high:
            return True
        if ratio <= low:
            return False
        return None

    # --- interface -------------------------------------------------------

    async def extract_raw(self, raw: bytes, prepared: PreparedImage) -> tuple[dict, dict]:
        """Run the blocking pipeline on a worker thread.

        Everything below is CPU and subprocess work. Awaiting it directly on the
        event loop made `async` decorative: measured on the fixture set, eight
        labels took 12.9s at concurrency 1, 4 and 8 alike -- the semaphore was
        limiting work that was already serial. Tesseract runs as a subprocess so
        the GIL is released while it works, and a thread pool gives real
        parallelism. It also keeps a long batch from freezing the UI.
        """
        return await asyncio.to_thread(self._extract_sync, prepared)

    def _extract_sync(self, prepared: PreparedImage) -> tuple[dict, dict]:
        started = time.perf_counter()
        image = prepared.image

        words, unresolved, weak = self._read(image)
        lines = layout.build_lines(words)
        layout.rescue_units(lines, weak)

        warning_text, warning_block = layout.extract_warning(lines)
        warning_indices = {i for i, ln in enumerate(lines) if ln in warning_block}
        warning_start = min(warning_indices) if warning_indices else None

        brand, class_type, dominance = layout.pick_brand_and_class(lines, warning_indices)
        degraded = bool(lines) and dominance < BRAND_DOMINANCE_FLOOR
        if degraded:
            # The most prominent element on the label did not survive the
            # photograph. Nothing read from it is trustworthy, so the whole
            # label goes to a human rather than being rejected on bad evidence.
            brand = None
        class_next = layout.pick_class_continuation(lines, warning_indices)
        alcohol = layout.pick_alcohol_statement(lines, warning_indices)
        net_contents = layout.pick_net_contents(lines, warning_indices)
        country = layout.pick_country(lines, warning_indices)
        bottler_name, bottler_address = layout.pick_bottler(
            lines,
            warning_indices | {i for i, ln in enumerate(lines)
                               if ln.text.strip() in {brand, class_type}},
            warning_start=warning_start,
        )

        binary = np.asarray(binarize(image), dtype=np.uint8)
        prefix_bold = self._prefix_is_bold(binary, warning_block)

        # Legibility: did we read it, fail to read it, or is it truly absent?
        if warning_text:
            block_conf = sum(ln.conf for ln in warning_block) / len(warning_block)
            glyph_px = min(ln.height for ln in warning_block)
            legible = block_conf >= LEGIBLE_CONF and glyph_px >= MIN_LEGIBLE_GLYPH_PX
            legibility = "read" if legible else "illegible"
        elif unresolved > 0:
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

        def lines_for(value: str | None) -> list[Line]:
            if not value:
                return []
            return [ln for ln in lines if value in ln.text or ln.text in value][:1]

        def quad(words_in: list[Word]) -> list[list[float]] | None:
            if not words_in:
                return None
            pad = 6
            return prepared.to_display_quad(
                min(w.left for w in words_in) - pad, min(w.top for w in words_in) - pad,
                max(w.right for w in words_in) + pad, max(w.bottom for w in words_in) + pad,
            )

        def box_of(value: str | None) -> list[list[float]] | None:
            return quad([w for ln in lines_for(value) for w in ln.words])

        def brand_box() -> list[list[float]] | None:
            if not brand:
                return None
            parts = [ln for ln in lines if ln.text.strip() and ln.text.strip() in brand]
            tallest = max((ln.height for ln in parts), default=0)
            return quad([w for ln in parts if ln.height >= tallest * 0.85 for w in ln.words])

        prefix_words = [w for w in (warning_block[0].words if warning_block else [])
                        if w.text.upper().strip(":").strip() in ("GOVERNMENT", "WARNING")]
        # Where each field was read, for the agent to see. Evidence only: no
        # rule reads these.
        field_boxes = {
            key: box for key, box in {
                "brand_name": brand_box(),
                "class_type": box_of(class_type),
                "alcohol_content": box_of(alcohol),
                "net_contents": box_of(net_contents),
                "bottler_name": box_of(bottler_name),
                "bottler_address": box_of(bottler_address),
                "country_of_origin": box_of(country),
                "government_warning": quad([w for ln in warning_block for w in ln.words]),
                "warning_typography": quad(prefix_words),
            }.items() if box is not None
        }

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
            "class_type_next": class_next,
            "alcohol_statement": alcohol,
            "net_contents": net_contents,
            "bottler_name": bottler_name,
            "bottler_address": bottler_address,
            "country_of_origin": country,
            "warning_text": warning_text,
            "warning_prefix_is_bold": prefix_bold,
            "warning_legibility": legibility,
            # Type this small is a size question, whoever reads the words.
            "warning_small_type": bool(warning_block) and min(
                ln.height for ln in warning_block) < MIN_LEGIBLE_GLYPH_PX,
            "legibility_notes": notes,
            "field_boxes": field_boxes,
            "field_confidence": {
                key: (DEGRADED_CONFIDENCE if degraded else value)
                for key, value in {
                    "brand_name": line_conf(brand),
                    "class_type": line_conf(class_type),
                    "alcohol_content": line_conf(alcohol),
                    "proof_consistency": line_conf(alcohol),
                    "net_contents": line_conf(net_contents),
                    "bottler_name": line_conf(bottler_name),
                    "bottler_address": line_conf(bottler_address),
                    "country_of_origin": line_conf(country),
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
