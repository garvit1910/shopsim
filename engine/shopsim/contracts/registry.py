"""ENTRY_POINTS registry (Law 12) — every behavioral variable enters the
pipeline at exactly one documented point. Mirrors the table in CONTRACT.md.

`consumes` entries are namespaced:
    trait:<AppraisalTraits field>   coeff:<ChoiceCoeffs field>
    scalar:<Scalars field>          motif:<behavioral MotifType value>
    stimulus:<objective-graph property>   seed:<population-factory input>

Completeness rules (tested in tests/test_registry.py):
  * every trait field in exactly one row, all appraise-stage;
  * every coeff field in exactly one row, all decide-stage;
  * every scalar field in exactly one row (shopper_id exempt as identity;
    trust_belief sanctioned twice — credibility + P1 risk term);
  * every behavioral motif in exactly one row; explanatory motifs in none.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EntryPoint:
    row: int
    consumes: tuple[str, ...]
    entry_point: str
    stage: str  # "seeding" | "appraise" | "decide" | "engine"
    priority: str  # "P0" | "P1"


ENTRY_POINTS: tuple[EntryPoint, ...] = (
    EntryPoint(1, ("seed:preference_priors",),
               "seeded PREFERS edges (population factory, E0=2)", "seeding", "P0"),
    EntryPoint(2, ("motif:preference_fit",),
               "appraisal: relevance", "appraise", "P0"),
    EntryPoint(3, ("motif:goal_fit",),
               "appraisal: relevance (strength x urgency)", "appraise", "P0"),
    EntryPoint(4, ("scalar:active_need",),
               "decide: BUY damp x0.25 guard (budget_cap)", "decide", "P0"),
    EntryPoint(5, ("scalar:trust_belief",),
               "appraisal: credibility (value x f(confidence, trust_orientation))", "appraise", "P0"),
    EntryPoint(6, ("trait:trust_orientation",),
               "appraisal: credibility", "appraise", "P0"),
    EntryPoint(7, ("scalar:aware_of_brand",),
               "appraisal: F2 abstention gate", "appraise", "P0"),
    EntryPoint(8, ("motif:brand_semantic_fatigue",),
               "appraisal: brand_message_fatigue", "appraise", "P0"),
    EntryPoint(9, ("stimulus:claimed_pct", "trait:deal_proneness"),
               "appraisal: offer_attractiveness (perceived deal)", "appraise", "P0"),
    EntryPoint(10, ("motif:expectation_violation",),
               "appraisal: expectation_alignment (1 - strength)", "appraise", "P0"),
    EntryPoint(11, ("scalar:adstock",),
               "decide: utility +gamma*adstock", "decide", "P0"),
    EntryPoint(12, ("scalar:exposures_72h", "scalar:last_seen_t"),
               "decide: utility -delta*asset_wearout (single asset-repetition entry w/ row 11)",
               "decide", "P0"),
    EntryPoint(13, ("scalar:current_price_gap", "coeff:price_sensitivity"),
               "decide: utility, realized price (losses x2)", "decide", "P0"),
    EntryPoint(14, ("scalar:reference_price",),
               "engine: input to current_price_gap; UI display", "engine", "P0"),
    EntryPoint(15, ("coeff:impulsivity",),
               "decide: sigma temperature tau", "decide", "P0"),
    EntryPoint(16, ("coeff:budget", "scalar:budget_left"),
               "decide: hard guard, price > budget_left blocks BUY", "decide", "P0"),
    EntryPoint(17, ("coeff:stage_bases",),
               "decide: theta_s per funnel stage", "decide", "P0"),
    EntryPoint(18, ("scalar:cart",),
               "decide: funnel stage state", "decide", "P0"),
    EntryPoint(19, ("motif:concept_saturation", "trait:novelty_seeking"),
               "appraisal: novelty (deliberately NOT adstock-driven)", "appraise", "P1"),
    EntryPoint(20, ("motif:social_proof",),
               "appraisal: social_proof", "appraise", "P1"),
    EntryPoint(21, ("scalar:habit", "coeff:switching_inertia"),
               "decide: utility CART/BUY, x(H_stim - H_rival_max)", "decide", "P1"),
    EntryPoint(22, ("coeff:risk_aversion", "scalar:trust_belief"),
               "decide: utility BUY, -risk_aversion*(1 - trust confidence)", "decide", "P1"),
    EntryPoint(23, ("scalar:quality_belief",),
               "appraisal: quality/credibility dims", "appraise", "P1"),
)

# Identity/bookkeeping fields that are not behavioral variables.
EXEMPT_SCALARS: frozenset[str] = frozenset({"shopper_id"})

# The only sanctioned dual read: value+confidence feed credibility (row 5);
# confidence alone also feeds the P1 BUY risk term (row 22). Documented in
# CONTRACT.md; anything else appearing twice is a double-count regression.
SANCTIONED_DUAL_READS: dict[str, int] = {"scalar:trust_belief": 2}


def consumed(prefix: str) -> list[str]:
    """All consumed names with the given namespace prefix, one per occurrence."""
    return [
        name.split(":", 1)[1]
        for row in ENTRY_POINTS
        for name in row.consumes
        if name.startswith(prefix + ":")
    ]
