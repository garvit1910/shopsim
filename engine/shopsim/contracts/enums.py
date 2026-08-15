"""The four closed vocabularies (Law 11) + the Action enum.

ONE shared file imported by engine and minds. Vocabulary drift silently
empties every graph intersection, so membership changes are contract changes
(CONTRACT.md: 5-minute call + version bump). Integer ids follow Appendix A.

Anchor ids are fixed by the Appendix-B reference context and must never move:
Concept.ECO_FRIENDLY = 5003, Concept.DISCOUNT = 5011, Category.RUNNING_SHOES = 5504.
"""

from __future__ import annotations

import enum


class Concept(enum.IntEnum):
    """Closed claim/attribute vocabulary, ids 5000–5029 (Appendix A: 5000–5499).

    Perception maps every claim onto this enum; unknown -> OTHER (Law 11).
    """

    PERFORMANCE = 5000
    COMFORT = 5001
    DURABILITY = 5002
    ECO_FRIENDLY = 5003
    RECYCLED_MATERIALS = 5004
    LIGHTWEIGHT = 5005
    CUSHIONING = 5006
    BREATHABLE = 5007
    WATERPROOF = 5008
    VEGAN = 5009
    PREMIUM = 5010
    DISCOUNT = 5011
    VALUE_PRICED = 5012
    FREE_SHIPPING = 5013
    FAST_SHIPPING = 5014
    FREE_RETURNS = 5015
    WARRANTY = 5016
    STYLE = 5017
    INNOVATIVE = 5018
    SUSTAINABLE_PACKAGING = 5019
    LOCALLY_MADE = 5020
    HANDCRAFTED = 5021
    LIMITED_EDITION = 5022
    AWARD_WINNING = 5023
    EXPERT_ENDORSED = 5024
    WIDE_SIZES = 5025
    ARCH_SUPPORT = 5026
    GRIP = 5027
    MACHINE_WASHABLE = 5028
    OTHER = 5029


class Category(enum.IntEnum):
    """Closed category vocabulary, ids 5500–5509 (Appendix A: 5500–5999)."""

    CASUAL_SHOES = 5500
    TRAIL_SHOES = 5501
    SANDALS = 5502
    SOCKS = 5503
    RUNNING_SHOES = 5504
    APPAREL = 5505
    ACCESSORIES = 5506
    FITNESS_EQUIPMENT = 5507
    RECOVERY = 5508
    OUTDOOR_GEAR = 5509


class MotifType(str, enum.Enum):
    """Motif library v2 (Appendix E). Behavioral motifs may appear in
    DecisionContext.motifs; explanatory motifs appear only in get_trace."""

    PREFERENCE_FIT = "preference_fit"
    GOAL_FIT = "goal_fit"
    BRAND_SEMANTIC_FATIGUE = "brand_semantic_fatigue"
    EXPECTATION_VIOLATION = "expectation_violation"
    CONCEPT_SATURATION = "concept_saturation"  # P1
    SOCIAL_PROOF = "social_proof"  # P1
    EXPERIENCE_PATH = "experience_path"  # explanatory: effect routes via trust belief
    HABIT_PATH = "habit_path"  # explanatory: effect routes via habit scalars (P1)


BEHAVIORAL_MOTIFS: frozenset[MotifType] = frozenset(
    {
        MotifType.PREFERENCE_FIT,
        MotifType.GOAL_FIT,
        MotifType.BRAND_SEMANTIC_FATIGUE,
        MotifType.EXPECTATION_VIOLATION,
        MotifType.CONCEPT_SATURATION,
        MotifType.SOCIAL_PROOF,
    }
)

EXPLANATORY_MOTIFS: frozenset[MotifType] = frozenset(
    {MotifType.EXPERIENCE_PATH, MotifType.HABIT_PATH}
)

# Retired in v3 to prevent double-counting (absorbed by trust belief / habit /
# social). These names must never re-enter the enum.
RETIRED_MOTIF_NAMES: frozenset[str] = frozenset({"brand_transfer", "trust_path"})


class EventType(str, enum.Enum):
    """Event taxonomy v2: episodic edges + JSONL log-only records.

    IGNORE is derived (a SAW with no CLICK) and is an Action, never an event.
    """

    SAW = "SAW"
    CLICKED = "CLICKED"
    VISITED = "VISITED"
    BROWSED = "BROWSED"
    BOUNCED = "BOUNCED"
    CARTED = "CARTED"
    ABANDONED = "ABANDONED"
    BOUGHT = "BOUGHT"
    PRICE_SEEN = "PRICE_SEEN"
    EXPERIENCED = "EXPERIENCED"
    # Log-only records: the NEEDS lifecycle lives as edge supersessions in the
    # graph; these records exist so the JSONL log alone can replay it.
    NEED_ACTIVATED = "NEED_ACTIVATED"
    NEED_EXPIRED = "NEED_EXPIRED"
    NEED_SATISFIED = "NEED_SATISFIED"


EPISODIC_EVENTS: frozenset[EventType] = frozenset(
    {
        EventType.SAW,
        EventType.CLICKED,
        EventType.VISITED,
        EventType.BROWSED,
        EventType.BOUNCED,
        EventType.CARTED,
        EventType.ABANDONED,
        EventType.BOUGHT,
        EventType.PRICE_SEEN,
        EventType.EXPERIENCED,
    }
)

LOG_ONLY_EVENTS: frozenset[EventType] = frozenset(
    {EventType.NEED_ACTIVATED, EventType.NEED_EXPIRED, EventType.NEED_SATISFIED}
)


class Action(str, enum.Enum):
    """decide() output. Funnel: IGNORE|CLICK -> BOUNCE|BROWSE -> CART|ABANDON -> BUY|ABANDON."""

    IGNORE = "IGNORE"
    CLICK = "CLICK"
    BOUNCE = "BOUNCE"
    BROWSE = "BROWSE"
    CART = "CART"
    ABANDON = "ABANDON"
    BUY = "BUY"
