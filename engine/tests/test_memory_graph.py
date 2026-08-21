"""The memory-graph exporter (Phase 5.9, CONTRACT v3.9-draft) — pure half.

The exporter's whole contract is that it invents nothing: every node and every
edge it emits corresponds to a row the store actually returned. These tests
pin the three places where that could quietly stop being true — node typing,
shared nodes, and version folding — plus the as-of discipline the client
depends on to scrub through days.
"""

import itertools
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from shopsim.contracts.ids import PAGE_VARIANT_BASE
from shopsim.contracts.ids import shopper_id as make_sid
from shopsim.hydramem import schema
from shopsim.hydramem.memgraph import (
    assemble_memory_graph,
    memory_graph_read_plan,
    node_kind,
    score_triad,
    triangles,
    why_triad,
)

SENT = schema.VALID_TO_SENTINEL
RUN = 44
A, B, C = (make_sid(RUN, 0), make_sid(RUN, 1), make_sid(RUN, 2))
PEER = make_sid(RUN, 3)
ECO, RECYCLED = 5003, 5004
BRAND, PRODUCT, CREATIVE, PAGE, CATEGORY = 6001, 3_000_001, 2_000_001, 4_000_001, 5504
BELIEF = 8_044_000_001

CACHE = SimpleNamespace(
    creatives={CREATIVE: {"brand": BRAND, "claims": {ECO: 0.9}, "offers": {PRODUCT: 0.0}}},
    pages={PAGE: {"product": PRODUCT, "shows": frozenset({ECO}), "brand": BRAND}},
    product_brand={PRODUCT: BRAND},
    product_category={PRODUCT: CATEGORY},
    prices={PRODUCT: 39.0},
)


def _rows(**kw):
    base = {"props": [{"segment_id": 1001}]}
    base.update(kw)
    return base


def build(rows_by_shopper, *, focus=(A, B, C), belief_rows=None, peer_rows=None,
          product_rows=None):
    return assemble_memory_graph(
        focus_ids=focus,
        rows_by_shopper=rows_by_shopper,
        belief_rows=belief_rows or {},
        peer_rows=peer_rows or {},
        product_rows=product_rows or {},
        cache=CACHE,
    )


def nodes_by_id(graph):
    return {n["id"]: n for n in graph["nodes"]}


def edges_by_id(graph):
    return {e["id"]: e for e in graph["edges"]}


# ---------------------------------------------------------------------------
# node typing
# ---------------------------------------------------------------------------


def test_shopper_ids_are_not_mistaken_for_catalog_ids():
    """Run 44's shoppers live at 5_400_00x, straight through the product and
    page-variant blocks. Range classification alone would call offset 0 a page
    variant; the shopper set has to come from the TRUSTS_PERSON closure."""
    shoppers = frozenset({A, B, C})
    assert A == 5_400_000 > PAGE_VARIANT_BASE  # the overlap is real, not theoretical
    assert node_kind(A, shoppers) == "shopper"
    assert node_kind(A, frozenset()) == "page"  # the bug this guards against
    assert node_kind(PRODUCT, shoppers) == "product"
    assert node_kind(CREATIVE, shoppers) == "creative"
    assert node_kind(PAGE, shoppers) == "page"
    assert node_kind(BELIEF, shoppers) == "belief"
    assert node_kind(ECO, shoppers) == "concept"
    assert node_kind(CATEGORY, shoppers) == "category"
    assert node_kind(BRAND, shoppers) == "brand"
    assert node_kind(schema.ASPECT_TRUST_ID, shoppers) == "aspect"


def test_trusted_peers_become_shoppers_even_outside_the_focus():
    g = build({A: _rows(TRUSTS_PERSON=[{"dst": PEER, "w": 0.5}])}, focus=[A])
    n = nodes_by_id(g)
    assert n[PEER]["kind"] == "shopper"
    assert n[PEER]["props"]["peer"] is True and n[PEER]["props"]["focus"] is False
    assert n[A]["props"]["focus"] is True


def test_concept_and_category_labels_come_from_the_closed_vocabularies():
    g = build({A: _rows(PREFERS=[{"dst": ECO, "w": 0.6, "evidence": 2.0,
                                  "source": "prior", "cause_kind": "SEED",
                                  "cause_id": 0, "t": 0, "valid_to": SENT}])},
              focus=[A])
    assert nodes_by_id(g)[ECO]["label"] == "eco_friendly"


