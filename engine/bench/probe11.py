"""Phase 1.1 hour-one probe (PLAN.md): the measurements that decide per-motif
routing (Route A = algo.SPpaths, Route B = single-hop reads + Python joins)
and validate the write-throughput budget. Output ends with a ready-to-paste
CONTRACT.md routing table.

Run:  cd engine && uv run python bench/probe11.py

Uses scratch ids in the 900_001_xxx block (outside every Appendix-A range);
cleans up after itself. Safe to re-run.
"""

from __future__ import annotations

import statistics
import time

from shopsim.hydramem import cypher, schema
from shopsim.hydramem.client import HydraClient

NOW = 1_755_300_000
SENT = schema.VALID_TO_SENTINEL

# scratch ids
SHOPPER = 900_001_001
PEER = 900_001_002
CONCEPT = 900_001_101  # stands in for a Concept node
CATEGORY = 900_001_102
BRAND = 900_001_103
PRODUCT = 900_001_201
CREATIVE_PAST = 900_001_301
CREATIVE_STIM = 900_001_302
PAGE = 900_001_401
BELIEF = 900_001_501

WRITE_BLOCK = 900_010_000  # throughput scratch: edges fan out from here


def _try(client: HydraClient, label: str, query: str, **params) -> tuple[bool, str]:
    try:
        client.run(query, **params)
        return True, ""
    except Exception as exc:
        return False, str(exc).split("\n")[0][:140]


def seed(c: HydraClient) -> None:
    stmts = [
        # preference_fit shape: shopper -PREFERS-> concept <-CLAIMS- creative(stim)
        cypher.create_edge("PREFERS", SHOPPER, CONCEPT, {
            "w": 0.61, "evidence": 2.85, "source": "learned", "cause_kind": "CLICKED",
            "cause_id": CREATIVE_PAST, "t": NOW - 86_400, "valid_to": SENT}, merge=True),
        cypher.create_edge("CLAIMS", CREATIVE_STIM, CONCEPT, {"strength": 0.9}, merge=True),
        cypher.create_edge("CLAIMS", CREATIVE_PAST, CONCEPT, {"strength": 0.8}, merge=True),
        # goal_fit shape: shopper -NEEDS-> category <-IN_CATEGORY- product <-OFFERS- creative
        cypher.create_edge("NEEDS", SHOPPER, CATEGORY, {
            "strength": 0.8, "budget_cap": 90.0, "deadline_t": NOW + 4 * 86_400,
            "t": NOW - 3600, "valid_to": SENT, "source": "seeded"}, merge=True),
        cypher.create_edge("IN_CATEGORY", PRODUCT, CATEGORY, merge=True),
        cypher.create_edge("OFFERS", CREATIVE_STIM, PRODUCT, {"claimed_pct": 0.15}, merge=True),
        # fatigue shape: shopper -SAW-> past creative; both creatives same brand
        cypher.create_edge("SAW", SHOPPER, CREATIVE_PAST, {"t": NOW - 2 * 86_400, "run": 0}),
        cypher.create_edge("PROMOTES", CREATIVE_PAST, BRAND, merge=True),
        cypher.create_edge("PROMOTES", CREATIVE_STIM, BRAND, merge=True),
        # violation shape: shopper -EXPECTS-> concept; page SHOWS nothing
        cypher.create_edge("EXPECTS", SHOPPER, CONCEPT, {
            "about": BRAND, "strength": 0.9, "t": NOW - 86_400, "valid_to": SENT,
            "cause_id": CREATIVE_PAST}, merge=True),
        # belief shape for M2/M4
        cypher.set_node_props("belief", BELIEF, {
            "value": 0.7, "evidence": 3.0, "about_id": BRAND, "that_id": schema.ASPECT_TRUST_ID,
            "t": NOW - 86_400, "valid_to": SENT}),
        cypher.create_edge("HOLDS", SHOPPER, BELIEF, {"t": NOW - 86_400, "valid_to": SENT}, merge=True),
        # social shape
        cypher.create_edge("TRUSTS_PERSON", SHOPPER, PEER, {"w": 0.7}, merge=True),
        cypher.create_edge("BOUGHT", PEER, PRODUCT, {"t": NOW - 86_400, "run": 0, "price": 39.0}),
    ]
    c.run_seq(stmts)


def cleanup(c: HydraClient) -> None:
    pairs = [
        ("PREFERS", SHOPPER, CONCEPT), ("CLAIMS", CREATIVE_STIM, CONCEPT),
        ("CLAIMS", CREATIVE_PAST, CONCEPT), ("NEEDS", SHOPPER, CATEGORY),
        ("IN_CATEGORY", PRODUCT, CATEGORY), ("OFFERS", CREATIVE_STIM, PRODUCT),
        ("SAW", SHOPPER, CREATIVE_PAST), ("PROMOTES", CREATIVE_PAST, BRAND),
        ("PROMOTES", CREATIVE_STIM, BRAND), ("EXPECTS", SHOPPER, CONCEPT),
        ("HOLDS", SHOPPER, BELIEF), ("TRUSTS_PERSON", SHOPPER, PEER),
        ("BOUGHT", PEER, PRODUCT),
    ]
    for rel, a, b in pairs:
        c.run_stmt(cypher.delete_edge(rel, a, b))
    # throughput scratch (batched delete needs both endpoints anchored)
    c.run_stmt(cypher.delete_edges_batch(
        "SAW", [(WRITE_BLOCK + i, WRITE_BLOCK + 100 + j)
                for i in range(64) for j in range(16)]))


