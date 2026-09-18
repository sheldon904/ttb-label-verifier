"""Cloud vision-model extractor (default).

Latency notes -- Sarah Chen's only hard number is ~5 seconds:
  * downscale to MAX_IMAGE_EDGE_PX before the call; this is the single biggest
    lever, usually larger than model choice
  * one round trip, schema-constrained output, capped max_tokens
  * cache by image hash
Measured p50/p95 belong in the README, not an adjective.
"""

from __future__ import annotations

from app.models import LabelExtraction

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "brand_name": {"type": ["string", "null"]},
        "class_type": {"type": ["string", "null"]},
        "alcohol_statement": {"type": ["string", "null"],
                              "description": "Verbatim, e.g. '45% Alc./Vol. (90 Proof)'"},
        "net_contents": {"type": ["string", "null"]},
        "bottler_name": {"type": ["string", "null"]},
        "bottler_address": {"type": ["string", "null"]},
        "country_of_origin": {"type": ["string", "null"]},
        "warning_text": {"type": ["string", "null"],
                         "description": "Verbatim transcription including the prefix. Do not correct it."},
        "warning_prefix_is_bold": {"type": ["boolean", "null"]},
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["brand_name", "warning_text"],
}


class VlmExtractor:
    name = "vlm"

    async def extract(self, image_bytes: bytes) -> LabelExtraction:
        raise NotImplementedError("Next step: downscale, then one schema-constrained call.")