# ---------------------------------------------------------------------------
# shared nodes — the reason this is one graph and not three widgets
# ---------------------------------------------------------------------------


def test_a_concept_two_shoppers_prefer_is_one_node_with_two_edges():
    pref = lambda w: [{"dst": ECO, "w": w, "evidence": 2.0, "source": "prior",
                       "cause_kind": "SEED", "cause_id": 0, "t": 0, "valid_to": SENT}]
    g = build({A: _rows(PREFERS=pref(0.6)), B: _rows(PREFERS=pref(0.8))}, focus=[A, B])
    assert sum(1 for n in g["nodes"] if n["id"] == ECO) == 1
    prefers = [e for e in g["edges"] if e["rel"] == "PREFERS"]
    assert {e["source"] for e in prefers} == {A, B}
    assert {e["target"] for e in prefers} == {ECO}


def test_the_objective_closure_links_a_seen_ad_to_its_brand_and_product():
    g = build({A: _rows(SAW=[{"dst": CREATIVE, "t": 10, "run": RUN}])}, focus=[A])
    e = edges_by_id(g)
    assert e[f"CLAIMS:{CREATIVE}:{ECO}"]["versions"][0]["strength"] == 0.9
    assert f"PROMOTES:{CREATIVE}:{BRAND}" in e
    assert f"OFFERS:{CREATIVE}:{PRODUCT}" in e
    # second pass: the product OFFERS introduced gets closed too
    assert f"SOLD_BY:{PRODUCT}:{BRAND}" in e
    assert f"IN_CATEGORY:{PRODUCT}:{CATEGORY}" in e


def test_every_edge_endpoint_exists_as_a_node():
    """A dangling link is not a cosmetic problem — d3.forceLink throws on an
    id it cannot resolve, so the whole canvas would go blank."""
    g = build({A: _rows(SAW=[{"dst": CREATIVE, "t": 10, "run": RUN}],
                        VISITED=[{"dst": PAGE, "t": 11, "run": RUN}],
                        TRUSTS_PERSON=[{"dst": PEER, "w": 0.5}])}, focus=[A])
    ids = set(nodes_by_id(g))
    for e in g["edges"]:
        assert e["source"] in ids and e["target"] in ids, e["id"]


# ---------------------------------------------------------------------------
# version folding
# ---------------------------------------------------------------------------


def test_repeat_events_fold_into_one_edge_carrying_every_occurrence():
    g = build({A: _rows(VISITED=[{"dst": PAGE, "t": t, "run": RUN}
                                 for t in (10, 20, 30)])}, focus=[A])
    e = edges_by_id(g)[f"VISITED:{A}:{PAGE}"]
    assert e["count"] == 3
    assert [v["t"] for v in e["versions"]] == [10, 20, 30]
    assert e["time"] == "event"
    assert sum(1 for x in g["edges"] if x["rel"] == "VISITED") == 1


def test_preference_supersessions_fold_into_one_edge_ordered_by_t():
    chain = [{"dst": ECO, "w": w, "evidence": 2.0, "source": "learned",
              "cause_kind": "CLICKED", "cause_id": CREATIVE, "t": t, "valid_to": vt}
             for w, t, vt in ((0.6, 0, 100), (0.7, 100, 200), (0.8, 200, SENT))]
    g = build({A: _rows(PREFERS=list(reversed(chain)))}, focus=[A])
    e = edges_by_id(g)[f"PREFERS:{A}:{ECO}"]
    assert e["time"] == "bitemporal"
    assert [v["w"] for v in e["versions"]] == [0.6, 0.7, 0.8]
    assert [v["valid_to"] for v in e["versions"]] == [100, 200, SENT]


