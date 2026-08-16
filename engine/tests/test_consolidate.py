"""Phase 2.5 — consolidate(): purity, the evidence hierarchy, the golden
chain from events, no learning from exposure (F7), HAS_ATTR truth channel."""

import pytest

from shopsim.contracts import evidence
from shopsim.contracts.enums import EventType
from shopsim.contracts.types import Event, WorldviewSnapshot
from shopsim.minds.consolidation import consolidate
from shopsim.minds.objective_view import ObjectiveView

SID = 1000052
AD = 2000003  # EcoStride Sale: claims {5003: 0.9, 5005: 0.6, 5011: 0.8}
ECO_AD = 2000001  # claims {5003: 0.9, 5004: 0.8}
PAGE = 4000001
PRODUCT = 3000001  # HAS_ATTR {5003, 5004, 5005, 5001}, category 5504, brand 6001
ECO = 5003
EMPTY = WorldviewSnapshot()


@pytest.fixture(scope="module")
def view(fixtures_dir) -> ObjectiveView:
    return ObjectiveView.from_catalog(fixtures_dir / "demo-brand")


def _event(etype, subject, t=100, **props):
    return Event(type=etype, shopper_id=SID, t=t, run=0, subject=subject,
                 props=tuple(props.items()))


def _eco_deltas(deltas, kind="edge"):
    return [d for d in deltas if d.key.kind == kind and d.key.object == ECO]


def test_pure_same_inputs_same_deltas(view):
    events = [_event(EventType.SAW, AD, 9), _event(EventType.CLICKED, AD, 10),
              _event(EventType.BOUGHT, PRODUCT, 11, price=39.0)]
    snap = WorldviewSnapshot(prefs=((ECO, 0.45, 2.0),))
    assert consolidate(list(events), snap, view) == consolidate(list(events), snap, view)


def test_no_learning_from_saw(view):
    """F7: bombardment with exposures yields ZERO preference deltas while
    expectations still move."""
    events = [_event(EventType.SAW, AD, t) for t in range(20)]
    deltas = consolidate(events, EMPTY, view)
    assert not [d for d in deltas if d.key.kind == "edge"]
    expects = [d for d in deltas if d.key.kind == "expects"]
    assert expects, "SAW must still teach EXPECTS"
    # target = perceived claim strength; weight from evidence.py's SAW row
    for d in expects:
        assert d.weight == evidence.EVIDENCE_TABLE[EventType.SAW].belief_weight
        assert d.target == view.facts(AD).claims[d.key.object]
        assert d.cause_kind is EventType.SAW


def test_hierarchy_strictly_ordered(view):
    """F8: equal counts of CLICK/BROWSE/CART/BUY ⇒ strictly ordered Δw."""
    w0, e0 = 0.45, evidence.PRIOR_E0
    deltas_by_event = []
    for etype, subject in [
        (EventType.CLICKED, AD),
        (EventType.BROWSED, PAGE),
        (EventType.CARTED, PRODUCT),
        (EventType.BOUGHT, PRODUCT),
    ]:
        out = consolidate([_event(etype, subject, cause_creative=AD)], EMPTY, view)
        eco = _eco_deltas(out)
        assert len(eco) == 1, etype
        w1, _ = evidence.blend(w0, e0, eco[0].target, eco[0].weight)
        deltas_by_event.append(w1 - w0)
    assert all(a < b for a, b in zip(deltas_by_event, deltas_by_event[1:]))


def test_golden_chain_from_events(view):
    """CLICK → BROWSE → CART → BUY → EXPERIENCED(sat=1) reproduces
    0.476 → 0.532 → 0.614 → 0.714 → 0.761 on eco, digit-exact."""
    chain = [
        _event(EventType.CLICKED, AD, 1, cause_creative=AD),
        _event(EventType.BROWSED, PAGE, 2, cause_creative=AD),
        _event(EventType.CARTED, PRODUCT, 3, cause_creative=AD),
        _event(EventType.BOUGHT, PRODUCT, 4, price=39.0, cause_creative=AD),
        _event(EventType.EXPERIENCED, PRODUCT, 5, sat=1.0),
    ]
    w, e = 0.45, evidence.PRIOR_E0
    trajectory = []
    for ev in chain:
        eco = _eco_deltas(consolidate([ev], EMPTY, view))
        assert len(eco) == 1, ev.type
        w, e = evidence.blend(w, e, eco[0].target, eco[0].weight)
        trajectory.append(round(w, 3))
    assert trajectory == [0.476, 0.532, 0.614, 0.714, 0.761]
    assert e == pytest.approx(4.6)


