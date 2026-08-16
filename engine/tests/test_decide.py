"""Phase 2.4 — decide(): determinism, funnel walk, guards, goal gating (F9 shape)."""

import inspect

import numpy as np
import pytest

from shopsim.contracts.enums import Action
from shopsim.contracts.types import AppraisalTraits, Appraisal, ChoiceCoeffs, DecisionContext
from shopsim.minds import choice
from shopsim.minds.appraisal import appraise
from shopsim.minds.calibration import DEFAULT_CHOICE_PARAMS, DEFAULT_STAGE_BASES
from shopsim.minds.choice import _buy_probability, _gate_probability, decide
from shopsim.minds.objective_view import StimulusFacts

NEUTRAL = AppraisalTraits(novelty_seeking=0.5, trust_orientation=0.5, deal_proneness=0.5)

STIM = StimulusFacts(
    stimulus_id=2000003, kind="creative", brand_id=6001,
    claims={5003: 0.9, 5005: 0.6, 5011: 0.8},
    offers={3000001: 0.15}, products={3000001: 5504})

COEFFS = ChoiceCoeffs(impulsivity=1.0, price_sensitivity=0.6, budget=120.0,
                      stage_bases=DEFAULT_STAGE_BASES)


def _scalars(**overrides):
    base = {
        "shopper_id": 1000041, "aware_of_brand": True, "adstock": 0.5,
        "exposures_72h": 1, "last_seen_t": 1755150000,
        "reference_price": {"3000001": 39.0}, "current_price_gap": -0.15,
        "budget_left": 120.0, "cart": [], "trust_belief": None,
        "quality_belief": None, "active_need": None, "habit": None,
    }
    base.update(overrides)
    motifs = []
    if base["active_need"] is not None:  # C1 biconditional: need ⇔ goal_fit
        need = base["active_need"]
        motifs.append({"type": "goal_fit", "strength": need["strength"],
                       "urgency": need["urgency"],
                       "path": [1000041, "NEEDS", need["category"], "IN_CATEGORY",
                                3000001, "OFFERS", 2000003]})
    return DecisionContext.from_dict({"scalars": base, "motifs": motifs}).scalars


APPRAISAL = Appraisal(relevance=0.4, credibility=0.5, brand_message_fatigue=0.1,
                      offer_attractiveness=0.3, expectation_alignment=1.0)


class FakeRng:
    """Deterministic uniform feed to steer the funnel walk."""

    def __init__(self, values):
        self.values = list(values)

    def random(self):
        return self.values.pop(0)


def test_same_seed_identical_action_sequence():
    def run():
        rng = np.random.default_rng(1234)
        out = []
        for i in range(300):
            s = _scalars(adstock=0.2 + (i % 7) * 0.1)
            out.append(decide(APPRAISAL, s, COEFFS, rng, kind="creative"))
            out.append(decide(APPRAISAL, s, COEFFS, rng, kind="page"))
        return out
    assert run() == run()


def test_funnel_walk_actions():
    s = _scalars()
    # low draws pass every gate → BUY
    assert decide(APPRAISAL, s, COEFFS, FakeRng([0.0, 0.0, 0.0]), kind="page") is Action.BUY
    # fail the first gate → BOUNCE
    assert decide(APPRAISAL, s, COEFFS, FakeRng([1.0]), kind="page") is Action.BOUNCE
    # pass browse, fail cart gate → deepest reached is BROWSE
    assert decide(APPRAISAL, s, COEFFS, FakeRng([0.0, 1.0]), kind="page") is Action.BROWSE
    # pass browse+cart, fail buy → cart persists
    assert decide(APPRAISAL, s, COEFFS, FakeRng([0.0, 0.0, 1.0]), kind="page") is Action.CART
    # resumed cart (product already carted) fails buy → ABANDON, one draw only
    carted = _scalars(cart=[3000001])
    assert decide(APPRAISAL, carted, COEFFS, FakeRng([1.0]), kind="page") is Action.ABANDON
    assert decide(APPRAISAL, carted, COEFFS, FakeRng([0.0]), kind="page") is Action.BUY
    # creative kind: single gate
    assert decide(APPRAISAL, s, COEFFS, FakeRng([1.0]), kind="creative") is Action.IGNORE