def test_belief_satellites_inherit_the_belief_version_window():
    """A belief gets a fresh node id per version. ABOUT/THAT/DERIVED_FROM carry
    no time of their own, so without the stamp every retired version would
    stay on screen forever."""
    g = build(
        {A: _rows(HOLDS=[{"dst": BELIEF, "value": 0.7, "evidence": 3.0,
                          "about_id": BRAND, "that_id": schema.ASPECT_TRUST_ID,
                          "t": 100, "valid_to": 200}])},
        focus=[A],
        belief_rows={BELIEF: {
            "ABOUT": [{"dst": BRAND}],
            "THAT": [{"dst": schema.ASPECT_TRUST_ID}],
            "DERIVED_FROM": [{"dst": PRODUCT, "kind": "BOUGHT", "count": 1,
                              "first_t": 100, "last_t": 100, "weight": 1.0}]}})
    e = edges_by_id(g)
    for rel, dst in (("ABOUT", BRAND), ("THAT", schema.ASPECT_TRUST_ID),
                     ("DERIVED_FROM", PRODUCT)):
        edge = e[f"{rel}:{BELIEF}:{dst}"]
        assert edge["time"] == "bitemporal", rel
        assert edge["versions"][0]["t"] == 100 and edge["versions"][0]["valid_to"] == 200
    assert e[f"DERIVED_FROM:{BELIEF}:{PRODUCT}"]["versions"][0]["kind"] == "BOUGHT"
    assert nodes_by_id(g)[BELIEF]["props"]["aspect"] == "trust"


def test_time_discipline_matches_the_schema_catalog():
    """The client filters on `time` alone, so it must agree with the store's
    own notion of which edges are bitemporal."""
    g = build({A: _rows(
        PREFERS=[{"dst": ECO, "w": 0.6, "evidence": 2.0, "source": "prior",
                  "cause_kind": "SEED", "cause_id": 0, "t": 0, "valid_to": SENT}],
        SAW=[{"dst": CREATIVE, "t": 10, "run": RUN}],
        TRUSTS_PERSON=[{"dst": PEER, "w": 0.5}])}, focus=[A])
    by_rel = {e["rel"]: e for e in g["edges"]}
    assert by_rel["PREFERS"]["time"] == "bitemporal"
    assert "PREFERS" in schema.BITEMPORAL_EDGES
    assert by_rel["SAW"]["time"] == "event"
    assert by_rel["TRUSTS_PERSON"]["time"] == "static"
    assert by_rel["CLAIMS"]["time"] == "static"


def test_reciprocal_trust_is_flagged_but_both_rows_are_kept():
    """seed_population writes TRUSTS_PERSON both ways. Both are really stored,
    and Explain walks the directed one, so neither is dropped — the flag just
    lets the canvas draw one arc per pair."""
    g = build({A: _rows(TRUSTS_PERSON=[{"dst": B, "w": 0.8}]),
               B: _rows(TRUSTS_PERSON=[{"dst": A, "w": 0.8}, {"dst": PEER, "w": 0.4}])},
              focus=[A, B])
    e = edges_by_id(g)
    assert e[f"TRUSTS_PERSON:{A}:{B}"]["reciprocal"] is True
    assert e[f"TRUSTS_PERSON:{B}:{A}"]["reciprocal"] is True
    assert e[f"TRUSTS_PERSON:{B}:{PEER}"]["reciprocal"] is False


# ---------------------------------------------------------------------------
# peer stubs
# ---------------------------------------------------------------------------


def test_a_peers_purchase_is_kept_only_when_the_product_is_already_on_screen():
    """The friend's-experience hop, without dragging the population in: a
    degree-4 trust graph would otherwise pull every peer's whole basket."""
    other = PRODUCT + 7
    rows = {A: _rows(TRUSTS_PERSON=[{"dst": PEER, "w": 0.8}],
                     BOUGHT=[{"dst": PRODUCT, "t": 5, "run": RUN, "price": 39.0}])}
    peers = {PEER: {"peer_bought": [{"dst": PRODUCT, "t": 1, "run": RUN, "price": 39.0},
                                    {"dst": other, "t": 2, "run": RUN, "price": 55.0}],
                    "peer_experienced": [{"dst": PRODUCT, "t": 3, "run": RUN,
                                          "sat": 0.86}]}}
    g = build(rows, focus=[A], peer_rows=peers)
    e = edges_by_id(g)
    assert f"BOUGHT:{PEER}:{PRODUCT}" in e
    assert e[f"EXPERIENCED:{PEER}:{PRODUCT}"]["versions"][0]["sat"] == 0.86
    assert f"BOUGHT:{PEER}:{other}" not in e
    assert other not in nodes_by_id(g)