def test_experienced_prefs_only_on_has_attr(view):
    """Ads teach expectations, experience teaches truth: the ad claimed
    DISCOUNT (5011), but the product's attrs are {5001, 5003, 5004, 5005}."""
    deltas = consolidate([_event(EventType.EXPERIENCED, PRODUCT, sat=0.9)], EMPTY, view)
    edge_concepts = {d.key.object for d in deltas if d.key.kind == "edge"}
    assert edge_concepts == {5001, 5003, 5004, 5005}
    assert 5011 not in edge_concepts
    # bad experience pulls toward 0 with the same magnitude rule
    bad = consolidate([_event(EventType.EXPERIENCED, PRODUCT, sat=0.2)], EMPTY, view)
    for d in bad:
        if d.key.kind == "edge":
            assert d.target == 0.0
            assert d.weight == pytest.approx(0.75 * abs(2 * 0.2 - 1))


def test_buy_trust_and_need_satisfaction(view):
    snap = WorldviewSnapshot(active_needs=((5504, 0.8, 1_755_400_000),))
    deltas = consolidate([_event(EventType.BOUGHT, PRODUCT, price=39.0)], snap, view)
    beliefs = [d for d in deltas if d.key.kind == "belief"]
    assert len(beliefs) == 1
    assert beliefs[0].key.object == 6001  # SOLD_BY brand
    assert (beliefs[0].weight, beliefs[0].target) == (1.5, 0.65)
    needs = [d for d in deltas if d.key.kind == "need_satisfy"]
    assert len(needs) == 1 and needs[0].key.object == 5504
    # no matching active need → no need_satisfy delta
    off = consolidate([_event(EventType.BOUGHT, PRODUCT, price=39.0)], EMPTY, view)
    assert not [d for d in off if d.key.kind == "need_satisfy"]


def test_price_seen_smooths_reference_price(view):
    deltas = consolidate([_event(EventType.PRICE_SEEN, PRODUCT, price=33.15)], EMPTY, view)
    refs = [d for d in deltas if d.key.kind == "ref_price"]
    assert len(refs) == 1
    assert refs[0].target == 33.15 and refs[0].key.object == PRODUCT


def test_only_applier_kinds_emitted(view):
    """P0 emits exactly the applier's vocabulary — never P1 kinds."""
    events = [
        _event(EventType.SAW, AD, 1), _event(EventType.CLICKED, AD, 2),
        _event(EventType.VISITED, PAGE, 3, cause_creative=AD),
        _event(EventType.BROWSED, PAGE, 4, cause_creative=AD),
        _event(EventType.BOUNCED, PAGE, 5),
        _event(EventType.CARTED, PRODUCT, 6, cause_creative=AD),
        _event(EventType.ABANDONED, PRODUCT, 7),
        _event(EventType.BOUGHT, PRODUCT, 8, price=39.0),
        _event(EventType.PRICE_SEEN, PRODUCT, 9, price=39.0),
        _event(EventType.EXPERIENCED, PRODUCT, 10, sat=0.9),
    ]
    deltas = consolidate(events, EMPTY, view)
    assert {d.key.kind for d in deltas} <= {"edge", "belief", "expects",
                                            "ref_price", "need_satisfy"}
    # provenance: every delta carries its cause
    for d in deltas:
        assert isinstance(d.cause_kind, EventType) and d.cause_id > 0


def test_bounce_abandon_and_need_records_carry_no_evidence(view):
    events = [_event(EventType.BOUNCED, PAGE), _event(EventType.ABANDONED, PRODUCT),
              _event(EventType.NEED_ACTIVATED, 5504), _event(EventType.NEED_EXPIRED, 5504)]
    assert consolidate(events, EMPTY, view) == []