def test_budget_hard_block():
    s = _scalars(reference_price={"3000001": 100.0}, current_price_gap=0.0,
                 budget_left=50.0)
    assert _buy_probability(APPRAISAL, s, COEFFS, DEFAULT_CHOICE_PARAMS) == 0.0
    # rng draw still consumed: streams stay aligned across the guard
    assert decide(APPRAISAL, s, COEFFS, FakeRng([0.0, 0.0, 0.0]), kind="page") is Action.CART


def test_budget_cap_damps_buy():
    need = {"category": 5504, "strength": 0.8, "urgency": 0.7, "budget_cap": 90.0}
    within = _scalars(active_need=need)
    over = _scalars(reference_price={"3000001": 100.0}, current_price_gap=0.0,
                    active_need=need)
    # need the goal_fit motif for a valid context; bypass via direct scalars
    p_within = _buy_probability(APPRAISAL, within, COEFFS, DEFAULT_CHOICE_PARAMS)
    p_over = _buy_probability(APPRAISAL, over, COEFFS, DEFAULT_CHOICE_PARAMS)
    base_over = _gate_probability("BUY", APPRAISAL, over, COEFFS, DEFAULT_CHOICE_PARAMS)
    assert p_over == pytest.approx(base_over * 0.25)
    assert p_within > p_over


def test_no_reference_price_skips_guards():
    s = _scalars(reference_price={}, budget_left=0.0)
    assert _buy_probability(APPRAISAL, s, COEFFS, DEFAULT_CHOICE_PARAMS) > 0.0


def test_price_term_rewards_deals_and_doubles_losses():
    deal = _scalars(current_price_gap=-0.2)
    loss = _scalars(current_price_gap=0.2)
    flat = _scalars(current_price_gap=0.0)
    p = DEFAULT_CHOICE_PARAMS
    up = _gate_probability("BROWSE", APPRAISAL, deal, COEFFS, p)
    mid = _gate_probability("BROWSE", APPRAISAL, flat, COEFFS, p)
    down = _gate_probability("BROWSE", APPRAISAL, loss, COEFFS, p)
    assert up > mid > down
    # CLICK gate is pre-price (row 13 is post-click only)
    assert _gate_probability("CLICK", APPRAISAL, deal, COEFFS, p) == \
        _gate_probability("CLICK", APPRAISAL, flat, COEFFS, p)


def test_wearout_lowers_probability():
    fresh = _scalars(exposures_72h=1)
    worn = _scalars(exposures_72h=8)
    p = DEFAULT_CHOICE_PARAMS
    assert _gate_probability("CLICK", APPRAISAL, fresh, COEFFS, p) > \
        _gate_probability("CLICK", APPRAISAL, worn, COEFFS, p)


def test_goal_twin_f9_shape(mock):
    """Need-on vs need-off, same ad: some CTR gap, a LARGER gap at BUY —
    goal gating emerges from stage-conditional relevance weights alone."""
    off_ctx: DecisionContext = mock.by_name("twin-need-off")
    on_ctx: DecisionContext = mock.by_name("twin-need-on")
    a_off = appraise(off_ctx, NEUTRAL, STIM)
    a_on = appraise(on_ctx, NEUTRAL, STIM)
    p = DEFAULT_CHOICE_PARAMS

    def through(a, s):
        """P(buy | exposure) = click gate × page walk — the F9 quantity."""
        return (_gate_probability("CLICK", a, s, COEFFS, p)
                * _gate_probability("BROWSE", a, s, COEFFS, p)
                * _gate_probability("CART", a, s, COEFFS, p)
                * _buy_probability(a, s, COEFFS, p))

    ctr_ratio = (_gate_probability("CLICK", a_on, on_ctx.scalars, COEFFS, p)
                 / _gate_probability("CLICK", a_off, off_ctx.scalars, COEFFS, p))
    buy_ratio = through(a_on, on_ctx.scalars) / through(a_off, off_ctx.scalars)
    assert ctr_ratio > 1.0
    assert buy_ratio > ctr_ratio, "goal must gate the deep funnel harder than CTR"


def test_relevance_weighs_more_deep_in_funnel():
    w = DEFAULT_CHOICE_PARAMS
    assert w.weights("BUY")["relevance"] > w.weights("CART")["relevance"] \
        > w.weights("CLICK")["relevance"]


def test_decide_signature_has_no_traits_param():
    params = inspect.signature(decide).parameters
    assert "traits" not in params
    assert all("Traits" not in str(p.annotation) for p in params.values())
    assert "AppraisalTraits" not in inspect.getsource(choice)
