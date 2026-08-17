"""consolidate() — pure worldview learning, P0 (Phase 2.5).

(events, WorldviewSnapshot) + the frozen ObjectiveView → EvidenceDelta[].
The mind never writes: the engine's DeltaApplier (hydramem/writes.py) reads
current (w, E), blends per contracts/evidence.py, and writes supersessions.
Every weight/target here comes from evidence.py — the single source of
behavioral learning (Law 14); this module contains no update constants.

Delta kinds emitted (exactly the applier's vocabulary, CONTRACT v3.1):
    "edge"          PREFERS evidence        (CLICK/BROWSE/VISIT/CART/BUY/EXPERIENCED)
    "belief"        trust Belief evidence   (VISIT/BROWSE/BUY/EXPERIENCED)
    "expects"       EXPECTS α-smoothing     (SAW/CLICK; target = perceived claim strength)
    "ref_price"     reference-price smoothing (PRICE_SEEN)
    "need_satisfy"  NEEDS supersede-with-cause (BUY in an active-need category)
P1 kinds ("habit", "belief:quality") are never emitted at P0.

The evidence hierarchy is law: SAW teaches only what a brand claims (EXPECTS)
— zero preference deltas (F7). Engagement (CLICK < BROWSE < CART < BUY)
teaches taste on the claimed concepts, target 1.0. EXPERIENCED teaches truth:
trust toward actual satisfaction, preferences only on concepts the product
actually HAS_ATTR.

Concept attribution for engagement events: the perceived claims of the
stimulus itself (creative subjects), else of the originating creative when
the event carries a `cause_creative` prop (runner convention, CONTRACT v3.2
pending), else catalog truth (HAS_ATTR ∩ page SHOWS for pages; HAS_ATTR for
products).
"""

from __future__ import annotations

from ..contracts import evidence
from ..contracts.enums import EventType
from ..contracts.types import Event, EvidenceDelta, EvidenceDeltaKey, WorldviewSnapshot
from .objective_view import ObjectiveView, StimulusFacts

_ENGAGEMENT = {
    EventType.CLICKED,
    EventType.VISITED,
    EventType.BROWSED,
    EventType.CARTED,
    EventType.BOUGHT,
}


def _claims_for(event: Event, view: ObjectiveView) -> dict[int, float]:
    """Perceived claim strengths attributed to this event's concepts."""
    facts: StimulusFacts | None = view.facts(event.subject)
    if facts is not None and facts.kind == "creative":
        return dict(facts.claims)
    cause = event.prop("cause_creative")
    if cause is not None:
        cf = view.facts(int(cause))
        if cf is not None:
            return dict(cf.claims)
    # catalog-truth fallback (no originating creative known)
    if facts is not None and facts.kind == "page":
        prods = list(facts.products)
        attrs: set[int] = set()
        for p in prods:
            attrs |= set(view.product_attrs.get(p, ()))
        return {c: 1.0 for c in sorted(attrs & set(facts.shows))}
    return {c: 1.0 for c in sorted(view.product_attrs.get(event.subject, ()))}


def _brand_for(event: Event, view: ObjectiveView) -> int:
    facts = view.facts(event.subject)
    if facts is not None:
        return facts.brand_id
    return view.product_brand.get(event.subject, 0)


def _expects_cause_id(event: Event, view: ObjectiveView) -> int:
    """The applier resolves the EXPECTS brand from the causing creative's
    PROMOTES edge, so cause_id must be a creative id."""
    facts = view.facts(event.subject)
    if facts is not None and facts.kind == "creative":
        return event.subject
    cause = event.prop("cause_creative")
    return int(cause) if cause is not None else event.subject


def consolidate(
    events: list[Event], snapshot: WorldviewSnapshot, view: ObjectiveView
) -> list[EvidenceDelta]:
    active_categories = {c for c, _, _ in snapshot.active_needs}
    deltas: list[EvidenceDelta] = []

    for e in sorted(events, key=lambda e: (e.shopper_id, e.t)):
        row = evidence.EVIDENCE_TABLE.get(e.type)

        if e.type is EventType.PRICE_SEEN:
            price = e.prop("price")
            if price is not None:
                deltas.append(EvidenceDelta(
                    key=EvidenceDeltaKey("ref_price", e.shopper_id, e.subject),
                    target=float(price), weight=1.0,
                    cause_kind=e.type, cause_id=e.subject))
            continue

        if e.type is EventType.EXPERIENCED:
            sat = float(e.prop("sat", 0.5))
            brand = _brand_for(e, view)
            b_weight, b_target = evidence.experienced_belief_evidence(sat)
            if brand:
                deltas.append(EvidenceDelta(
                    key=EvidenceDeltaKey("belief", e.shopper_id, brand),
                    target=b_target, weight=b_weight,
                    cause_kind=e.type, cause_id=e.subject))
            p_weight, p_target = evidence.experienced_pref_evidence(sat)
            # truth channel: ONLY concepts the product actually HAS_ATTR
            for concept in sorted(view.product_attrs.get(e.subject, ())):
                deltas.append(EvidenceDelta(
                    key=EvidenceDeltaKey("edge", e.shopper_id, concept),
                    target=p_target, weight=p_weight,
                    cause_kind=e.type, cause_id=e.subject))
            continue

        if row is None:
            continue  # BOUNCED/ABANDONED/NEED_* carry no evidence at P0

        claims = _claims_for(e, view)

        # preference evidence — the hierarchy (SAW's 0.0 emits nothing)
        if row.pref_weight > 0 and e.type in _ENGAGEMENT:
            for concept in sorted(claims):
                deltas.append(EvidenceDelta(
                    key=EvidenceDeltaKey("edge", e.shopper_id, concept),
                    target=evidence.PREF_TARGET, weight=row.pref_weight,
                    cause_kind=e.type, cause_id=e.subject))

        # belief channel: target None = EXPECTS (SAW/CLICK), else trust Belief
        if row.belief_weight:
            if row.belief_target is None:
                cause_id = _expects_cause_id(e, view)
                for concept in sorted(claims):
                    deltas.append(EvidenceDelta(
                        key=EvidenceDeltaKey("expects", e.shopper_id, concept),
                        target=claims[concept], weight=row.belief_weight,
                        cause_kind=e.type, cause_id=cause_id))
            else:
                brand = _brand_for(e, view)
                if brand:
                    deltas.append(EvidenceDelta(
                        key=EvidenceDeltaKey("belief", e.shopper_id, brand),
                        target=row.belief_target, weight=row.belief_weight,
                        cause_kind=e.type, cause_id=e.subject))

        # BUY satisfies the matching active need (supersede-with-cause)
        if e.type is EventType.BOUGHT:
            category = view.product_category.get(e.subject)
            if category in active_categories:
                deltas.append(EvidenceDelta(
                    key=EvidenceDeltaKey("need_satisfy", e.shopper_id, category),
                    target=1.0, weight=1.0,
                    cause_kind=e.type, cause_id=e.subject))

    return deltas
