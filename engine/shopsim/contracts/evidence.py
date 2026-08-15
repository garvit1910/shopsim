"""Appendix F — evidence.py, the single source of behavioral learning (Law 14).

Both sides import THIS file; the update weights live nowhere else. The file's
hash rides in the run manifest (Law 13): changing anything here invalidates
replays. These constants are frozen — Phase-4 tuning touches the calibration
layer (choice weights, thresholds), never this file.

The evidence hierarchy is law: exposure NEVER updates preferences — SAW
touches awareness, adstock and EXPECTS only. Only clicking, browsing, carting,
buying and living with the product teach a shopper what they like.

One formula everywhere:
    w' = (E*w + wt*target) / (E + wt)
    E' = min(E + wt, 8)
Priors seed E0 = 2. Belief confidence = E / (E + 0.7). Contradiction moves
low-E beliefs more automatically — no extra mechanism.
"""

from __future__ import annotations

from dataclasses import dataclass

from .enums import EventType

E_CAP = 8.0
PRIOR_E0 = 2.0
CONFIDENCE_K = 0.7

# Law 14 bounds: skip writes with |dw| < EPSILON; at most
# MAX_SUBJECTIVE_WRITES_PER_TICK subjective writes per shopper per tick,
# in WRITE_PRIORITY order.
EPSILON = 0.01
MAX_SUBJECTIVE_WRITES_PER_TICK = 6
WRITE_PRIORITY = ("need_satisfy", "trust", "preferences", "expects")

REF_PRICE_ALPHA = 0.3

# Engagement preference evidence always pulls toward 1.0 ("I like what this
# stimulus claims"); direction for EXPERIENCED comes from satisfaction below.
PREF_TARGET = 1.0

EXPERIENCED_BELIEF_WEIGHT = 2.0
EXPERIENCED_PREF_MAGNITUDE = 0.75
DISCONFIRMATION_FACTOR = 0.5  # P1: overpromising ads poison trust harder
SOCIAL_REPORT_BELIEF_FACTOR = 0.5  # P1: weight = 0.5 * peer_trust
HABIT_EVIDENCE_PER_BUY = 1.0  # P1


@dataclass(frozen=True)
class EventEvidence:
    """One row of the Appendix F table. None = this event carries no evidence
    on that channel. belief_target None with a positive belief_weight means
    the weight feeds the EXPECTS channel, not a trust/quality Belief."""

    pref_weight: float
    belief_weight: float | None
    belief_target: float | None


EVIDENCE_TABLE: dict[EventType, EventEvidence] = {
    # awareness, adstock, expectations — never taste
    EventType.SAW: EventEvidence(0.0, 0.2, None),  # 0.2 = EXPECTS only
    # prefs on stimulus-claimed concepts, target = PREF_TARGET
    EventType.CLICKED: EventEvidence(0.10, 0.2, None),  # 0.2 = EXPECTS reinforcement
    EventType.BROWSED: EventEvidence(0.25, 0.75, 0.6),
    EventType.VISITED: EventEvidence(0.25, 0.75, 0.6),
    EventType.CARTED: EventEvidence(0.50, None, None),
    # also: satisfy matching NEEDS; habit +1 (P1)
    EventType.BOUGHT: EventEvidence(1.00, 1.5, 0.65),
    # EXPERIENCED is satisfaction-dependent: use experienced_*_evidence() below.
}

# IGNORE is derived and carries no evidence at P0 (ambiguous without an
# attention model — P2). It is an Action, so it has no EVIDENCE_TABLE row.


def blend(w: float, e: float, target: float, weight: float) -> tuple[float, float]:
    """The one formula. Returns (w', E'). weight <= 0 is a no-op."""
    if weight <= 0:
        return w, e
    w_new = (e * w + weight * target) / (e + weight)
    e_new = min(e + weight, E_CAP)
    return w_new, e_new


def confidence(e: float) -> float:
    return e / (e + CONFIDENCE_K)


def experienced_pref_evidence(sat: float) -> tuple[float, float]:
    """Preference evidence from living with the product: +-0.75*(2*sat-1),
    encoded as (magnitude, direction target) for the blend (CONTRACT.md).
    Applies ONLY to concepts the product actually HAS_ATTR — ads teach
    expectations, experience teaches truth."""
    return EXPERIENCED_PREF_MAGNITUDE * abs(2 * sat - 1), (1.0 if sat >= 0.5 else 0.0)


def experienced_belief_evidence(
    sat: float, expectation: float | None = None
) -> tuple[float, float]:
    """Trust evidence from a delivery: weight 2.0, target = satisfaction.
    P1 disconfirmation multiplier: x(1 + 0.5*max(0, expectation - sat))."""
    weight = EXPERIENCED_BELIEF_WEIGHT
    if expectation is not None:
        weight *= 1 + DISCONFIRMATION_FACTOR * max(0.0, expectation - sat)
    return weight, sat


def smooth_reference_price(old: float, seen: float) -> float:
    """PRICE_SEEN -> reference-price exponential smoothing, alpha = 0.3."""
    return (1 - REF_PRICE_ALPHA) * old + REF_PRICE_ALPHA * seen


def habit_strength(e: float) -> float:
    """HABIT strength = E / (E + 2) (P1)."""
    return e / (e + 2.0)
