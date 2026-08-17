"""Phase 3: the Action -> episodic-event expansion table (CONTRACT v3.3)."""

import pytest

from shopsim.contracts.enums import Action, EventType
from shopsim.runner.expansion import expand_creative, expand_page

SID, T, RUN = 1_000_007, 1_755_000_000, 0
PAGE, PRODUCT, CREATIVE, PRICE = 4_000_001, 3_000_001, 2_000_003, 33.15


def types(events):
    return [e.type for e in events]


def test_creative_expansion():
    assert types(expand_creative(Action.IGNORE, SID, CREATIVE, T, RUN)) == [EventType.SAW]
    evs = expand_creative(Action.CLICK, SID, CREATIVE, T, RUN)
    assert types(evs) == [EventType.SAW, EventType.CLICKED]
    assert all(e.subject == CREATIVE and e.t == T and e.run == RUN for e in evs)
    with pytest.raises(ValueError):
        expand_creative(Action.BUY, SID, CREATIVE, T, RUN)


def page(action, resumed=False):
    return expand_page(action, SID, PAGE, PRODUCT, PRICE, CREATIVE, resumed, T, RUN)


def test_bounce_teaches_nothing():
    evs = page(Action.BOUNCE)
    assert types(evs) == [EventType.BOUNCED]  # no VISITED, no PRICE_SEEN
    with pytest.raises(ValueError):
        page(Action.BOUNCE, resumed=True)


def test_fresh_page_chains():
    assert types(page(Action.BROWSE)) == [
        EventType.VISITED, EventType.PRICE_SEEN, EventType.BROWSED]
    assert types(page(Action.CART)) == [
        EventType.VISITED, EventType.PRICE_SEEN, EventType.BROWSED, EventType.CARTED]
    assert types(page(Action.BUY)) == [
        EventType.VISITED, EventType.PRICE_SEEN, EventType.BROWSED,
        EventType.CARTED, EventType.BOUGHT]


def test_resumed_cart_chains():
    assert types(page(Action.BUY, resumed=True)) == [
        EventType.VISITED, EventType.PRICE_SEEN, EventType.BOUGHT]
    assert types(page(Action.ABANDON, resumed=True)) == [
        EventType.VISITED, EventType.PRICE_SEEN, EventType.ABANDONED]
    with pytest.raises(ValueError):
        page(Action.BROWSE, resumed=True)


def test_cause_creative_and_payloads():
    for action in (Action.BROWSE, Action.CART, Action.BUY):
        for e in page(action):
            assert e.prop("cause_creative") == CREATIVE
    evs = page(Action.BUY)
    price_seen = [e for e in evs if e.type is EventType.PRICE_SEEN][0]
    bought = [e for e in evs if e.type is EventType.BOUGHT][0]
    assert price_seen.subject == PRODUCT and price_seen.prop("price") == PRICE
    assert bought.subject == PRODUCT and bought.prop("price") == PRICE
    # page-subject events target the page; product events target the product
    assert {e.subject for e in evs if e.type in (EventType.VISITED, EventType.BROWSED)} == {PAGE}
    assert {e.subject for e in evs if e.type in (EventType.CARTED, EventType.BOUGHT)} == {PRODUCT}