def test_the_whole_social_proof_path_is_drawable():
    """Maya -TRUSTS_PERSON-> Leo -BOUGHT-> product <-EXPERIENCED- Leo, which is
    exactly reads.assemble_context's social_proof path plus the valence hop."""
    rows = {C: _rows(TRUSTS_PERSON=[{"dst": B, "w": 0.7976}],
                     PRICE_SEEN=[{"dst": PRODUCT, "t": 4, "run": RUN, "price": 39.0}])}
    peers = {B: {"peer_bought": [{"dst": PRODUCT, "t": 1, "run": RUN, "price": 39.0}],
                 "peer_experienced": [{"dst": PRODUCT, "t": 2, "run": RUN, "sat": 0.8589}]}}
    g = build(rows, focus=[C], peer_rows=peers)
    e = edges_by_id(g)
    assert e[f"TRUSTS_PERSON:{C}:{B}"]["versions"][0]["w"] == 0.7976
    assert e[f"BOUGHT:{B}:{PRODUCT}"]["versions"][0]["price"] == 39.0
    assert e[f"EXPERIENCED:{B}:{PRODUCT}"]["versions"][0]["sat"] == 0.8589


# ---------------------------------------------------------------------------
# read plan + triad ranking
# ---------------------------------------------------------------------------


def test_the_read_plan_asks_only_for_whitelisted_props():
    """Built off schema.ALL_EDGES, so cypher's prop check can never reject it
    and it cannot drift out of sync with the catalog."""
    plan = memory_graph_read_plan(A)
    names = [name for name, _ in plan]
    assert names[-2:] == ["HOLDS", "props"]
    for rel, (query, _params) in plan[:-2]:
        for prop in schema.ALL_EDGES[rel]:
            assert f"e.{prop} AS {prop}" in query, (rel, prop)


def test_triads_are_ranked_by_whether_they_can_show_the_mechanism():
    adj = {1: {2, 3}, 2: {1, 3}, 3: {1, 2}, 4: {5, 6}, 5: {4, 6}, 6: {4, 5}}
    assert triangles(adj) == [(1, 2, 3), (4, 5, 6)]
    bought, exp = {2: {PRODUCT}}, {2: {PRODUCT}}
    lived = score_triad((1, 2, 3), bought, exp, {})
    inert = score_triad((4, 5, 6), bought, exp, {})
    assert lived > inert
    assert "social_proof path is live" in why_triad((1, 2, 3), bought, exp)
    assert "nobody in the triple bought" in why_triad((4, 5, 6), bought, exp)


def test_a_run_without_the_social_layer_yields_no_triads():
    assert triangles({}) == []


@pytest.mark.parametrize("rel", sorted(schema.SOCIAL_EDGES))
def test_trusts_person_is_still_the_only_shopper_valued_relationship(rel):
    """node_kind's correctness rests on this. If a second shopper->shopper
    relationship is ever added, the shopper-set closure must learn about it."""
    assert rel == "TRUSTS_PERSON"
    assert len(schema.SOCIAL_EDGES) == 1


# ---------------------------------------------------------------------------
# the committed capture (no database — the golden-run pattern)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def frozen():
    path = (Path(__file__).resolve().parents[2]
            / "fixtures" / "social-graph" / "memory-graph.json")
    assert path.exists(), (
        "fixtures/social-graph/memory-graph.json is missing — regenerate with "
        "`python -m shopsim.runner export-graph` (see the README beside it)")
    return json.loads(path.read_text())


def test_the_capture_says_what_it_is_a_photograph_of(frozen):
    """A frozen graph that does not name its source reads as live state."""
    cap = frozen["captured"]
    assert cap["run_id"] and isinstance(cap["run_index"], int)
    assert 0 <= cap["head_tick"] < frozen["ticks"]
    assert frozen["head_tick"] == cap["head_tick"]
    assert "frozen capture" in frozen["comment"].lower()
    assert "export-graph" in frozen["comment"]


def test_every_frozen_edge_resolves_to_a_node(frozen):
    """d3.forceLink throws on an id it cannot resolve, so one dangling edge
    blanks the whole canvas. This is the check a bad regeneration must fail."""
    ids = {n["id"] for n in frozen["nodes"]}
    dangling = [e["id"] for e in frozen["edges"]
                if e["source"] not in ids or e["target"] not in ids]
    assert not dangling, dangling[:5]


