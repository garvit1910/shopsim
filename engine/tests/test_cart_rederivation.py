"""Phase 4 regression (CONTRACT v3.4-draft bug-fix): the cart scalar must
match the runner's cart state for REPEAT purchases — a BOUGHT resolves only
carts made at or before it, never a later re-cart. The old any-historical-
BOUGHT exclusion desynced mind and loop and crashed resumed-cart expansion
on the second promo cycle (exactly the promo-addiction scenario)."""

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