def micro_probes(c: HydraClient) -> dict[str, tuple[bool, str]]:
    out: dict[str, tuple[bool, str]] = {}
    out["M1 multi-assign SET"] = _try(
        c, "M1", "MATCH (n {id: $id}) SET n.value = $v, n.evidence = $e",
        id=BELIEF, v=0.7, e=3.0)
    out["M2 dst node props via edge"] = _try(
        c, "M2",
        "MATCH (a {id: $a})-[e:HOLDS]->(x) WHERE e.valid_to > $now "
        "RETURN x.id AS dst, x.value AS value, x.evidence AS evidence",
        a=SHOPPER, now=NOW)
    out["M3 compound WHERE (AND)"] = _try(
        c, "M3",
        "MATCH (a {id: $a})-[e:EXPECTS]->(x) WHERE e.valid_to > $now AND e.about = $b "
        "RETURN x.id AS dst, e.strength AS strength",
        a=SHOPPER, now=NOW, b=BRAND)
    out["M4 WHERE on dst node prop"] = _try(
        c, "M4",
        "MATCH (a {id: $a})-[e:HOLDS]->(x) WHERE x.valid_to > $now RETURN x.id AS dst",
        a=SHOPPER, now=NOW)
    out["M5 ORDER BY t DESC LIMIT 1"] = _try(
        c, "M5",
        "MATCH (a {id: $a})-[e:SAW]->(x) RETURN x.id AS dst, e.t AS t ORDER BY e.t DESC LIMIT 1",
        a=SHOPPER)
    out["M6 EXPLAIN prefix"] = _try(
        c, "M6", "EXPLAIN MATCH (a {id: $a})-[e:SAW]->(x) RETURN x.id AS dst", a=SHOPPER)
    out["M7 aggregate count"] = _try(
        c, "M7", "MATCH (a {id: $a})-[e:SAW]->(x) RETURN count(x) AS n", a=SHOPPER)
    return out


def sppaths_probes(c: HydraClient) -> dict[str, tuple[bool, str]]:
    """(a) heterogeneous relTypes lists + direction semantics."""
    out: dict[str, tuple[bool, str]] = {}

    def call(label: str, a: int, b: int, types: list[str]) -> None:
        q = ("CALL algo.SPpaths({sourceNode: $a, targetNode: $b, "
             f"relTypes: {types!r}, maxLen: 4}}) YIELD path RETURN path")
        try:
            rows = c.run(q, a=a, b=b)
            out[label] = (True, f"{len(rows)} path(s)")
        except Exception as exc:
            out[label] = (False, str(exc).split("\n")[0][:140])

    call("A1 homogeneous fwd (SAW)", SHOPPER, CREATIVE_PAST, ["SAW"])
    # shopper -PREFERS-> concept <-CLAIMS- stim : needs a REVERSED second hop
    call("A2 hetero 2-type w/ reversal (PREFERS,CLAIMS)", SHOPPER, CREATIVE_STIM,
         ["PREFERS", "CLAIMS"])
    # shopper -NEEDS-> cat <-IN_CATEGORY- product <-OFFERS- stim : two reversed hops
    call("A3 hetero 3-type w/ reversals (NEEDS,IN_CATEGORY,OFFERS)", SHOPPER, CREATIVE_STIM,
         ["NEEDS", "IN_CATEGORY", "OFFERS"])
    # explicit direction check: source/target swapped on a directed edge
    call("A4 reverse direction (SAW, swapped ends)", CREATIVE_PAST, SHOPPER, ["SAW"])
    return out


def _time(fn, n: int) -> tuple[float, float]:
    """median, p95 in ms over n runs."""
    samples = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000)
    samples.sort()
    return statistics.median(samples), samples[int(0.95 * len(samples)) - 1]


def route_b_latency(c: HydraClient, n: int = 200) -> dict[str, tuple[float, float]]:
    """(b) Route B: the per-motif single-hop read sets, timed end-to-end
    (statements + the trivial Python join)."""
    out = {}

    def preference_fit():
        c.run_stmt(cypher.live_edges("PREFERS", SHOPPER, NOW, ("w", "evidence", "t")))
        # stimulus CLAIMS come from the per-tick stimulus cache in real reads

    def goal_fit():
        c.run_stmt(cypher.live_edges("NEEDS", SHOPPER, NOW,
                                     ("strength", "budget_cap", "deadline_t")))

    def fatigue():
        c.run_stmt(cypher.events_since("SAW", SHOPPER, NOW - 14 * 86_400, ("t",)))
        # past-creative CLAIMS/PROMOTES come from the objective cache

    def violation():
        c.run_stmt(cypher.live_edges("EXPECTS", SHOPPER, NOW, ("about", "strength")))

    out["preference_fit"] = _time(preference_fit, n)
    out["goal_fit"] = _time(goal_fit, n)
    out["brand_semantic_fatigue"] = _time(fatigue, n)
    out["expectation_violation"] = _time(violation, n)
    return out


