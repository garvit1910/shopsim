"""Phase 3: ScriptedMind v2 — kind-aware two-phase funnel behavior."""

from pathlib import Path

from shopsim.contracts.enums import Action
from shopsim.contracts.types import ActiveNeed, ChoiceCoeffs, Scalars
from shopsim.minds.objective_view import ObjectiveView
from shopsim.minds.scripted import ScriptedMind

REPO = Path(__file__).resolve().parents[2]
VIEW = ObjectiveView.from_catalog(REPO / "fixtures" / "demo-brand")
COEFFS = ChoiceCoeffs(impulsivity=1.0, price_sensitivity=0.5, budget=200.0,
                      stage_bases=(("CLICK", 0.0),))

NEED = ActiveNeed(category=5504, strength=0.8, urgency=0.7, budget_cap=90.0)


def scalars(*, need=None, aware=False, adstock=0.0, ref=None, gap=0.0,
            budget_left=200.0, cart=()):
    return Scalars(
        shopper_id=1_000_007, aware_of_brand=aware, adstock=adstock,
        exposures_72h=0, last_seen_t=None, reference_price=ref or {},
        current_price_gap=gap, budget_left=budget_left, cart=tuple(cart),
        trust_belief=None, quality_belief=None, active_need=need, habit=None)


def decide(kind_stim, s):
    mind = ScriptedMind(VIEW).for_stimulus(kind_stim)
    return mind.decide(None, s, COEFFS, None)


AD, PAGE = 2_000_003, 4_000_001


def test_creative_click_when_need_live():
    assert decide(AD, scalars(need=NEED)) is Action.CLICK


def test_creative_adstock_rule_without_need():
    assert decide(AD, scalars(aware=True, adstock=0.7)) is Action.CLICK
    assert decide(AD, scalars(aware=True, adstock=0.5)) is Action.IGNORE
    assert decide(AD, scalars(aware=False, adstock=0.9)) is Action.IGNORE


def test_creative_never_buys():
    s = scalars(need=NEED, ref={3_000_001: 39.0})
    assert decide(AD, s) in (Action.IGNORE, Action.CLICK)


def test_page_buys_only_within_cap_and_budget():
    affordable = scalars(need=NEED, ref={3_000_001: 39.0}, gap=-0.15)
    assert decide(PAGE, affordable) is Action.BUY
    over_cap = scalars(need=ActiveNeed(5504, 0.8, 0.7, budget_cap=20.0),
                       ref={3_000_001: 39.0})
    assert decide(PAGE, over_cap) is Action.BROWSE
    broke = scalars(need=NEED, ref={3_000_001: 39.0}, budget_left=10.0)
    assert decide(PAGE, broke) is Action.BROWSE


def test_page_needs_reference_price_to_buy():
    # sanctioned price derivation (v3.2 item 3): no reference price, no guard, no BUY
    assert decide(PAGE, scalars(need=NEED)) is Action.BROWSE


def test_resumed_cart_abandons_on_failed_buy():
    s = scalars(cart=[3_000_001], ref={3_000_001: 39.0})  # no need -> BUY fails
    assert decide(PAGE, s) is Action.ABANDON


def test_unbound_mind_defaults_to_creative():
    assert ScriptedMind().decide(None, scalars(need=NEED), COEFFS, None) is Action.CLICK
