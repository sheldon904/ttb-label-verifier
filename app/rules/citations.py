"""Which regulation each check cites, by commodity.

TTB labels wine under 27 CFR part 4, distilled spirits under part 5 and malt
beverages under part 7, and the section numbers differ between them. Every
section below was read on eCFR (Title 27 as amended 2026-09-16). The health
warning (part 16) is common to all three and is cited in warning.py.

The application record carries no commodity field, so the commodity is
inferred from the class/type designation. When that says nothing ("Special
Reserve"), the citation names all three parts.
"""

from __future__ import annotations

import re
from typing import Literal

Commodity = Literal["wine", "spirits", "malt"]

# The last designation word decides: "Bourbon Barrel Aged Stout" is a malt
# beverage and "Kentucky Straight Bourbon Whiskey" is a spirit.
_WORDS: dict[Commodity, str] = {
    # "Barley wine" is an ale; matched whole, so its "wine" never counts.
    "malt": (r"beer|ale|lager|stout|porter|pilsner|pilsener|ipa|malt beverage|malt liquor|bock"
             r"|hefeweizen|weissbier|saison|k[oö]lsch|hard seltzer|barley\s*wine"),
    "wine": (r"wine|champagne|sparkling|cabernet|sauvignon|chardonnay|merlot|pinot|riesling"
             r"|zinfandel|syrah|shiraz|malbec|ros[eé]|port|sherry|madeira|vermouth|sake|cider"
             r"|mead|prosecco|cava|grenache|tempranillo|sangiovese|chianti|moscato|muscat|claret"),
    "spirits": (r"whiskey|whisky|bourbon|scotch|rye|vodka|gin|rum|tequila|mezcal|brandy|cognac"
                r"|armagnac|liqueur|cordial|schnapps|absinthe|grappa|pisco|spirits?|aquavit"
                r"|soju|shochu|baijiu"),
}
_PATTERN = re.compile(
    "|".join(rf"(?P<{name}>\b(?:{words})\b)" for name, words in _WORDS.items()), re.IGNORECASE)


def commodity_of(*designations: str | None) -> Commodity | None:
    """The commodity named by the first designation that names one."""
    for text in designations:
        if not text:
            continue
        found = list(_PATTERN.finditer(text))
        if found:
            return found[-1].lastgroup  # type: ignore[return-value]
    return None


# field -> (wine, spirits, malt), each "section (subject)"
_SECTIONS: dict[str, tuple[str, str, str]] = {
    "brand_name": ("4.33", "5.64", "7.64"),
    "class_type": ("4.34 and subpart C", "5.63(a)(2) and subpart I", "7.63(a)(2) and 7.141"),
    "alcohol_content": ("4.36", "5.65", "7.65"),
    "alcohol_format": ("4.36", "5.65(b)", "7.65"),
    "proof_consistency": ("4.36", "5.65", "7.65"),
    "net_contents": ("4.37", "5.70", "7.70"),
    "bottler_name": ("4.35", "5.66-5.68", "7.66-7.68"),
    "bottler_address": ("4.35", "5.66-5.68", "7.66-7.68"),
    # Each part only cross-refers country of origin to the CBP marking rule.
    "country_of_origin": ("4.35(e)", "5.69", "7.69"),
}
_SUBJECT = {
    "brand_name": "brand name",
    "class_type": "class and type",
    "alcohol_content": "alcohol content",
    "alcohol_format": "alcohol content statement",
    "proof_consistency": "alcohol content",
    "net_contents": "net contents",
    "bottler_name": "name and address",
    "bottler_address": "name and address",
    "country_of_origin": "country of origin",
}
_INDEX = {"wine": 0, "spirits": 1, "malt": 2}


def citation(field: str, commodity: Commodity | None) -> str | None:
    """The citation for a check, or None when the field is not in the table."""
    if field not in _SECTIONS:
        return None
    wine, spirits, malt = _SECTIONS[field]
    cbp = " and 19 CFR 134.11" if field == "country_of_origin" else ""
    if commodity is None:
        return (f"27 CFR {spirits} (spirits), {wine} (wine) or {malt} (malt beverages)"
                f"{cbp}: {_SUBJECT[field]}")
    return f"27 CFR {_SECTIONS[field][_INDEX[commodity]]}{cbp} ({_SUBJECT[field]})"
