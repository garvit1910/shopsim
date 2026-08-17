"""Action -> episodic-event expansion (CONTRACT v3.2 item 2 / v3.3 table).

The mind returns the deepest action reached; the runner expands it into the
episodic record chain. Page/product funnel events carry `cause_creative`
(JSONL-only — the EPISODIC_EDGE_TYPES whitelist keeps it off graph edges;
consolidate() uses it for concept attribution). A BOUNCE emits neither
VISITED nor PRICE_SEEN: VISITED carries preference evidence (Appendix F) and
a bounce must not teach taste; PRICE_SEEN requires engaging past the bounce.
"""

from __future__ import annotations

from ..contracts.enums import Action, EventType
from ..contracts.types import Event


def expand_creative(
    action: Action, sid: int, creative: int, t: int, run: int
) -> list[Event]:
    events = [Event(EventType.SAW, sid, t, run, creative)]
    if action is Action.CLICK:
        events.append(Event(EventType.CLICKED, sid, t, run, creative))
    elif action is not Action.IGNORE:
        raise ValueError(f"creative decision returned {action} (IGNORE|CLICK only)")
    return events


def expand_page(
    action: Action,
    sid: int,
    page: int,
    product: int,
    price: float,
    cause_creative: int,
    resumed: bool,
    t: int,
    run: int,
) -> list[Event]:
    cc = (("cause_creative", cause_creative),)

    def ev(etype: EventType, subject: int, *extra: tuple) -> Event:
        return Event(etype, sid, t, run, subject, props=tuple(extra) + cc)

    if action is Action.BOUNCE:
        if resumed:
            raise ValueError("a resumed cart cannot BOUNCE (BUY|ABANDON only)")
        return [ev(EventType.BOUNCED, page)]

    engaged = [ev(EventType.VISITED, page), ev(EventType.PRICE_SEEN, product, ("price", price))]
    if resumed:
        if action is Action.BUY:
            return engaged + [ev(EventType.BOUGHT, product, ("price", price))]
        if action is Action.ABANDON:
            return engaged + [ev(EventType.ABANDONED, product)]
        raise ValueError(f"resumed-cart decision returned {action} (BUY|ABANDON only)")

    if action is Action.BROWSE:
        return engaged + [ev(EventType.BROWSED, page)]
    if action is Action.CART:
        return engaged + [ev(EventType.BROWSED, page), ev(EventType.CARTED, product)]
    if action is Action.BUY:
        return engaged + [ev(EventType.BROWSED, page), ev(EventType.CARTED, product),
                          ev(EventType.BOUGHT, product, ("price", price))]
    if action is Action.ABANDON:
        # fresh page ABANDON (scripted stand-in shape): browsed, did not keep it
        return engaged + [ev(EventType.BROWSED, page), ev(EventType.ABANDONED, product)]
    raise ValueError(f"page decision returned {action}")
