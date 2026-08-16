"""Phase-1 checkpoint: the golden preference chain renders end-to-end on the
real store — prior 0.45 -> 0.476 -> 0.532 -> 0.614 -> 0.714 -> 0.761, each
version carrying its cause (Appendix F numbers, asserted to the digit)."""

import pytest

from shopsim.contracts import evidence
from shopsim.contracts.enums import EventType
from shopsim.contracts.types import EvidenceDelta, EvidenceDeltaKey
from shopsim.hydramem import cypher, schema, story
from shopsim.hydramem.writes import OrderedDelta

pytestmark = pytest.mark.real

T0 = story.STORY_NOW - 10 * story.DAY


def _delta(kind, weight, target, t, cause_id):
    return OrderedDelta(t, 0, EvidenceDelta(
        key=EvidenceDeltaKey(kind="edge", subject=story.GOLDEN, object=story.ECO),
        target=target, weight=weight, cause_kind=kind, cause_id=cause_id))


def test_golden_chain_digit_exact_with_receipts(mock):
    mem = mock.mem
    # dedicated shopper — never 1000042/Maya-twin, whose symmetry other tests rely on
    mem.client.run_stmt(cypher.delete_edge("PREFERS", story.GOLDEN, story.ECO))
    mem.seed_preference(story.GOLDEN, story.ECO, 0.45, t=T0)

    mag, tgt = evidence.experienced_pref_evidence(1.0)
    chain = [
        _delta(EventType.CLICKED, 0.10, 1.0, T0 + 1 * story.DAY, story.STIM_AD),
        _delta(EventType.BROWSED, 0.25, 1.0, T0 + 2 * story.DAY, story.PAGE_OK),
        _delta(EventType.CARTED, 0.50, 1.0, T0 + 3 * story.DAY, story.PRODUCT),
        _delta(EventType.BOUGHT, 1.00, 1.0, T0 + 4 * story.DAY, story.PRODUCT),
        _delta(EventType.EXPERIENCED, mag, tgt, T0 + 6 * story.DAY, story.PRODUCT),
    ]
    saved = (mem._tick, mem._now, mem._tick_start)
    try:
        for od in chain:  # one per tick, as the runner would
            mem.set_tick(tick=0, now=od.t, tick_start=od.t)
            report = mem.apply_deltas({story.GOLDEN: [od]})
            assert report.written.get("edge") == 1
    finally:
        mem.set_tick(tick=saved[0], now=saved[1], tick_start=saved[2])

    hist = mem.get_preference_history(story.GOLDEN, story.ECO)
    assert [round(r["w"], 3) for r in hist] == [0.45, 0.476, 0.532, 0.614, 0.714, 0.761]
    assert hist[-1]["evidence"] == pytest.approx(4.6)
    assert evidence.confidence(hist[-1]["evidence"]) == pytest.approx(0.87, abs=0.005)

    causes = [(r["cause_kind"], r["cause_id"]) for r in hist]
    assert causes == [
        ("SEED", 0),
        ("CLICKED", story.STIM_AD),
        ("BROWSED", story.PAGE_OK),
        ("CARTED", story.PRODUCT),
        ("BOUGHT", story.PRODUCT),
        ("EXPERIENCED", story.PRODUCT),
    ]
    assert [r["source"] for r in hist] == ["prior"] + ["learned"] * 5

    live = [r for r in hist if r["valid_to"] == schema.VALID_TO_SENTINEL]
    assert len(live) == 1 and live[0]["w"] == hist[-1]["w"]
