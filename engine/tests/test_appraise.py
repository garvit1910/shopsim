"""Phase 2.3 — formula appraise(): monotonicity, abstention, single entry.

Motif-level monotonicity checkpoints (PLAN Phase 2): +preference_fit
↑relevance · +goal_fit ↑relevance · +brand_semantic_fatigue ↑fatigue dim ·
+violation ↓expectation_alignment · unaware + no paths + no belief ⇒
engagement ≈ 0 (F2).
"""

import pytest

from shopsim.contracts.types import AppraisalTraits, DecisionContext
from shopsim.minds.appraisal import appraise
from shopsim.minds.objective_view import StimulusFacts

NEUTRAL = AppraisalTraits(novelty_seeking=0.5, trust_orientation=0.5, deal_proneness=0.5)

STIM = StimulusFacts(
    stimulus_id=2000003, kind="creative", brand_id=6001,
    claims={5003: 0.9, 5005: 0.6, 5011: 0.8},
    offers={3000001: 0.15}, products={3000001: 5504})


def _ctx(motifs=None, **scalar_overrides) -> DecisionContext:
    scalars = {
        "shopper_id": 1000041, "aware_of_brand": True, "adstock": 0.5,
        "exposures_72h": 1, "last_seen_t": 1755150000,
        "reference_price": {"3000001": 39.0}, "current_price_gap": -0.15,
        "budget_left": 120.0, "cart": [], "trust_belief": None,
        "quality_belief": None, "active_need": None, "habit": None,
    }
    scalars.update(scalar_overrides)
    return DecisionContext.from_dict({"scalars": scalars, "motifs": motifs or []})


def _pref_motif(strength, recency=1.0):
    return {"type": "preference_fit", "strength": strength, "evidence": 2.0,
            "recency": recency, "path": [1000041, "PREFERS", 5003, "CLAIMS", 2000003]}


def _goal(strength, urgency):
    need = {"category": 5504, "strength": strength, "urgency": urgency, "budget_cap": 90.0}
    motif = {"type": "goal_fit", "strength": strength, "urgency": urgency,
             "path": [1000041, "NEEDS", 5504, "IN_CATEGORY", 3000001, "OFFERS", 2000003]}
    return need, motif


def _belief(value, e):
    return {"value": value, "evidence": e, "confidence": e / (e + 0.7)}


def test_preference_fit_raises_relevance():
    low = appraise(_ctx([_pref_motif(0.3)]), NEUTRAL, STIM)
    high = appraise(_ctx([_pref_motif(0.7)]), NEUTRAL, STIM)
    assert high.relevance > low.relevance > 0


def test_goal_fit_raises_relevance():
    need, motif = _goal(0.8, 0.7)
    off = appraise(_ctx([_pref_motif(0.61)]), NEUTRAL, STIM)
    on = appraise(_ctx([_pref_motif(0.61), motif], active_need=need), NEUTRAL, STIM)
    assert on.relevance > off.relevance
    weak_need, weak_motif = _goal(0.8, 0.2)
    weak = appraise(_ctx([_pref_motif(0.61), weak_motif], active_need=weak_need), NEUTRAL, STIM)
    assert on.relevance > weak.relevance  # urgency matters


def test_fatigue_motif_raises_fatigue_dim():
    def fat(strength):
        return {"type": "brand_semantic_fatigue", "strength": strength, "recency": 0.7,
                "brand": 6001, "path": [1000041, "SAW", 2000001, "CLAIMS", 5003,
                                        "CLAIMS", 2000003]}
    low = appraise(_ctx([fat(0.2)]), NEUTRAL, STIM)
    high = appraise(_ctx([fat(0.8)]), NEUTRAL, STIM)
    none = appraise(_ctx(), NEUTRAL, STIM)
    assert high.brand_message_fatigue > low.brand_message_fatigue > none.brand_message_fatigue == 0.0


def test_violation_lowers_alignment():
    def viol(strength):
        return {"type": "expectation_violation", "strength": strength,
                "path": [1000041, "EXPECTS", 5011, "NOT_SHOWN_BY", 4000002]}
    clean = appraise(_ctx(), NEUTRAL, STIM)
    mild = appraise(_ctx([viol(0.3)]), NEUTRAL, STIM)
    severe = appraise(_ctx([viol(0.9)]), NEUTRAL, STIM)
    assert clean.expectation_alignment == 1.0
    assert clean.expectation_alignment > mild.expectation_alignment > severe.expectation_alignment


def test_credibility_confidence_and_orientation():
    low = appraise(_ctx(trust_belief=_belief(0.6, 0.75)), NEUTRAL, STIM)
    high = appraise(_ctx(trust_belief=_belief(0.6, 6.0)), NEUTRAL, STIM)
    # same positive value: more evidence mass ⇒ more credible
    assert high.credibility > low.credibility > 0.5
    bad = appraise(_ctx(trust_belief=_belief(0.2, 6.0)), NEUTRAL, STIM)
    assert bad.credibility < 0.5
    # trust_orientation tilts an uncertain belief more than a confident one
    trusting = AppraisalTraits(0.5, 0.9, 0.5)
    d_low = appraise(_ctx(trust_belief=_belief(0.6, 0.75)), trusting, STIM).credibility - low.credibility
    d_high = appraise(_ctx(trust_belief=_belief(0.6, 6.0)), trusting, STIM).credibility - high.credibility
    assert d_low > d_high >= 0


def test_no_belief_floors_neutral_low():
    a = appraise(_ctx(), NEUTRAL, STIM)
    assert a.credibility == pytest.approx(0.2)  # anchored abstention floor


def test_offer_is_perceived_deal_times_proneness():
    keen = AppraisalTraits(0.5, 0.5, 0.8)
    meh = AppraisalTraits(0.5, 0.5, 0.2)
    assert appraise(_ctx(), keen, STIM).offer_attractiveness > \
        appraise(_ctx(), meh, STIM).offer_attractiveness > 0
    no_stim = appraise(_ctx(), keen, None)
    assert no_stim.offer_attractiveness == 0.0


def test_f2_cold_gate_engagement_near_zero():
    cold = appraise(_ctx(aware_of_brand=False, adstock=0.0, exposures_72h=0,
                         last_seen_t=None), NEUTRAL, STIM)
    assert cold.relevance == 0.0
    assert cold.credibility <= 0.11
    assert cold.offer_attractiveness <= 0.2 * 0.5 * 0.8  # scaled well down
    # awareness alone lifts the gate
    warm = appraise(_ctx(aware_of_brand=True), NEUTRAL, STIM)
    assert warm.credibility > cold.credibility


def test_all_dims_bounded_on_every_fixture(mock):
    grid = [AppraisalTraits(a, b, c)
            for a in (0.0, 1.0) for b in (0.0, 1.0) for c in (0.0, 1.0)]
    for name in mock.cases:
        ctx = mock.by_name(name)
        for traits in grid:
            a = appraise(ctx, traits, STIM)
            for dim in ("relevance", "credibility", "brand_message_fatigue",
                        "offer_attractiveness", "expectation_alignment"):
                assert 0.0 <= getattr(a, dim) <= 1.0, (name, dim)
            assert a.novelty is None and a.social_proof is None  # P1 untouched


def test_twin_fixtures_goal_gap(mock):
    """The Maya twin at the appraisal level: need-on strictly more relevant."""
    off = appraise(mock.by_name("twin-need-off"), NEUTRAL, STIM)
    on = appraise(mock.by_name("twin-need-on"), NEUTRAL, STIM)
    assert on.relevance > off.relevance
    assert on.credibility == off.credibility  # goal enters relevance only