def test_the_focus_offsets_are_real_shopper_nodes(frozen):
    by_offset = {n["props"].get("offset"): n for n in frozen["nodes"]
                 if n["kind"] == "shopper"}
    assert len(frozen["focus"]) == 3
    for off in frozen["focus"]:
        assert off in by_offset, off
        assert by_offset[off]["props"]["focus"] is True


def test_the_three_are_mutually_trusting(frozen):
    """The exhibit's premise. If the triple is not a triangle it is not the
    picture the aside claims it is."""
    sids = [n["id"] for n in frozen["nodes"]
            if n["kind"] == "shopper" and n["props"].get("offset") in frozen["focus"]]
    trust = {(e["source"], e["target"]) for e in frozen["edges"]
             if e["rel"] == "TRUSTS_PERSON"}
    for a, b in itertools.permutations(sids, 2):
        assert (a, b) in trust, (a, b)


def test_the_social_proof_chain_is_present(frozen):
    """TRUSTS_PERSON -> BOUGHT -> EXPERIENCED, on the same product, by someone
    a focus shopper trusts — the one path this whole view exists to show."""
    trust = {(e["source"], e["target"]) for e in frozen["edges"]
             if e["rel"] == "TRUSTS_PERSON"}
    bought = {(e["source"], e["target"]) for e in frozen["edges"]
              if e["rel"] == "BOUGHT"}
    lived = {(e["source"], e["target"]) for e in frozen["edges"]
             if e["rel"] == "EXPERIENCED"}
    chains = [(a, b, p) for (a, b) in trust
              for (peer, p) in bought if peer == b and (b, p) in lived]
    assert chains, "no trusted peer both bought and took delivery of anything"


def test_every_trace_maps_to_a_focus_shopper_and_a_visible_stimulus(frozen):
    """Explain reads these by (offset, stimulus id); a key that matches nothing
    on screen is a silently dead tab."""
    node_ids = {n["id"] for n in frozen["nodes"]}
    assert set(frozen["traces"]) == {str(o) for o in frozen["focus"]}
    for offset, by_stim in frozen["traces"].items():
        assert by_stim, f"offset {offset} has no traces"
        for stim, trace in by_stim.items():
            assert int(stim) in node_ids, (offset, stim)
            assert isinstance(trace["motifs"], list)


def test_the_frozen_traces_carry_the_social_proof_motif(frozen):
    """With its required fields — the same ones C1 enforces on a live read."""
    motifs = [m for by_stim in frozen["traces"].values()
              for t in by_stim.values() for m in t["motifs"]
              if m["type"] == "social_proof"]
    assert motifs, "no social_proof motif survived the capture"
    for m in motifs:
        for field in ("valence", "peer_trust", "experience"):
            assert isinstance(m[field], (int, float)), (field, m)
        assert 0.0 <= m["valence"] <= 1.0
        shopper, rel, peer, rel2, product = m["path"]
        assert rel == "TRUSTS_PERSON" and rel2 == "BOUGHT"


def test_motif_paths_reference_nodes_that_are_on_screen(frozen):
    """explainMotifs looks each hop up against the rendered graph; a path whose
    endpoints are absent lights nothing and the tab looks broken."""
    node_ids = {n["id"] for n in frozen["nodes"]}
    missing = set()
    for by_stim in frozen["traces"].values():
        for trace in by_stim.values():
            for m in trace["motifs"]:
                for hop in m.get("path", []):
                    if isinstance(hop, int) and hop not in node_ids:
                        missing.add(hop)
    assert not missing, f"motif paths reference absent nodes: {sorted(missing)[:5]}"


def test_the_frozen_payload_matches_the_live_envelope(frozen):
    """The client types one shape for both paths, so the capture must carry
    every key a live /runs/{id}/memory-graph read carries."""
    for key in ("run_id", "run_index", "t0", "tick_seconds", "ticks",
                "head_tick", "social_enabled", "focus", "candidates",
                "nodes", "edges"):
        assert key in frozen, key
    for e in frozen["edges"]:
        assert e["time"] in ("static", "event", "bitemporal"), e["id"]
        assert e["versions"], e["id"]
