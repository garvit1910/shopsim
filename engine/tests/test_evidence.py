"""Appendix F asserted to the digit — the golden chain IS the demo claim."""

import pytest

from shopsim.contracts.enums import EventType
from shopsim.contracts.evidence import (
    E_CAP,
    EVIDENCE_TABLE,
    PREF_TARGET,
    PRIOR_E0,
    blend,
    confidence,
    experienced_belief_evidence,
    experienced_pref_evidence,
    smooth_reference_price,
)


def test_golden_chain_digit_exact():
    """eco prior 0.45 (E=2) -> CLICK 0.476 -> BROWSE 0.532 -> CART 0.614
    -> BUY 0.714 -> positive experience 0.761 (E=4.6, confidence 0.87)."""
    w, e = 0.45, PRIOR_E0
    for event, expected in [
        (EventType.CLICKED, 0.476),
        (EventType.BROWSED, 0.532),
        (EventType.CARTED, 0.614),
        (EventType.BOUGHT, 0.714),
    ]:
        w, e = blend(w, e, PREF_TARGET, EVIDENCE_TABLE[event].pref_weight)
        assert round(w, 3) == expected, f"after {event}: {w}"
    weight, target = experienced_pref_evidence(sat=1.0)
    w, e = blend(w, e, target, weight)
    assert round(w, 3) == 0.761
    assert e == pytest.approx(4.6)
    assert round(confidence(e), 2) == 0.87


def test_trust_from_two_visits_and_a_purchase():
    """'value …, confidence 0.81 — from 2 visits and 1 purchase': E = 3.0."""
    visit = EVIDENCE_TABLE[EventType.VISITED]
    buy = EVIDENCE_TABLE[EventType.BOUGHT]
    # a belief is born at its first evidence: (w, E) = (target, weight)
    w, e = visit.belief_target, visit.belief_weight
    w, e = blend(w, e, visit.belief_target, visit.belief_weight)
    w, e = blend(w, e, buy.belief_target, buy.belief_weight)
    assert e == pytest.approx(3.0)
    assert round(confidence(e), 2) == 0.81


def test_evidence_cap():
    _, e = blend(0.5, 7.8, 1.0, 0.5)
    assert e == E_CAP
    w, e = blend(0.5, e, 1.0, 1.0)
    assert e == E_CAP  # stays capped
    assert 0.5 < w < 1.0  # value still moves


def test_saw_never_touches_preferences():
    saw = EVIDENCE_TABLE[EventType.SAW]
    assert saw.pref_weight == 0.0
    assert saw.belief_weight == 0.2  # EXPECTS only
    assert saw.belief_target is None
    w, e = blend(0.45, PRIOR_E0, PREF_TARGET, saw.pref_weight)
    assert (w, e) == (0.45, PRIOR_E0)  # weight 0 is a no-op


def test_hierarchy_strictly_ordered():
    """F8 unit-level: equal counts of CLICK/BROWSE/CART/BUY -> strictly ordered dw."""
    deltas = []
    for event in (EventType.CLICKED, EventType.BROWSED, EventType.CARTED, EventType.BOUGHT):
        w, _ = blend(0.45, PRIOR_E0, PREF_TARGET, EVIDENCE_TABLE[event].pref_weight)
        deltas.append(w - 0.45)
    assert all(a < b for a, b in zip(deltas, deltas[1:]))


def test_confidence_differential_updating():
    """F10 unit-level: identical contradictory evidence moves a low-E belief more."""
    low, _ = blend(0.7, 1.0, 0.2, 1.0)
    high, _ = blend(0.7, 6.0, 0.2, 1.0)
    assert (0.7 - low) > (0.7 - high) > 0


def test_experienced_pref_direction():
    # sat=1 reproduces the golden chain's final step
    assert experienced_pref_evidence(1.0) == (0.75, 1.0)
    # bad experience: same |2*sat-1| magnitude, pulls toward 0
    weight, target = experienced_pref_evidence(0.2)
    assert weight == pytest.approx(0.45)
    assert target == 0.0


def test_experienced_belief_and_disconfirmation():
    assert experienced_belief_evidence(0.9) == (2.0, 0.9)
    # P1: overpromising (expectation 0.9, sat 0.3) inflates the weight x1.3
    weight, target = experienced_belief_evidence(0.3, expectation=0.9)
    assert weight == pytest.approx(2.0 * 1.3)
    assert target == 0.3
    # meeting expectations adds nothing
    assert experienced_belief_evidence(0.9, expectation=0.5)[0] == 2.0


def test_reference_price_smoothing():
    assert smooth_reference_price(40.0, 30.0) == pytest.approx(37.0)  # alpha = 0.3


def test_confidence_formula_anchors():
    assert round(confidence(3.0), 2) == 0.81  # Appendix B trust belief
    assert round(confidence(0.75), 2) == 0.52  # one visit (low-conf fixture)
    assert round(confidence(6.0), 2) == 0.90  # high-conf fixture
