"""Renders a LabelSpec to a PNG that looks like real label artwork.

Rendering rather than sourcing images is what makes the eval set trustworthy:
the ground truth is the spec, so a failed check is unambiguously the extractor's
miss and never an annotation error. It also lets the warning prefix be drawn in
genuine bold or genuine regular weight, which is the only way to actually test
the 27 CFR 16.22 typography path.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from fixtures.spec import Degradation, LabelSpec

W, H = 760, 1040
MARGIN = 54
CREAM = (247, 243, 233)
INK = (26, 24, 22)
RULE = (150, 138, 118)

_FONT_CANDIDATES = {
    "regular": [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ],
    "bold": [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ],
    "serif": [
        "/System/Library/Fonts/Supplemental/Georgia.ttf",
        "C:/Windows/Fonts/georgia.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    ],
    "serif-bold": [
        "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
        "C:/Windows/Fonts/georgiab.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    ],
    "times": [
        "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
        "C:/Windows/Fonts/times.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
    ],
    "times-bold": [
        "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
        "C:/Windows/Fonts/timesbd.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
    ],
}


class MissingFontError(RuntimeError):
    pass


def _font_path(weight: str) -> str:
    for candidate in _FONT_CANDIDATES[weight]:
        if Path(candidate).is_file():
            return candidate
    raise MissingFontError(
        f"No {weight} font found. Fixture images are committed to the repo, so you only "
        f"need fonts if you are regenerating them. Tried: {_FONT_CANDIDATES[weight]}"
    )


def font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(_font_path(weight), size)


def _text_w(draw: ImageDraw.ImageDraw, text: str, f: ImageFont.FreeTypeFont) -> float:
    return draw.textlength(text, font=f)


def _centered(draw, y: int, text: str, f, fill=INK) -> int:
    w = _text_w(draw, text, f)
    draw.text(((W - w) / 2, y), text, font=f, fill=fill)
    return y + int(f.size * 1.35)


def _centered_wrapped(draw, y: int, text: str, f, max_w: int, fill=INK) -> int:
    words, line = text.split(), ""
    for word in words:
        trial = f"{line} {word}".strip()
        if _text_w(draw, trial, f) <= max_w:
            line = trial
        else:
            y = _centered(draw, y, line, f, fill)
            line = word
    if line:
        y = _centered(draw, y, line, f, fill)
    return y


def _draw_warning(draw, y: int, text: str, size: int, prefix_bold: bool, max_w: int,
                  family: str = "", ink=INK, margin: int = MARGIN) -> int:
    """Draw the warning with its prefix in a distinct weight.

    Tokenizes into (word, font) pairs so the prefix can carry real bold weight
    while the body stays regular, then wraps across that mixed run.
    """
    regular = font(family or "regular", size)
    bold = font(f"{family}-bold" if family else "bold", size)
    prefix = "GOVERNMENT WARNING:"

    tokens: list[tuple[str, ImageFont.FreeTypeFont]] = []
    if text.upper().startswith(prefix):
        head, tail = text[: len(prefix)], text[len(prefix):]
        head_font = bold if prefix_bold else regular
        tokens += [(w, head_font) for w in head.split()]
        tokens += [(w, regular) for w in tail.split()]
    else:
        tokens = [(w, regular) for w in text.split()]

    space = _text_w(draw, " ", regular)
    line: list[tuple[str, ImageFont.FreeTypeFont]] = []
    line_w = 0.0

    def flush(cur_y: int, run) -> int:
        x = margin
        for word, wf in run:
            draw.text((x, cur_y), word, font=wf, fill=ink)
            x += _text_w(draw, word, wf) + space
        return cur_y + int(size * 1.45)

    for word, wf in tokens:
        w = _text_w(draw, word, wf)
        if line and line_w + space + w > max_w:
            y = flush(y, line)
            line, line_w = [(word, wf)], w
        else:
            line_w = line_w + space + w if line else w
            line.append((word, wf))
    if line:
        y = flush(y, line)
    return y


def _left_wrapped(draw, y: int, text: str, f, max_w: int, fill) -> int:
    words, line = text.split(), ""
    for word in words:
        trial = f"{line} {word}".strip()
        if _text_w(draw, trial, f) <= max_w:
            line = trial
        else:
            draw.text((MARGIN, y), line, font=f, fill=fill)
            y += int(f.size * 1.3)
            line = word
    if line:
        draw.text((MARGIN, y), line, font=f, fill=fill)
        y += int(f.size * 1.3)
    return y


NAVY = (22, 32, 48)
PAPER = (251, 250, 246)


def render_modern(spec: LabelSpec) -> Image.Image:
    """Left-aligned serif artwork with small print under the warning."""
    img = Image.new("RGB", (W, H), PAPER)
    draw = ImageDraw.Draw(img)
    max_w = W - 2 * MARGIN
    draw.rectangle([MARGIN - 20, 40, MARGIN - 12, 230], fill=NAVY)

    y = 70
    y = _left_wrapped(draw, y, spec.brand_name, font("serif-bold", 52), max_w, NAVY)
    y += 10
    y = _left_wrapped(draw, y, spec.class_type, font("serif", 25), max_w, NAVY)
    y += 30
    draw.line([(MARGIN, y), (W - MARGIN, y)], fill=NAVY, width=2)
    y += 34
    for text, size in ((spec.alcohol_statement, 25), (spec.net_contents, 25)):
        if text:
            draw.text((MARGIN, y), text, font=font("serif", size), fill=NAVY)
            y += int(size * 1.5)
    y += 30
    for text, size in ((spec.bottler_name, 18), (spec.bottler_address, 18),
                       (spec.country_of_origin, 16)):
        if text:
            draw.text((MARGIN, y), text, font=font("serif", size), fill=NAVY)
            y += int(size * 1.45)

    if spec.warning_text:
        wy = max(y + 60, H - 330)
        end = _draw_warning(draw, wy, spec.warning_text, spec.warning_point_size,
                            spec.warning_prefix_bold, max_w, family="serif", ink=NAVY)
        if spec.footer_text:
            draw.text((MARGIN, end + 22), spec.footer_text, font=font("serif", 13), fill=NAVY)
    return img


TAN, BROWN = (236, 222, 190), (60, 30, 10)
NIGHT, GOLD = (20, 30, 60), (230, 210, 150)


def render_stress(spec: LabelSpec) -> Image.Image:
    """The label shapes an outside reviewer drew to test the tool.

    Centred type on a taller card, with the options that broke an earlier
    version: a brand stacked over two lines in two sizes, light type on a
    dark card, a scan several times the usual resolution and the net contents
    on the alcohol statement's line.
    """
    s = spec.scale
    width, height = 900 * s, 1300 * s
    bg, fg = (NIGHT, GOLD) if spec.dark else (TAN, BROWN)
    regular, bold = ("times", "times-bold") if spec.dark else ("regular", "bold")
    img = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(img)

    def centred(y: int, text: str, weight: str, size: int) -> int:
        f = font(weight, size * s)
        draw.text(((width - _text_w(draw, text, f)) / 2, y), text, font=f, fill=fg)
        return y + (size + 40) * s

    words = spec.brand_name.split()
    y = 80 * s
    if spec.brand_split:
        y = centred(y, " ".join(words[:spec.brand_split]), bold, 110)
        y = centred(y, " ".join(words[spec.brand_split:]), bold, 80)
    else:
        y = centred(y, spec.brand_name, bold, 80)
    y = centred(y, spec.class_type, regular, 40)
    if spec.statement_one_line and spec.net_contents:
        y = centred(y, f"{spec.net_contents}   {spec.alcohol_statement}", regular, 44)
    else:
        y = centred(y, spec.alcohol_statement, regular, 44)
        if spec.net_contents:
            y = centred(y, spec.net_contents, regular, 44)
    for text in (spec.bottler_name, spec.bottler_address, spec.country_of_origin):
        if text:
            y = centred(y, text, regular, 26)

    if spec.warning_text:
        _draw_warning(draw, y + 60 * s, spec.warning_text, 22 * s, spec.warning_prefix_bold,
                      width - 140 * s, family="times" if spec.dark else "", ink=fg,
                      margin=70 * s)
    return img


def render_label(spec: LabelSpec) -> Image.Image:
    if spec.template == "modern":
        return render_modern(spec)
    if spec.template == "stress":
        return render_stress(spec)
    img = Image.new("RGB", (W, H), CREAM)
    draw = ImageDraw.Draw(img)
    max_w = W - 2 * MARGIN

    draw.rectangle([18, 18, W - 19, H - 19], outline=RULE, width=3)

    y = 110
    y = _centered_wrapped(draw, y, spec.brand_name, font("bold", 46), max_w)
    y += 18
    y = _centered_wrapped(draw, y, spec.class_type, font("regular", 24), max_w)

    y += 34
    draw.line([(MARGIN + 60, y), (W - MARGIN - 60, y)], fill=RULE, width=2)
    y += 40

    y = _centered(draw, y, spec.alcohol_statement, font("regular", 26))
    y += 10
    if spec.net_contents:
        y = _centered(draw, y, spec.net_contents, font("regular", 26))

    y += 44
    y = _centered(draw, y, spec.bottler_name, font("regular", 18))
    y = _centered(draw, y, spec.bottler_address, font("regular", 18))
    if spec.country_of_origin:
        y = _centered(draw, y, spec.country_of_origin, font("regular", 16))

    if spec.warning_text:
        warning_y = max(y + 60, H - 300)
        _draw_warning(draw, warning_y, spec.warning_text, spec.warning_point_size,
                      spec.warning_prefix_bold, max_w)

    return img


def apply_degradation(img: Image.Image, deg: Degradation) -> Image.Image:
    """Simulates the photographs Jenny described."""
    if deg.rotate_deg:
        img = img.rotate(deg.rotate_deg, resample=Image.BICUBIC,
                         expand=True, fillcolor=(58, 55, 52))
    if deg.glare:
        overlay = Image.new("L", img.size, 0)
        g = ImageDraw.Draw(overlay)
        w, h = img.size
        g.ellipse([int(w * 0.05), int(-h * 0.10), int(w * 0.95), int(h * 0.34)], fill=205)
        overlay = overlay.filter(ImageFilter.GaussianBlur(48))
        img = Image.composite(Image.new("RGB", img.size, (255, 255, 255)), img, overlay)
    if deg.blur_radius:
        img = img.filter(ImageFilter.GaussianBlur(deg.blur_radius))
    if deg.jpeg_quality:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=deg.jpeg_quality)
        img = Image.open(io.BytesIO(buf.getvalue())).convert("RGB")
    return img
