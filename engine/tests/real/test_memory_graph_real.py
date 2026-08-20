"""The memory-graph exporter on the live stack (Phase 5.9, CONTRACT v3.9-draft).

The pure half is tests/test_memory_graph.py. This one asserts the part only a
real store can prove: that a run seeded with `population.social` yields a
mutually-trusting triple, that the triple's subgraph is one connected graph
rather than three, and that the exhibit's headline path —
TRUSTS_PERSON -> BOUGHT -> EXPERIENCED — comes back as drawable edges whose
numbers match the social_proof motif retrieval computes from the same rows.

Rides test_social_real's run so the suite pays for one 4-tick run, not two.
"""

import pytest

from shopsim.contracts.ids import shopper_id as make_sid
from shopsim.hydramem import schema
from shopsim.hydramem.real import HydraMem

pytestmark = pytest.mark.real

from test_social_real import social_run  # noqa: E402,F401  (shared live run)


@pytest.fixture(scope="module")
def graph(social_run):
    cfg, run_index, _results = social_run
    mem = HydraMem(run_index=run_index)
    try:
        mem.set_tick(tick=cfg.ticks - 1, now=cfg.now_at(cfg.ticks - 1))
        triads = mem.find_social_triads()
        payload = (mem.get_memory_graph(triads[0]["shopper_ids"])
                   if triads else {"nodes": [], "edges": []})
        yield cfg, run_index, triads, payload
    finally:
        mem.close()


def test_triads_are_found_and_are_genuinely_mutual(graph):
    cfg, run_index, triads, _payload = graph
    assert triads, "a run with population.social must expose at least one triple"
    mem = HydraMem(run_index=run_index)
    try:
        from shopsim.hydramem import cypher
        for cand in triads[:3]:
            a, b, c = cand["shopper_ids"]
            adj = {s: {r["dst"] for r in mem.client.run_stmt(
                cypher.all_edges("TRUSTS_PERSON", s))} for s in (a, b, c)}
            assert b in adj[a] and c in adj[a] and c in adj[b], cand["offsets"]
    finally:
        mem.close()


def test_the_triple_is_one_connected_graph(graph):
    """The point of the exhibit: three worldviews sharing concept, brand and
    product nodes, not three disjoint islands."""
    _cfg, _idx, triads, payload = graph
    nodes = {n["id"] for n in payload["nodes"]}
    adj: dict[int, set[int]] = {n: set() for n in nodes}
    for e in payload["edges"]:
        adj[e["source"]].add(e["target"])
        adj[e["target"]].add(e["source"])

    seen, stack = set(), [next(iter(nodes))]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(adj[cur] - seen)
    assert seen == nodes, f"{len(nodes) - len(seen)} nodes are unreachable"

    focus = set(triads[0]["shopper_ids"])
    shared = [n["id"] for n in payload["nodes"]
              if n["kind"] in ("concept", "brand", "product", "category")
              and len({e["source"] for e in payload["edges"]
                       if e["target"] == n["id"]} & focus) > 1]
    assert shared, "no node is shared between the three shoppers"


def test_every_edge_resolves_to_a_node(graph):
    """d3.forceLink throws on an unresolvable id — a dangling edge blanks the
    whole canvas, so this is a hard invariant, not a nicety."""
    _cfg, _idx, _triads, payload = graph
    ids = {n["id"] for n in payload["nodes"]}
    dangling = [e["id"] for e in payload["edges"]
                if e["source"] not in ids or e["target"] not in ids]
    assert not dangling, dangling[:5]


def test_the_graph_only_reports_relationships_the_schema_declares(graph):
    _cfg, _idx, _triads, payload = graph
    rels = {e["rel"] for e in payload["edges"]}
    assert rels and rels <= set(schema.ALL_EDGES)


def test_the_social_proof_path_is_drawable_and_agrees_with_retrieval(graph):
    """The headline exhibit. Whatever social_proof the engine computes for a
    decision, the same peer, the same product and the same satisfaction must
    be present as edges — otherwise the picture and the number disagree."""
    cfg, run_index, triads, payload = graph
    by_rel: dict[str, list] = {}
    for e in payload["edges"]:
        by_rel.setdefault(e["rel"], []).append(e)

    trusts = by_rel.get("TRUSTS_PERSON", [])
    assert trusts, "the trust layer is missing from the payload"

    bought = by_rel.get("BOUGHT", [])
    if not bought:
        pytest.skip("no purchase inside this run's window — nothing to trace")

    mem = HydraMem(run_index=run_index)
    try:
        mem.set_tick(tick=cfg.ticks - 1, now=cfg.now_at(cfg.ticks - 1),
                     tick_start=cfg.now_at(cfg.ticks - 1))
        hits = []
        for sid in triads[0]["shopper_ids"]:
            for m in mem.get_trace(sid, 2000003)["motifs"]:
                if m["type"] == "social_proof":
                    hits.append((sid, m))
        if not hits:
            pytest.skip("no social_proof motif on this stimulus")
        _sid, motif = hits[0]
        _shopper, _rel, peer, _rel2, product = motif["path"]
        assert any(e["source"] == _shopper and e["target"] == peer
                   for e in trusts), "the trust hop is not drawn"
        assert any(e["source"] == peer and e["target"] == product
                   for e in bought), "the peer's purchase is not drawn"
        # the valence the motif reports is the friend's EXPERIENCED sat,
        # trust-scaled — so that sat has to be on an edge too
        exps = [e for e in by_rel.get("EXPERIENCED", [])
                if e["source"] == peer and e["target"] == product]
        if motif["experience"] != schema.DEFAULT_PARAMS.social_default_experience:
            assert exps, "the friend's experience is missing from the payload"
            sats = [v["sat"] for e in exps for v in e["versions"]]
            assert pytest.approx(motif["experience"]) == sats[-1]
    finally:
        mem.close()


def test_the_day_scrub_grows_the_worldview(graph):
    """Filtering the payload by `time` + t/valid_to must reproduce a worldview
    that only ever accumulates within the run window — the client does exactly
    this, so if the discipline is wrong the scrub lies."""
    cfg, _idx, _triads, payload = graph
    sent = schema.VALID_TO_SENTINEL

    def live(e, as_of):
        if e["time"] == "static":
            return True
        if e["time"] == "event":
            return any(v.get("t", 0) <= as_of for v in e["versions"])
        return any(v.get("t", 0) <= as_of < v.get("valid_to", sent)
                   for v in e["versions"])

    counts = [sum(1 for e in payload["edges"] if live(e, cfg.now_at(d)))
              for d in range(cfg.ticks)]
    assert counts[0] > 0
    assert counts[-1] >= counts[0], counts
    episodic = [sum(1 for e in payload["edges"]
                    if e["time"] == "event" and live(e, cfg.now_at(d)))
                for d in range(cfg.ticks)]
    assert episodic == sorted(episodic), f"events must never un-happen: {episodic}"
