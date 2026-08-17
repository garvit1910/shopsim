"""Perception output schema (Phase 2.2) — strict structured output constrained
to the closed Concept enum (Law 11: unknown claims map to OTHER, enforced at
parse time; vocabulary drift refuses to load).

The LLM sees only what the ad itself shows a shopper (name, headline, body,
brand id, offered product ids) — never the authored ground-truth claims, never
catalog attributes, never latent props. It records claims and claimed
discounts; it never decides CLICK/BROWSE/CART/BUY.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..contracts.enums import Concept

CONCEPT_NAMES = tuple(c.name for c in Concept)

# OpenAI strict-mode JSON schema (bounds are validated in parse_output —
# strict mode rejects unsupported keywords like minimum/maximum).
OUTPUT_JSON_SCHEMA = {
    "name": "ad_perception",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["claims", "claimed_discounts"],
        "properties": {
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["concept", "strength"],
                    "properties": {
                        "concept": {"type": "string", "enum": list(CONCEPT_NAMES)},
                        "strength": {"type": "number"},
                    },
                },
            },
            "claimed_discounts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["product_id", "claimed_pct"],
                    "properties": {
                        "product_id": {"type": "integer"},
                        "claimed_pct": {"type": "number"},
                    },
                },
            },
        },
    },
}


@dataclass(frozen=True)
class PerceivedCreative:
    creative_id: int
    brand_id: int
    claims: tuple[tuple[int, float], ...]  # (concept_id, strength), sorted
    offers: tuple[tuple[int, float], ...]  # (product_id, claimed_pct), sorted

    @property
    def claims_dict(self) -> dict[int, float]:
        return dict(self.claims)

    @property
    def offers_dict(self) -> dict[int, float]:
        return dict(self.offers)


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(x)))


def parse_output(
    creative_id: int, brand_id: int, offer_product_ids: list[int], output: dict
) -> PerceivedCreative:
    """Validate a raw structured output into a PerceivedCreative. Raises
    ValueError on schema violations; maps unknown concept names to OTHER."""
    if not isinstance(output, dict) or "claims" not in output or "claimed_discounts" not in output:
        raise ValueError("perception output must have 'claims' and 'claimed_discounts'")

    claims: dict[int, float] = {}
    for row in output["claims"]:
        name = row["concept"]
        concept = Concept[name] if name in Concept.__members__ else Concept.OTHER
        strength = _clamp(row["strength"], 0.0, 1.0)
        claims[int(concept)] = max(claims.get(int(concept), 0.0), strength)

    discounts = {}
    for row in output["claimed_discounts"]:
        pid = int(row["product_id"])
        if pid not in offer_product_ids:
            continue  # never invent an offer for a product the ad doesn't carry
        discounts[pid] = _clamp(row["claimed_pct"], 0.0, 0.95)
    offers = {pid: discounts.get(pid, 0.0) for pid in offer_product_ids}

    return PerceivedCreative(
        creative_id=creative_id,
        brand_id=brand_id,
        claims=tuple(sorted(claims.items())),
        offers=tuple(sorted(offers.items())),
    )
