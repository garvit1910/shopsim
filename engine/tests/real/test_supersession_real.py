"""Phase-1 checkpoint: supersession proof on three layers — subjective
(belief now vs as-of-T), objective (price now vs before the promo), goal
(NEEDS active -> satisfied-with-cause). Uses scratch ids outside every
Appendix-A block; cleans up after itself."""

import pytest

from shopsim.contracts.enums import EventType
from shopsim.contracts.ids import IdAllocator
from shopsim.contracts.types import EvidenceDelta, EvidenceDeltaKey
from shopsim.hydramem import cypher, schema, story
from shopsim.hydramem.writes import DeltaApplier, OrderedDelta

pytestmark = pytest.mark.real

SENT = schema.VALID_TO_SENTINEL
S = 900_060_001  # scratch shopper
P = 900_060_101  # scratch product
NOW = story.STORY_NOW


def test_objective_price_history_survives_the_promo(mock):
    c = mock.mem.client
    c.run_stmt(cypher.delete_edge("PRICED_AT", P, schema.PRICEBOOK_ID))
    try:
        c.run_stmt(cypher.create_edge("PRICED_AT", P, schema.PRICEBOOK_ID, {
            "price": 39.0, "t": NOW - 5 * story.DAY, "valid_to": SENT}))
        # promo lands: supersede, then the new price
        c.run_stmt(cypher.supersede_edge("PRICED_AT", P, schema.PRICEBOOK_ID, NOW))
        c.run_stmt(cypher.create_edge("PRICED_AT", P, schema.PRICEBOOK_ID, {
            "price": 33.15, "t": NOW, "valid_to": SENT}))

        live = c.run_stmt(cypher.live_edges("PRICED_AT", P, NOW + 1, ("price", "t")))
        assert [r["price"] for r in live] == [33.15]
        hist = c.run_stmt(cypher.edge_history("PRICED_AT", P, schema.PRICEBOOK_ID,
                                              ("price", "t", "valid_to")))
        assert sorted(r["price"] for r in hist) == [33.15, 39.0]
        # price-as-of before the promo
        before = [r for r in hist if r["t"] <= NOW - 1 < r["valid_to"]]
        assert [r["price"] for r in before] == [39.0]
    finally:
        c.run_stmt(cypher.delete_edge("PRICED_AT", P, schema.PRICEBOOK_ID))


def test_subjective_belief_now_vs_as_of_t(mock):
    mem = mock.mem
    c = mem.client
    alloc = IdAllocator(run_index=7)  # scratch belief block
    applier = DeltaApplier(c, alloc)

    def trust_delta(t, weight, target):
        return OrderedDelta(t, 0, EvidenceDelta(
            key=EvidenceDeltaKey(kind="belief", subject=S, object=story.SHOECO),
            target=target, weight=weight, cause_kind=EventType.VISITED,
            cause_id=story.PAGE_OK))

    t1, t2 = NOW - 3 * story.DAY, NOW - 1 * story.DAY
    try:
        applier.apply({S: [trust_delta(t1, 0.75, 0.6)]}, now=t1)
        applier.apply({S: [trust_delta(t2, 0.75, 0.9)]}, now=t2)

        versions = c.run_stmt(cypher.holds_history(S))
        assert len(versions) == 2
        versions.sort(key=lambda r: r["t"])
        v1, v2 = versions
        assert v1["valid_to"] == t2 and v2["valid_to"] == SENT  # old closed at t2
        # now: only v2 live
        live = c.run_stmt(cypher.live_holds(S, NOW))
        assert [r["dst"] for r in live] == [v2["dst"]]
        # as-of T between t1 and t2: v1 was the live belief
        as_of = t1 + story.DAY
        held_then = [r for r in versions if r["t"] <= as_of < r["valid_to"]]
        assert [r["dst"] for r in held_then] == [v1["dst"]]
        assert held_then[0]["value"] == pytest.approx(0.6)
        assert v2["value"] > v1["value"]  # contradicting evidence moved it up
    finally:
        for r in c.run_stmt(cypher.holds_history(S)):
            b = r["dst"]
            c.run_stmt(cypher.delete_edge("HOLDS", S, b))
            c.run_stmt(cypher.delete_edge("ABOUT", b, story.SHOECO))
            c.run_stmt(cypher.delete_edge("THAT", b, schema.ASPECT_TRUST_ID))
            c.run_stmt(cypher.delete_edge("DERIVED_FROM", b, story.PAGE_OK))


def test_goal_needs_satisfied_with_cause(mock):
    c = mock.mem.client
    c.run_stmt(cypher.delete_edge("NEEDS", S, story.RUNNING))
    try:
        c.run_stmt(cypher.create_edge("NEEDS", S, story.RUNNING, {
            "strength": 0.8, "budget_cap": 90.0, "deadline_t": NOW + 2 * story.DAY,
            "t": NOW - story.DAY, "valid_to": SENT, "source": "seeded"}))
        live = c.run_stmt(cypher.live_edges("NEEDS", S, NOW, ("strength",)))
        assert len(live) == 1

        # the purchase satisfies it — supersede with a cause receipt
        c.run_stmt(cypher.supersede_edge("NEEDS", S, story.RUNNING, NOW, {
            "closed_cause_kind": "BOUGHT", "closed_cause_id": story.PRODUCT}))

        assert c.run_stmt(cypher.live_edges("NEEDS", S, NOW + 1, ("strength",))) == []
        hist = c.run_stmt(cypher.edge_history(
            "NEEDS", S, story.RUNNING,
            ("strength", "t", "valid_to", "closed_cause_kind", "closed_cause_id")))
        assert len(hist) == 1
        closed = hist[0]
        assert closed["valid_to"] == NOW
        assert closed["closed_cause_kind"] == "BOUGHT"
        assert closed["closed_cause_id"] == story.PRODUCT
    finally:
        c.run_stmt(cypher.delete_edge("NEEDS", S, story.RUNNING))
