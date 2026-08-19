"""Phase 4 regression (CONTRACT v3.4-draft bug-fix): the cart scalar must
match the runner's cart state for REPEAT purchases — a BOUGHT resolves only
carts made at or before it, never a later re-cart. The old any-historical-
BOUGHT exclusion desynced mind and loop and crashed resumed-cart expansion
on the second promo cycle (exactly the promo-addiction scenario)."""

import pytest
from types import SimpleNamespace

from shopsim.hydramem.reads import StimulusView, assemble_context
from shopsim.hydramem.schema import RetrievalParams

T0 = 1_759_000_000
SID = 1_000_000


def build_cart(carted, bought, abandoned):
    stim = StimulusView(
        stimulus_id=4000001, kind="page", brand_id=6001,
        shows=frozenset({5003}), products={3000001: 5504},
        prices={3000001: 39.0})
    cache = SimpleNamespace(creatives={}, pages={}, promotes={})
    rows = {
        "saw": (), "prefers": (), "needs": (), "holds": (), "expects": (),
        "ref_price": ({"dst": 3000001, "price": 39.0},), "habit": (),
        "bought": tuple({"dst": p, "t": t, "price": pr} for p, t, pr in bought),
        "carted": tuple({"dst": p, "t": t} for p, t in carted),
        "abandoned": tuple({"dst": p, "t": t} for p, t in abandoned),
        "props": [{"budget": 500.0}], "trusts": (), "visited": (),
    }
    ctx = assemble_context(SID, rows, stim, cache, {}, T0 + 10, T0,
                           RetrievalParams())
    return ctx["scalars"]["cart"]


def test_recart_after_purchase_is_live():
    # cart @t1 -> bought @t2 -> re-cart @t3: the re-cart is LIVE
    assert build_cart(
        carted=[(3000001, T0 + 1), (3000001, T0 + 3)],
        bought=[(3000001, T0 + 2, 33.15)],
        abandoned=[]) == [3000001]


def test_purchase_resolves_earlier_cart():
    assert build_cart(
        carted=[(3000001, T0 + 1)],
        bought=[(3000001, T0 + 2, 33.15)],
        abandoned=[]) == []


def test_second_purchase_resolves_recart():
    assert build_cart(
        carted=[(3000001, T0 + 1), (3000001, T0 + 3)],
        bought=[(3000001, T0 + 2, 33.15), (3000001, T0 + 4, 31.2)],
        abandoned=[]) == []


def test_abandon_still_resolves_and_recart_revives():
    assert build_cart(
        carted=[(3000001, T0 + 1)],
        bought=[],
        abandoned=[(3000001, T0 + 2)]) == []
    assert build_cart(
        carted=[(3000001, T0 + 1), (3000001, T0 + 3)],
        bought=[],
        abandoned=[(3000001, T0 + 2)]) == [3000001]


# -- the resumed flag follows the MIND's view, not the runner's memory -------


def test_expand_page_resumed_flag_matches_decide_in_cart():
    """The runner's `resumed` and the mind's `in_cart` must be the SAME
    predicate, or a shopper whose REFERENCE_PRICE was evicted by the Law-14
    per-tick write cap holds a cart the graph cannot show: decide() sees no
    cart and returns BROWSE, while expand_page still demands BUY|ABANDON and
    kills the run. Both sides now read `cart ∩ reference_price`.
    """
    from shopsim.contracts.enums import Action
    from shopsim.contracts.types import Scalars
    from shopsim.runner.expansion import expand_page

    def in_cart(s: Scalars) -> bool:
        return bool(set(s.cart) & set(s.reference_price))

    def scalars(cart, ref):
        return Scalars(
            shopper_id=3500049, aware_of_brand=True, adstock=0.0, exposures_72h=1,
            last_seen_t=None, reference_price=ref, current_price_gap=0.0,
            budget_left=200.0, cart=cart, trust_belief=None, quality_belief=None,
            active_need=None, habit=None)

    # the evicted-price case: a real cart the mind cannot see
    blind = scalars((3000004,), {})
    assert in_cart(blind) is False
    # BROWSE must expand cleanly under the flag the mind's view implies
    evs = expand_page(Action.BROWSE, 3500049, 4000004, 3000004, 42.0,
                      2000004, in_cart(blind), t=1791172800, run=25)
    assert [e.type.value for e in evs] == ["VISITED", "PRICE_SEEN", "BROWSED"]

    # the visible case: mind sees the cart, so only BUY|ABANDON are legal
    seen = scalars((3000004,), {3000004: 42.0})
    assert in_cart(seen) is True
    bought = expand_page(Action.BUY, 3500049, 4000004, 3000004, 42.0,
                         2000004, in_cart(seen), t=1791172800, run=25)
    assert [e.type.value for e in bought] == ["VISITED", "PRICE_SEEN", "BOUGHT"]
    with pytest.raises(ValueError, match="BUY|ABANDON only"):
        expand_page(Action.BROWSE, 3500049, 4000004, 3000004, 42.0,
                    2000004, in_cart(seen), t=1791172800, run=25)
