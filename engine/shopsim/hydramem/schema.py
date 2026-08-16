"""Schema v3 — the six state families as edges (§0.1), plus retrieval params.

Every signal documents its representation (Law 16): paths where relationships
genuinely matter, scalars where a value is just a value. This file is the
single catalog of relationship types and their properties; cypher.py refuses
any rel/prop not listed here.

Bitemporality (decision 1): live edges carry valid_to = VALID_TO_SENTINEL;
supersede = SET old valid_to = now, CREATE new. History is never erased.

Anchor nodes: HydraDB is edge-only (no bare-node CREATE; nodes are implicit
by integer id), so edges that would otherwise hang off a single node get a
well-known destination anchor. Ids come from the 7,000–7,999 gap Appendix A
leaves unallocated (brands are 6,00x; beliefs start at 8,000,000).
"""

from __future__ import annotations

from dataclasses import dataclass

VALID_TO_SENTINEL = 9_007_199_254_740_991

# -- anchor node ids (unallocated Appendix-A gap) ---------------------------
PRICEBOOK_ID = 7_001  # PRICED_AT destination: product -> pricebook
CATALOG_ID = 7_002  # LISTS source: catalog -> creative/product/page (bare-node
#                     scans don't exist, so enumeration needs a registry edge)
ASPECT_TRUST_ID = 7_101  # Belief THAT target for trust beliefs
ASPECT_QUALITY_ID = 7_102  # Belief THAT target for quality beliefs (P1)
STORY_MARKER_ID = 7_999  # test-only: story-graph seeded_hash marker

ASPECT_IDS = {"trust": ASPECT_TRUST_ID, "quality": ASPECT_QUALITY_ID}

# -- relationship catalog: rel -> allowed edge props ------------------------

OBJECTIVE_EDGES: dict[str, tuple[str, ...]] = {
    "SOLD_BY": (),  # product -> brand
    "IN_CATEGORY": (),  # product -> category
    "HAS_ATTR": (),  # product -> concept
    "PRICED_AT": ("price", "t", "valid_to"),  # product -> PRICEBOOK anchor
    "CLAIMS": ("strength",),  # creative -> concept
    "PROMOTES": (),  # creative -> brand
    "OFFERS": ("claimed_pct",),  # creative -> product
    "SHOWS": (),  # page -> concept
    "PAGE_FOR": (),  # page -> product
    "LISTS": (),  # CATALOG anchor -> creative/product/page (enumeration registry)
}

# All episodic edges carry {t, run}; some carry one extra payload prop.
EPISODIC_EDGE_TYPES: dict[str, tuple[str, ...]] = {
    "SAW": ("t", "run"),  # shopper -> creative
    "CLICKED": ("t", "run"),  # shopper -> creative
    "VISITED": ("t", "run"),  # shopper -> page
    "BROWSED": ("t", "run"),  # shopper -> page
    "BOUNCED": ("t", "run"),  # shopper -> page
    "CARTED": ("t", "run"),  # shopper -> product
    "ABANDONED": ("t", "run"),  # shopper -> product
    "BOUGHT": ("t", "run", "price"),  # shopper -> product
    "PRICE_SEEN": ("t", "run", "price"),  # shopper -> product
    "EXPERIENCED": ("t", "run", "sat"),  # shopper -> product
}

SUBJECTIVE_EDGES: dict[str, tuple[str, ...]] = {
    # Liveness is filtered on the HOLDS edge (verified supersede pattern);
    # the belief node keeps its own valid_to for as-of-T reads.
    "HOLDS": ("t", "valid_to"),  # shopper -> belief node
    "ABOUT": (),  # belief -> brand
    "THAT": (),  # belief -> aspect anchor
    "DERIVED_FROM": ("kind", "count", "first_t", "last_t", "weight"),  # belief -> cause target
    "EXPECTS": ("about", "strength", "t", "valid_to", "cause_id"),  # shopper -> concept
    "REFERENCE_PRICE": ("price", "t", "valid_to"),  # shopper -> product
}

PREFERENCE_EDGES: dict[str, tuple[str, ...]] = {
    "PREFERS": ("w", "evidence", "source", "cause_kind", "cause_id", "t", "valid_to"),
    "HABIT": ("evidence", "t", "valid_to"),  # shopper -> brand (P1)
    # closed_cause_* are set at supersession time (satisfied-with-cause)
    "NEEDS": (
        "strength",
        "budget_cap",
        "deadline_t",
        "t",
        "valid_to",
        "source",
        "closed_cause_kind",
        "closed_cause_id",
    ),  # shopper -> category
}

SOCIAL_EDGES: dict[str, tuple[str, ...]] = {
    "TRUSTS_PERSON": ("w",),  # shopper -> shopper (P1)
}

TEST_EDGES: dict[str, tuple[str, ...]] = {
    "STORY_MARKER": ("seeded_hash",),  # STORY_MARKER anchor self-bookkeeping (test-only)
}

ALL_EDGES: dict[str, tuple[str, ...]] = {
    **OBJECTIVE_EDGES,
    **EPISODIC_EDGE_TYPES,
    **SUBJECTIVE_EDGES,
    **PREFERENCE_EDGES,
    **SOCIAL_EDGES,
    **TEST_EDGES,
}

# Node property whitelist per node family. Latent objective params
# (latent_quality, ship_reliability) are deliberately NOT listed: the single
# writer template in cypher.py is the only Cypher that may name them (Law 15).
NODE_PROPS: dict[str, tuple[str, ...]] = {
    "product": ("name", "list_price"),
    "shopper": ("segment_id", "budget"),
    "creative": ("brand_id",),
    "page": ("brand_id", "product_id"),
    "belief": ("value", "evidence", "about_id", "that_id", "t", "valid_to"),
    "marker": ("seeded_hash",),  # test-only story-graph bookkeeping
}

# Edges whose liveness is bitemporal (valid_to filter applies).
BITEMPORAL_EDGES = frozenset(
    {"PRICED_AT", "HOLDS", "EXPECTS", "REFERENCE_PRICE", "PREFERS", "HABIT", "NEEDS"}
)


# -- retrieval parameters ---------------------------------------------------


@dataclass(frozen=True)
class RetrievalParams:
    """Every hand-picked retrieval constant, in one greppable place.

    These are retrieval-layer parameters (NOT evidence.py constants): tuning
    them is calibration, not a contract change. Time is epoch seconds; one
    tick = one sim-day by default (Phase 3 owns the clock).
    """

    tick_seconds: int = 86_400
    saw_window_ticks: int = 14  # SAW lookback for adstock/fatigue/awareness
    freq_window_seconds: int = 259_200  # 72h — exposures_72h window
    adstock_half_life_s: float = 2 * 86_400.0  # exp decay of brand exposure
    recency_half_life_s: float = 3 * 86_400.0  # pref/fatigue recency weight
    fatigue_norm: float = 3.0  # full-recency same-story SAWs to saturate fatigue
    saturation_norm: float = 4.0  # cross-brand version of the same normalizer (P1)
    urgency_horizon_s: float = 7 * 86_400.0  # deadline this far out => urgency 0
    pref_min_w: float = 0.05  # preference_fit floor (hub-noise kill)
    claim_min_strength: float = 0.05  # CLAIMS strength floor
    max_path_len: int = 4  # Law: maxLen <= 4 everywhere
    budget_default: float = 200.0  # budget_left base when the node prop is unset
    social_default_experience: float = 1.0  # peer BOUGHT with no EXPERIENCED yet

    @property
    def saw_window_seconds(self) -> int:
        return self.saw_window_ticks * self.tick_seconds


DEFAULT_PARAMS = RetrievalParams()
