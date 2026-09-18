"""Cloud vision-model extractor (default implementation).

Observes the label. Returns no verdicts -- see app/models.py for why that
separation is the load-bearing decision in this codebase.
"""

from __future__ import annotations

import base64
import time

from anthropic import AsyncAnthropic

from app.config import Settings
from app.extract.preprocess import PreparedImage

TOOL_NAME = "record_label_observations"

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "brand_name": {"type": ["string", "null"],
                       "description": "The brand name as printed."},
        "class_type": {"type": ["string", "null"],
                       "description": "Class/type designation, e.g. 'Kentucky Straight Bourbon Whiskey'."},
        "alcohol_statement": {"type": ["string", "null"],
                              "description": "The complete alcohol content statement, verbatim, "
                                             "e.g. '45% Alc./Vol. (90 Proof)'."},
        "net_contents": {"type": ["string", "null"],
                         "description": "Net contents as printed, e.g. '750 mL'."},
        "bottler_name": {"type": ["string", "null"]},
        "bottler_address": {"type": ["string", "null"]},
        "country_of_origin": {"type": ["string", "null"]},
        "warning_text": {
            "type": ["string", "null"],
            "description": "The government warning statement transcribed EXACTLY as printed, "
                           "including its prefix and original capitalization. Do not correct it.",
        },
        "warning_prefix_is_bold": {
            "type": ["boolean", "null"],
            "description": "Whether the 'GOVERNMENT WARNING:' prefix is in noticeably heavier type "
                           "than the text that follows it. null if you cannot tell.",
        },
        "legibility_notes": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Anything impairing the read: glare, blur, skew, cropping, low contrast.",
        },
    },
    "required": ["brand_name", "warning_text", "warning_prefix_is_bold", "legibility_notes"],
}

# The single most important paragraph in this file.
#
# A vision model's default instinct is to be helpful: asked to transcribe
# "Government Warning:", it will hand back the canonical "GOVERNMENT WARNING:"
# because it knows that is the correct form. That silently destroys the only
# exact-match check in the system -- the tool would pass a label that a human
# agent would reject, and it would do so invisibly. Transcription fidelity is
# therefore stated three times and reinforced by a fixture in the eval set.
SYSTEM_PROMPT = """\
You are a transcription instrument for alcohol beverage label artwork. You report \
what is printed on the label. You never evaluate compliance, and you never state \
whether a label passes or fails -- that determination is made elsewhere.

Transcription rules, in order of importance:

1. TRANSCRIBE VERBATIM. Reproduce text exactly as printed, including its \
capitalization, punctuation, spacing and any misspellings. If the label reads \
"Government Warning:" in title case, report "Government Warning:" in title case. \
If it reads "GOVERNMENT WARNlNG:" with a lowercase L, report that. Do NOT correct, \
normalize, expand, standardize or improve any text. An error you preserve is useful; \
an error you silently fix is a defect in the system.

2. REPORT ABSENCE AS NULL. If a field is not present on the label, return null for \
it. Never infer a value from what a label of this type usually says, and never carry \
a value over from another field.

3. REPORT UNCERTAINTY HONESTLY. If glare, blur, skew or cropping prevents you from \
reading something, return null for that field and describe the problem in \
legibility_notes rather than guessing.

For warning_prefix_is_bold, compare the weight of the "GOVERNMENT WARNING:" prefix \
against the sentences that follow it. Return true only if the prefix is visibly \
heavier. Return null if the rendering is too small or too degraded to judge.

Call the record_label_observations tool exactly once."""

USER_PROMPT = (
    "Transcribe the fields on this alcohol beverage label. Reproduce all text exactly "
    "as printed, including the government warning statement and its original capitalization."
)


class VlmExtractor:
    """One image in, one structured observation out, one round trip."""

    name = "vlm"

    def __init__(self, settings: Settings) -> None:
        if not settings.anthropic_api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Set it in .env, or run with "
                "LABEL_EXTRACTOR=stub to use recorded fixture observations."
            )
        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._model = settings.vlm_model
        self.name = f"vlm:{settings.vlm_model}"

    async def extract_raw(self, raw: bytes, prepared: PreparedImage) -> tuple[dict, dict]:
        """Return (observations, telemetry). Telemetry feeds the eval report."""
        started = time.perf_counter()
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            temperature=0,
            system=SYSTEM_PROMPT,
            tools=[{
                "name": TOOL_NAME,
                "description": "Record the text observed on an alcohol beverage label.",
                "input_schema": EXTRACTION_SCHEMA,
            }],
            tool_choice={"type": "tool", "name": TOOL_NAME},
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {
                        "type": "base64",
                        "media_type": prepared.media_type,
                        "data": base64.b64encode(prepared.data).decode("ascii"),
                    }},
                    {"type": "text", "text": USER_PROMPT},
                ],
            }],
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        observations: dict = {}
        for block in response.content:
            if block.type == "tool_use" and block.name == TOOL_NAME:
                observations = dict(block.input)
                break

        telemetry = {
            "model": self._model,
            "elapsed_ms": elapsed_ms,
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "image_bytes": prepared.final_bytes,
        }
        return observations, telemetry
