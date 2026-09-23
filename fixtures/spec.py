"""Fixture definitions: what each generated label says, and what the system
should conclude about it.

The spec IS the ground truth. Because the label is rendered from this data, the
expected extraction is known exactly -- no hand-labeling, and no ambiguity about
whether a miss was the model's fault or the annotator's.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.rules.warning import STATUTORY_WARNING

TITLE_CASE_WARNING = STATUTORY_WARNING.replace("GOVERNMENT WARNING:", "Government Warning:")
REWORDED_WARNING = STATUTORY_WARNING.replace(
    "women should not drink alcoholic beverages during pregnancy",
    "women may wish to avoid alcoholic beverages during pregnancy",
)


@dataclass
class LabelSpec:
    """What gets printed on the artwork."""

    brand_name: str
    class_type: str
    alcohol_statement: str
    net_contents: str | None
    bottler_name: str
    bottler_address: str
    country_of_origin: str | None = None
    warning_text: str | None = STATUTORY_WARNING
    warning_prefix_bold: bool = True
    warning_point_size: int = 13
    # "classic": centred sans-serif, warning last. "modern": left-aligned serif
    # with a line of small print under the warning. The second template exists
    # to find out whether the layout heuristics generalise beyond the first.
    # "stress": the shapes an outside reviewer's own labels broke, drawn on
    # purpose (see render_stress).
    template: str = "classic"
    footer_text: str | None = None
    # stress template only
    brand_split: int = 0            # words on the brand's first line; 0 is one line
    dark: bool = False              # light type on a dark label
    scale: int = 1                  # render at this multiple, as a high-resolution scan
    statement_one_line: bool = False  # net contents on the alcohol statement's line


@dataclass
class Degradation:
    """Jenny Park: 'photographed at weird angles, or the lighting is bad, or
    there's glare on the bottle.'"""

    rotate_deg: float = 0.0
    blur_radius: float = 0.0
    glare: bool = False
    jpeg_quality: int | None = None


@dataclass
class Fixture:
    id: str
    description: str
    spec: LabelSpec
    record: dict
    expected_verdict: str
    expected_failing_fields: list[str] = field(default_factory=list)
    degradation: Degradation = field(default_factory=Degradation)
    # None means "a human could not judge boldness from this artwork either",
    # so the extractor returning null is the correct answer, not a miss.
    truth_bold: bool | None = None


# --- base products ---------------------------------------------------------

OLD_TOM = dict(
    brand_name="OLD TOM DISTILLERY",
    class_type="Kentucky Straight Bourbon Whiskey",
    alcohol_statement="45% Alc./Vol. (90 Proof)",
    net_contents="750 mL",
    bottler_name="Old Tom Distilling Co.",
    bottler_address="Bardstown, Kentucky",
    country_of_origin="Product of the United States",
)

STONES_THROW = dict(
    brand_name="STONE'S THROW",
    class_type="Straight Rye Whiskey",
    alcohol_statement="50% Alc./Vol. (100 Proof)",
    net_contents="750 mL",
    bottler_name="Stone's Throw Spirits LLC",
    bottler_address="Portland, Oregon",
    country_of_origin="Product of the United States",
)

COPPER_RIDGE = dict(
    brand_name="COPPER RIDGE RESERVE",
    class_type="Single Malt Whisky",
    alcohol_statement="43% Alc./Vol. (86 Proof)",
    net_contents="700 mL",
    bottler_name="Copper Ridge Distillers",
    bottler_address="Inverness, Scotland",
    country_of_origin="Product of Scotland",
)


BELLE_RIVE = dict(
    brand_name="CHATEAU BELLE RIVE",
    class_type="Cabernet Sauvignon",
    alcohol_statement="13.5% Alc./Vol.",
    net_contents="750 mL",
    bottler_name="Belle Rive Cellars",
    bottler_address="Napa, California",
    country_of_origin="Product of the United States",
)

HARBOR_LIGHT = dict(
    brand_name="HARBOR LIGHT",
    class_type="India Pale Ale",
    alcohol_statement="6.5% ALC/VOL",
    net_contents="12 FL OZ",
    bottler_name="Harbor Light Brewing Co.",
    bottler_address="Portland, Maine",
    country_of_origin="Product of the United States",
)

BODY_CAPS_WARNING = "GOVERNMENT WARNING: " + STATUTORY_WARNING[len("GOVERNMENT WARNING: "):].upper()


def _modern(base: dict, footer: str = "www.example-distillery.com", **overrides) -> LabelSpec:
    return LabelSpec(**{**base, **overrides}, template="modern", footer_text=footer)


CASA_LUNA = {
    "brand_name": "CASA LUNA",
    "class_type": "100% Blue Agave Tequila",
    "alcohol_statement": "40% Alc./Vol. (80 Proof)",
    "net_contents": "750 mL",
    "bottler_name": "Imported by Harbor Imports",
    "bottler_address": "New York, New York",
    "country_of_origin": "Product of Mexico",
}

# How a distillery often words it on the label; the application has the name.
OLD_TOM_STATED = {**OLD_TOM, "bottler_name": "Distilled and bottled by Old Tom Distilling Co."}


def _stress(base: dict, **overrides) -> LabelSpec:
    return LabelSpec(**{**base, **overrides}, template="stress")


def _record(cola_id: str, base: dict, **overrides) -> dict:
    """The COLA application record an agent checks the artwork against."""
    rec = {
        "cola_id": cola_id,
        "brand_name": base["brand_name"].title().replace("'S", "'s"),
        "class_type": base["class_type"],
        "alcohol_content_pct": float(base["alcohol_statement"].split("%")[0]),
        "net_contents": base["net_contents"],
        "bottler_name": base["bottler_name"],
        "bottler_address": base["bottler_address"],
        "country_of_origin": base["country_of_origin"],
    }
    rec.update(overrides)
    return rec


def build_catalog() -> list[Fixture]:
    f: list[Fixture] = []

    # --- clean passes, one per product -----------------------------------
    for n, (cid, base) in enumerate(
        [("24-001", OLD_TOM), ("24-002", STONES_THROW), ("24-003", COPPER_RIDGE)], start=1
    ):
        f.append(Fixture(
            id=f"clean_{n:02d}",
            description=f"Compliant label, {base['brand_name'].title()}",
            spec=LabelSpec(**base),
            record=_record(cid, base),
            expected_verdict="pass",
            truth_bold=True,
        ))

    # --- Dave Morrison's case: casing differs, meaning does not -----------
    f.append(Fixture(
        id="brand_case_difference",
        description="Label is all caps, application is title case. Dave: 'obviously the same thing.'",
        spec=LabelSpec(**STONES_THROW),
        record=_record("24-010", STONES_THROW, brand_name="Stone's Throw"),
        expected_verdict="pass",
        truth_bold=True,
    ))
    f.append(Fixture(
        id="brand_near_miss",
        description="One character apart -- ambiguous, must escalate rather than guess",
        spec=LabelSpec(**{**OLD_TOM, "brand_name": "OLD TIM DISTILLERY"}),
        record=_record("24-011", OLD_TOM),
        expected_verdict="flag",
        expected_failing_fields=["brand_name"],
        truth_bold=True,
    ))
    f.append(Fixture(
        id="brand_wrong",
        description="Entirely different brand on the artwork",
        spec=LabelSpec(**{**OLD_TOM, "brand_name": "COPPER RIDGE RESERVE"}),
        record=_record("24-012", OLD_TOM),
        expected_verdict="fail",
        expected_failing_fields=["brand_name"],
        truth_bold=True,
    ))

    # --- Jenny Park's cases: the warning must be exact --------------------
    f.append(Fixture(
        id="warning_title_case",
        description="'Government Warning:' in title case -- the rejection Jenny caught",
        spec=LabelSpec(**OLD_TOM, warning_text=TITLE_CASE_WARNING),
        record=_record("24-020", OLD_TOM),
        expected_verdict="fail",
        expected_failing_fields=["government_warning"],
        truth_bold=True,
    ))
    f.append(Fixture(
        id="warning_reworded",
        description="Softened wording -- 'may wish to avoid' instead of 'should not drink'",
        spec=LabelSpec(**OLD_TOM, warning_text=REWORDED_WARNING),
        record=_record("24-021", OLD_TOM),
        expected_verdict="fail",
        expected_failing_fields=["government_warning"],
        truth_bold=True,
    ))
    f.append(Fixture(
        id="warning_missing",
        description="No health warning statement at all",
        spec=LabelSpec(**OLD_TOM, warning_text=None),
        record=_record("24-022", OLD_TOM),
        expected_verdict="fail",
        expected_failing_fields=["government_warning"],
        truth_bold=None,
    ))
    f.append(Fixture(
        id="warning_prefix_not_bold",
        description="Correct text, but the prefix is set in regular weight -- advisory only",
        spec=LabelSpec(**OLD_TOM, warning_prefix_bold=False),
        record=_record("24-023", OLD_TOM),
        expected_verdict="flag",
        expected_failing_fields=["warning_typography"],
        truth_bold=False,
    ))
    f.append(Fixture(
        id="warning_microtype",
        description="Text buried at ~6pt -- too small to judge weight, must not guess",
        spec=LabelSpec(**OLD_TOM, warning_point_size=6),
        record=_record("24-024", OLD_TOM),
        expected_verdict="flag",
        expected_failing_fields=["warning_typography"],
        truth_bold=None,
    ))

    # --- alcohol content --------------------------------------------------
    f.append(Fixture(
        id="abv_mismatch",
        description="Label states 40%, application says 45%",
        spec=LabelSpec(**{**OLD_TOM, "alcohol_statement": "40% Alc./Vol. (80 Proof)"}),
        record=_record("24-030", OLD_TOM),
        expected_verdict="fail",
        expected_failing_fields=["alcohol_content"],
        truth_bold=True,
    ))
    f.append(Fixture(
        id="proof_inconsistent",
        description="Label contradicts itself: 45% is 90 proof, not 80",
        spec=LabelSpec(**{**OLD_TOM, "alcohol_statement": "45% Alc./Vol. (80 Proof)"}),
        record=_record("24-031", OLD_TOM),
        expected_verdict="fail",
        expected_failing_fields=["proof_consistency"],
        truth_bold=True,
    ))
    f.append(Fixture(
        id="abv_no_proof",
        description="ABV only, no proof statement -- perfectly legal",
        spec=LabelSpec(**{**OLD_TOM, "alcohol_statement": "45% Alc./Vol."}),
        record=_record("24-032", OLD_TOM),
        expected_verdict="pass",
        truth_bold=True,
    ))

    # --- net contents -----------------------------------------------------
    f.append(Fixture(
        id="net_contents_centilitres",
        description=("'75 cl' alone against '750 mL': the same volume, but 27 CFR 5.70(a) "
                     "asks for liters or milliliters, so it is referred"),
        spec=LabelSpec(**{**COPPER_RIDGE, "net_contents": "75 cl"}),
        record=_record("24-040", COPPER_RIDGE, net_contents="750 mL"),
        expected_verdict="flag",
        expected_failing_fields=["net_contents"],
        truth_bold=True,
    ))
    f.append(Fixture(
        id="net_contents_missing",
        description="Net contents absent from the artwork",
        spec=LabelSpec(**{**OLD_TOM, "net_contents": None}),
        record=_record("24-041", OLD_TOM),
        expected_verdict="fail",
        expected_failing_fields=["net_contents"],
        truth_bold=True,
    ))
    f.append(Fixture(
        id="net_contents_wrong",
        description="700 mL on the label, 750 mL on the application",
        spec=LabelSpec(**{**OLD_TOM, "net_contents": "700 mL"}),
        record=_record("24-042", OLD_TOM),
        expected_verdict="fail",
        expected_failing_fields=["net_contents"],
        truth_bold=True,
    ))

    # --- image quality: compliant labels, badly photographed --------------
    f.append(Fixture(
        id="photo_skewed",
        description="Compliant label shot at an angle",
        spec=LabelSpec(**OLD_TOM),
        record=_record("24-050", OLD_TOM),
        expected_verdict="pass",
        degradation=Degradation(rotate_deg=7.0),
        truth_bold=True,
    ))
    f.append(Fixture(
        id="photo_glare",
        description="Compliant label with specular glare across the upper third",
        spec=LabelSpec(**STONES_THROW),
        record=_record("24-051", STONES_THROW),
        expected_verdict="pass",
        degradation=Degradation(glare=True),
        truth_bold=True,
    ))
    f.append(Fixture(
        id="photo_soft_focus",
        description="Compliant label, slightly out of focus",
        spec=LabelSpec(**COPPER_RIDGE),
        record=_record("24-052", COPPER_RIDGE),
        expected_verdict="pass",
        degradation=Degradation(blur_radius=1.4),
        truth_bold=True,
    ))
    f.append(Fixture(
        id="photo_compressed",
        description="Heavily re-compressed JPEG, as arrives from email chains",
        spec=LabelSpec(**OLD_TOM),
        record=_record("24-053", OLD_TOM),
        expected_verdict="pass",
        degradation=Degradation(jpeg_quality=22, rotate_deg=-3.0),
        truth_bold=True,
    ))
    f.append(Fixture(
        id="photo_skewed_and_defective",
        description="Angled shot AND a title-case warning -- degradation must not mask a real defect",
        spec=LabelSpec(**OLD_TOM, warning_text=TITLE_CASE_WARNING),
        record=_record("24-054", OLD_TOM),
        expected_verdict="fail",
        expected_failing_fields=["government_warning"],
        degradation=Degradation(rotate_deg=-6.0, blur_radius=0.8),
        truth_bold=True,
    ))

    # --- second template: does any of this generalise? ---------------------
    f.append(Fixture(
        id="v2_wine_clean",
        description="Second template: compliant wine, serif, web address under the warning",
        spec=_modern(BELLE_RIVE, footer="www.bellerive.example"),
        record=_record("25-001", BELLE_RIVE),
        expected_verdict="pass",
        truth_bold=True,
    ))
    f.append(Fixture(
        id="v2_malt_floz",
        description="Second template: '12 FL OZ' on the label, '355 mL' on the application",
        spec=_modern(HARBOR_LIGHT, footer="Brewed and canned in Portland, Maine"),
        record=_record("25-002", HARBOR_LIGHT, net_contents="355 mL"),
        expected_verdict="pass",
        truth_bold=True,
    ))
    f.append(Fixture(
        id="v2_malt_floz_wrong",
        description="Second template: '16 FL OZ' on the label, '355 mL' on the application",
        spec=_modern(HARBOR_LIGHT, net_contents="16 FL OZ"),
        record=_record("25-003", HARBOR_LIGHT, net_contents="355 mL"),
        expected_verdict="fail",
        expected_failing_fields=["net_contents"],
        truth_bold=True,
    ))
    f.append(Fixture(
        id="v2_import_wrong_country",
        description="Second template: Scotch declared Scottish, label says Canada",
        spec=_modern(COPPER_RIDGE, country_of_origin="Product of Canada"),
        record=_record("25-004", COPPER_RIDGE),
        expected_verdict="fail",
        expected_failing_fields=["country_of_origin"],
        truth_bold=True,
    ))
    f.append(Fixture(
        id="v2_title_case",
        description="Second template: title-case warning prefix",
        spec=_modern(OLD_TOM, warning_text=TITLE_CASE_WARNING),
        record=_record("25-005", OLD_TOM),
        expected_verdict="fail",
        expected_failing_fields=["government_warning"],
        truth_bold=True,
    ))
    f.append(Fixture(
        id="v2_body_caps",
        description="Second template: whole statement in capitals; 16.22 regulates only the prefix",
        spec=_modern(OLD_TOM, warning_text=BODY_CAPS_WARNING),
        record=_record("25-006", OLD_TOM),
        expected_verdict="pass",
        truth_bold=True,
    ))
    f.append(Fixture(
        id="v2_body_caps_not_bold",
        description="Second template: whole statement in capitals, prefix in regular weight",
        spec=_modern(OLD_TOM, warning_text=BODY_CAPS_WARNING, warning_prefix_bold=False),
        record=_record("25-008", OLD_TOM),
        expected_verdict="flag",
        expected_failing_fields=["warning_typography"],
        truth_bold=False,
    ))
    f.append(Fixture(
        id="v2_photo_skewed",
        description="Second template: compliant wine photographed at an angle",
        spec=_modern(BELLE_RIVE, footer="www.bellerive.example"),
        record=_record("25-007", BELLE_RIVE),
        expected_verdict="pass",
        degradation=Degradation(rotate_deg=5.0),
        truth_bold=True,
    ))


    # --- third template: what an outside reviewer's labels broke ------------
    f.append(Fixture(
        id="v3_stacked_brand",
        description="Third template: brand set on two lines in two sizes",
        spec=_stress(OLD_TOM_STATED, brand_split=2),
        record=_record("26-001", OLD_TOM),
        expected_verdict="pass",
        truth_bold=True,
    ))
    f.append(Fixture(
        id="v3_dark_label",
        description="Third template: light serif type on a dark label, brand on two lines",
        spec=_stress(OLD_TOM_STATED, brand_split=2, dark=True),
        record=_record("26-002", OLD_TOM),
        expected_verdict="pass",
        truth_bold=True,
    ))
    f.append(Fixture(
        id="v3_large_scan",
        description="Third template: a 2700 x 3900 pixel scan",
        spec=_stress(OLD_TOM_STATED, brand_split=2, scale=3),
        record=_record("26-003", OLD_TOM),
        expected_verdict="pass",
        truth_bold=True,
    ))
    f.append(Fixture(
        id="v3_one_line_statement",
        description="Third template: net contents on the same line as the alcohol statement",
        spec=_stress(OLD_TOM_STATED, statement_one_line=True),
        record=_record("26-004", OLD_TOM),
        expected_verdict="pass",
        truth_bold=True,
    ))
    f.append(Fixture(
        id="v3_import_agave",
        description="Third template: imported tequila; '100% Blue Agave' is the class, not the strength",
        spec=_stress(CASA_LUNA),
        record=_record("26-005", CASA_LUNA, bottler_name="Harbor Imports",
                       country_of_origin="Mexico"),
        expected_verdict="pass",
        truth_bold=True,
    ))
    f.append(Fixture(
        id="v3_dark_title_case",
        description="Third template: dark label with a title-case warning prefix",
        spec=_stress(OLD_TOM_STATED, brand_split=2, dark=True, warning_text=TITLE_CASE_WARNING),
        record=_record("26-006", OLD_TOM),
        expected_verdict="fail",
        expected_failing_fields=["government_warning"],
        truth_bold=True,
    ))
    f.append(Fixture(
        id="v3_abv_wrong",
        description="Third template: stacked brand, label states 40% against 45% on the application",
        spec=_stress(OLD_TOM_STATED, brand_split=2,
                     alcohol_statement="40% Alc./Vol. (80 Proof)"),
        record=_record("26-007", OLD_TOM),
        expected_verdict="fail",
        expected_failing_fields=["alcohol_content"],
        truth_bold=True,
    ))

    return f