def route_a_latency(c: HydraClient, n: int = 200) -> dict[str, tuple[float, float]]:
    """(b) Route A: one SPpaths call per motif shape (only meaningful if the
    heterogeneous probes pass)."""
    out = {}

    def pref():
        c.run_stmt(cypher.sppaths(SHOPPER, CREATIVE_STIM, ["PREFERS", "CLAIMS"]))

    def goal():
        c.run_stmt(cypher.sppaths(SHOPPER, CREATIVE_STIM, ["NEEDS", "IN_CATEGORY", "OFFERS"]))

    for label, fn in (("preference_fit", pref), ("goal_fit", goal)):
        try:
            out[label] = _time(fn, n)
        except Exception:
            out[label] = (float("nan"), float("nan"))
    return out


def batched_read_throughput(c: HydraClient) -> dict[str, float]:
    """(c) UNWIND adjacency batch vs per-row singles (rows/s)."""
    ids = [SHOPPER] * 200  # same source repeated: measures transport, not cache
    t0 = time.perf_counter()
    c.run_stmt(cypher.adj_batch("SAW", ids))
    batch_s = time.perf_counter() - t0

    t0 = time.perf_counter()
    for i in ids:
        c.run_stmt(cypher.events_since("SAW", i, 0, ("t",)))
    singles_s = time.perf_counter() - t0
    return {"adj_batch_200_rows_ms": batch_s * 1000,
            "singles_200_ms": singles_s * 1000,
            "singles_per_s": 200 / singles_s}


def write_throughput(c: HydraClient, n: int = 1000) -> dict[str, float]:
    """(d) prop-carrying edge CREATE singles/s, sequential vs grouped."""
    def stmts(base: int, count: int) -> list[cypher.Statement]:
        return [cypher.create_edge("SAW", WRITE_BLOCK + (base + i) % 64,
                                   WRITE_BLOCK + 100 + (base + i) % 16,
                                   {"t": NOW + base + i, "run": 0})
                for i in range(count)]

    t0 = time.perf_counter()
    c.run_seq(stmts(0, n))
    seq_s = time.perf_counter() - t0

    groups = {w: stmts(n + w * (n // 8), n // 8) for w in range(8)}
    t0 = time.perf_counter()
    c.run_grouped(groups)
    par_s = time.perf_counter() - t0
    return {"sequential_per_s": n / seq_s, "grouped8_per_s": n / par_s,
            "seq_ms_per_stmt": seq_s / n * 1000}


def main() -> None:
    c = HydraClient()
    print("== seeding scratch story shapes ==")
    seed(c)

    print("\n== micro-probes ==")
    micro = micro_probes(c)
    for label, (ok, msg) in micro.items():
        print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{msg}]" if msg else ""))

    print("\n== SPpaths probes (a) ==")
    spp = sppaths_probes(c)
    for label, (ok, msg) in spp.items():
        print(f"  {'PASS' if ok else 'FAIL'}  {label}  [{msg}]")

    print("\n== Route B latency (b) — median / p95 ms over 200 ==")
    rb = route_b_latency(c)
    for motif, (med, p95) in rb.items():
        print(f"  {motif:26s} {med:6.2f} / {p95:6.2f}")

    hetero_ok = spp.get("A2 hetero 2-type w/ reversal (PREFERS,CLAIMS)", (False, ""))[0]
    ra: dict[str, tuple[float, float]] = {}
    if hetero_ok:
        print("\n== Route A latency (b) — median / p95 ms over 200 ==")
        ra = route_a_latency(c)
        for motif, (med, p95) in ra.items():
            print(f"  {motif:26s} {med:6.2f} / {p95:6.2f}")
    else:
        print("\n== Route A latency skipped (heterogeneous SPpaths unavailable) ==")

    print("\n== batched read throughput (c) ==")
    for k, v in batched_read_throughput(c).items():
        print(f"  {k}: {v:.1f}")

    print("\n== write throughput (d) ==")
    wt = write_throughput(c)
    for k, v in wt.items():
        print(f"  {k}: {v:.1f}")
    need = 10_000 / max(wt["grouped8_per_s"], 1e-9)
    print(f"  -> projected 10k-event batch: {need:.1f}s (target <= 10s)")

    print("\n== cleanup ==")
    cleanup(c)
    c.close()

    print("\n== CONTRACT.md routing table (paste-ready) ==\n")
    def row(motif: str) -> str:
        med, p95 = rb[motif]
        a = ra.get(motif)
        a_txt = f"A available ({a[0]:.1f}ms med)" if a and a[0] == a[0] else "A n/a"
        return (f"| {motif} | B | {med:.1f}ms med / {p95:.1f}ms p95 single "
                f"(shopper-side statement; stimulus side cached) — {a_txt} |")
    for motif in ("preference_fit", "goal_fit", "brand_semantic_fatigue",
                  "expectation_violation"):
        print(row(motif))


if __name__ == "__main__":
    main()
