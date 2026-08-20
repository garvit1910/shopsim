"""HydraMem v3 — the real worldview store over HydraDB (Phase 1).

Facade over client/cypher/writes/reads. C1 freezes only
get_decision_context(shopper_id, stimulus_id); everything else here is
engine-internal (PLAN.md Phase 1). The C1 signature carries no clock, so the
engine drives time via set_tick() each tick (retrieval needs `now` for
liveness/windows and `tick_start` for as-of-previous-tick social reads).

The single admitted writer (constraint 8) is the engine process holding this
object: minds return EvidenceDeltas, the applier writes; the dashboard reads
only through these APIs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Mapping

from ..contracts.enums import EventType
from ..contracts.ids import IdAllocator, shopper_offset
from ..contracts.types import DecisionContext, Event, WorldviewSnapshot
from ..eventlog import JsonlEventLog
from . import cypher, memgraph, reads, schema, writes
from .client import HydraClient
from .config import HydraConfig

_ASPECT_NAMES = {schema.ASPECT_TRUST_ID: "trust", schema.ASPECT_QUALITY_ID: "quality"}

_KIND_NOUNS = {
    "SAW": ("exposure", "exposures"),
    "CLICKED": ("click", "clicks"),
    "VISITED": ("visit", "visits"),
    "BROWSED": ("browse", "browses"),
    "CARTED": ("cart add", "cart adds"),
    "BOUGHT": ("purchase", "purchases"),
    "EXPERIENCED": ("delivery", "deliveries"),
}


def _provenance_sentence(rows: list[dict]) -> str:
    parts = []
    for r in sorted(rows, key=lambda r: r["first_t"]):
        one, many = _KIND_NOUNS.get(r["kind"], (r["kind"].lower(), r["kind"].lower() + "s"))
        n = r["count"]
        parts.append(f"{n} {one if n == 1 else many}")
    if not parts:
        return "no recorded evidence"
    if len(parts) == 1:
        return "from " + parts[0]
    return "from " + ", ".join(parts[:-1]) + " and " + parts[-1]


class HydraMem:
    def __init__(
        self,
        client: HydraClient | None = None,
        *,
        run_index: int = 0,
        allocator: IdAllocator | None = None,
        event_log: JsonlEventLog | None = None,
        params: schema.RetrievalParams | None = None,
        validate: bool = True,
    ):
        self.client = client or HydraClient(HydraConfig.from_env())
        self.run_index = run_index
        self.allocator = allocator or IdAllocator(run_index)
        self.event_log = event_log
        self.params = params or schema.DEFAULT_PARAMS
        self.validate = validate
        self.cache = reads.ObjectiveCache(self.client)
        self._tick = 0
        self._now = 0
        self._tick_start = 0
        self._peer_cache: dict[int, dict[str, list[dict]]] = {}

    # -- clock --------------------------------------------------------------

    def set_tick(self, *, tick: int, now: int, tick_start: int | None = None) -> None:
        self._tick = tick
        self._now = now
        self._tick_start = tick_start if tick_start is not None else now
        self._peer_cache = {}
        self.cache._built_at = None  # rebuild lazily (PRICED_AT may have moved)

    # -- C1 read path -------------------------------------------------------

    def get_decision_context(self, shopper_id: int, stimulus_id: int) -> DecisionContext:
        return self.get_decision_contexts([shopper_id], stimulus_id)[shopper_id]

    def get_decision_contexts(
        self, shopper_ids: Iterable[int], stimulus_id: int
    ) -> dict[int, DecisionContext]:
        """Batched: stimulus/objective cache built once, per-shopper single
        sequences fanned across worker sessions, peers shared per tick."""
        shopper_ids = list(shopper_ids)
        self.cache.build(self._now)
        stim = self.cache.stimulus_view(stimulus_id)

        plans = {sid: reads.shopper_read_plan(sid, self._now, self.params, stim)
                 for sid in shopper_ids}
        results = self.client.run_grouped(
            {sid: [stmt for _, stmt in plan] for sid, plan in plans.items()})
        rows_by_shopper = {
            sid: {name: rows for (name, _), rows in zip(plans[sid], results[sid])}
            for sid in shopper_ids}

        peers = self._read_peers(
            {r["dst"] for rows in rows_by_shopper.values() for r in rows.get("trusts", ())})

        out: dict[int, DecisionContext] = {}
        for sid in shopper_ids:
            payload = reads.assemble_context(
                sid, rows_by_shopper[sid], stim, self.cache, peers,
                self._now, self._tick_start, self.params)
            # from_dict runs validate_context (C1 schema + Law-15 scan) on the
            # way out — every real context is checked at the boundary.
            out[sid] = DecisionContext.from_dict(payload)
        return out

    def _read_peers(self, peer_ids: set[int]) -> dict[int, dict[str, list[dict]]]:
        missing = [p for p in peer_ids if p not in self._peer_cache]
        if missing:
            plans = {p: reads.peer_read_plan(p) for p in missing}
            results = self.client.run_grouped(
                {p: [stmt for _, stmt in plan] for p, plan in plans.items()})
            for p in missing:
                self._peer_cache[p] = {
                    name: rows for (name, _), rows in zip(plans[p], results[p])}
        return self._peer_cache

    # -- trace + inspector (1.5) --------------------------------------------

    def get_trace(self, shopper_id: int, stimulus_id: int) -> dict:
        """All candidate paths (thresholds relaxed) + explanatory motifs."""
        self.cache.build(self._now)
        stim = self.cache.stimulus_view(stimulus_id)
        plan = reads.shopper_read_plan(shopper_id, self._now, self.params, stim)
        plan.append(("experienced_self",
                     cypher.all_edges("EXPERIENCED", shopper_id, ("t", "sat"))))
        results = self.client.run_seq([stmt for _, stmt in plan])
        rows = {name: r for (name, _), r in zip(plan, results)}
        peers = self._read_peers({r["dst"] for r in rows.get("trusts", ())})
        payload = reads.assemble_context(
            shopper_id, rows, stim, self.cache, peers,
            self._now, self._tick_start, self.params, trace=True)
        return {"shopper_id": shopper_id, "stimulus_id": stimulus_id,
                "scalars": payload["scalars"], "motifs": payload["motifs"]}

    def get_shopper_worldview(self, shopper_id: int) -> dict:
        c, now = self.client, self._now
        beliefs = []
        for row in c.run_stmt(cypher.live_holds(shopper_id, now)):
            derived = [
                {"kind": r["kind"], "target": r["dst"], "count": r["count"],
                 "first_t": r["first_t"], "last_t": r["last_t"], "weight": r["weight"]}
                for r in c.run_stmt(cypher.all_edges(
                    "DERIVED_FROM", row["dst"],
                    ("kind", "count", "first_t", "last_t", "weight")))]
            from ..contracts.evidence import confidence
            beliefs.append({
                "belief_id": row["dst"], "about_id": row["about_id"],
                "aspect": _ASPECT_NAMES.get(row["that_id"], str(row["that_id"])),
                "value": row["value"], "evidence": row["evidence"],
                "confidence": confidence(row["evidence"]),
                "provenance": derived,
                "provenance_sentence": _provenance_sentence(derived)})
        prefs = [
            {"concept": r["dst"], "w": r["w"], "evidence": r["evidence"],
             "source": r["source"], "cause_kind": r["cause_kind"],
             "cause_id": r["cause_id"], "t": r["t"]}
            for r in c.run_stmt(cypher.live_edges(
                "PREFERS", shopper_id, now,
                ("w", "evidence", "source", "cause_kind", "cause_id", "t")))]
        needs = [
            {"category": r["dst"], "strength": r["strength"],
             "budget_cap": r["budget_cap"], "deadline_t": r["deadline_t"],
             "source": r["source"]}
            for r in c.run_stmt(cypher.live_edges(
                "NEEDS", shopper_id, now,
                ("strength", "budget_cap", "deadline_t", "source")))]
        habits = [
            {"brand": r["dst"], "evidence": r["evidence"]}
            for r in c.run_stmt(cypher.live_edges("HABIT", shopper_id, now, ("evidence",)))]
        expects = [
            {"concept": r["dst"], "about": r["about"], "strength": r["strength"]}
            for r in c.run_stmt(cypher.live_edges(
                "EXPECTS", shopper_id, now, ("about", "strength")))]
        return {"shopper_id": shopper_id, "beliefs": beliefs, "preferences": prefs,
                "active_needs": needs, "habits": habits, "expects": expects}

    # -- memory graph (5.9) -------------------------------------------------

    def find_social_triads(self, *, probe_max: int = 2_000, limit: int = 8
                           ) -> list[dict]:
        """Mutually-trusting triples in this run, best-for-the-exhibit first.

        Three adj_batch statements and no population size: cypher.adj_batch is
        the one legal batch-read shape, and probing a fixed offset window
        returns rows only for shoppers that actually have edges. Empty when
        the run was built without population.social — the caller says so
        plainly rather than drawing nothing.
        """
        from ..contracts.ids import shopper_id as make_sid

        # HydraDB admission control caps an UNWIND batch at 1024 items
        # ("client_query_batch_items rejected ... exceeds limit 1024"), so the
        # offset window is walked in chunks.
        def chunks(upto: int):
            for i in range(0, upto, memgraph.ADJ_BATCH_MAX):
                yield [make_sid(self.run_index, off)
                       for off in range(i, min(i + memgraph.ADJ_BATCH_MAX, upto))]

        def adj(rel: str, sids: list[int]) -> dict[int, set[int]]:
            out: dict[int, set[int]] = {}
            for r in self.client.run_stmt(cypher.adj_batch(rel, sids)):
                out.setdefault(r["row.sid"], set()).add(r["x.id"])
            return out

        # Shopper offsets are allocated contiguously from 0, and the social
        # factory gives every shopper degree >= 1, so the first chunk with no
        # trust rows is past the end of the population. Walking until then
        # costs one statement for the common case and never silently truncates
        # a big population at an arbitrary window.
        trusts: dict[int, set[int]] = {}
        seen: list[int] = []
        for chunk in chunks(probe_max):
            got = adj("TRUSTS_PERSON", chunk)
            if not got:
                break
            trusts.update(got)
            seen += chunk
        if not trusts:
            return []

        bought: dict[int, set[int]] = {}
        experienced: dict[int, set[int]] = {}
        for i in range(0, len(seen), memgraph.ADJ_BATCH_MAX):
            part = seen[i:i + memgraph.ADJ_BATCH_MAX]
            bought.update(adj("BOUGHT", part))
            experienced.update(adj("EXPERIENCED", part))
        degree = {s: len(bought.get(s, ())) + len(experienced.get(s, ()))
                  for s in trusts}

        tris = memgraph.triangles(trusts)
        tris.sort(key=lambda t: (
            memgraph.score_triad(t, bought, experienced, degree), tuple(-x for x in t)),
            reverse=True)
        return [{"shopper_ids": list(t),
                 "offsets": [shopper_offset(m) for m in t],
                 "why": memgraph.why_triad(t, bought, experienced)}
                for t in tris[:limit]]

    def get_memory_graph(self, focus_ids: Iterable[int],
                         *, creative_names: Mapping[str, str] | None = None) -> dict:
        """{nodes, edges} for a shopper cohort, full edge history included so
        the client owns the as-of scrub (see memgraph's module docstring)."""
        focus = [int(f) for f in focus_ids]
        self.cache.build(self._now)

        plans = {sid: memgraph.memory_graph_read_plan(sid) for sid in focus}
        results = self.client.run_grouped(
            {sid: [stmt for _, stmt in plan] for sid, plan in plans.items()})
        rows_by_shopper = {
            sid: {name: rows for (name, _), rows in zip(plans[sid], results[sid])}
            for sid in focus}

        # peers: the friend's BOUGHT/EXPERIENCED, via the existing plan
        peer_ids = {r["dst"] for rows in rows_by_shopper.values()
                    for r in rows.get("TRUSTS_PERSON", ())} - set(focus)
        peer_rows = self._read_peers(peer_ids) if peer_ids else {}

        # belief satellites (ABOUT / THAT / DERIVED_FROM), one group per belief
        belief_ids = [r["dst"] for rows in rows_by_shopper.values()
                      for r in rows.get("HOLDS", ())]
        belief_rows: dict[int, dict[str, list[dict]]] = {}
        if belief_ids:
            bplans = {bid: memgraph.belief_satellite_plan(bid) for bid in belief_ids}
            bres = self.client.run_grouped(
                {bid: [stmt for _, stmt in plan] for bid, plan in bplans.items()})
            belief_rows = {
                bid: {name: rows for (name, _), rows in zip(bplans[bid], bres[bid])}
                for bid in belief_ids}

        # product node props + HAS_ATTR, for products anyone touched
        product_ids = sorted({
            r["dst"] for rows in rows_by_shopper.values()
            for rel in ("BOUGHT", "CARTED", "ABANDONED", "PRICE_SEEN",
                        "EXPERIENCED", "REFERENCE_PRICE")
            for r in rows.get(rel, ())
        } | {r["dst"] for rows in peer_rows.values()
             for name in ("peer_bought", "peer_experienced")
             for r in rows.get(name, ())}
          | set(self.cache.product_brand))
        product_rows: dict[int, dict[str, list[dict]]] = {}
        if product_ids:
            pplans = {pid: [memgraph.product_props_plan(pid),
                            memgraph.has_attr_plan(pid)] for pid in product_ids}
            pres = self.client.run_grouped(
                {pid: [stmt for _, stmt in plan] for pid, plan in pplans.items()})
            product_rows = {
                pid: {name: rows for (name, _), rows in zip(pplans[pid], pres[pid])}
                for pid in product_ids}

        return memgraph.assemble_memory_graph(
            focus_ids=focus, rows_by_shopper=rows_by_shopper,
            belief_rows=belief_rows, peer_rows=peer_rows,
            product_rows=product_rows, cache=self.cache,
            creative_names=dict(creative_names or {}))

    def get_preference_history(self, shopper_id: int, concept_id: int) -> list[dict]:
        """The full supersession chain with receipts — the UI timeline."""
        rows = self.client.run_stmt(cypher.edge_history(
            "PREFERS", shopper_id, concept_id,
            ("w", "evidence", "source", "cause_kind", "cause_id", "t", "valid_to")))
        rows.sort(key=lambda r: (r["t"], r["valid_to"]))
        return rows

    def get_belief_history(self, shopper_id: int) -> list[dict]:
        """All belief versions ever held (as-of-T reads filter client-side)."""
        rows = self.client.run_stmt(cypher.holds_history(shopper_id))
        rows.sort(key=lambda r: r["t"])
        return rows

    # -- write path ---------------------------------------------------------

    def ingest_catalog(self, demo_brand_dir: Path | str, now: int = 0,
                       include_stimuli: bool = True) -> int:
        n = writes.ingest_catalog(self.client, demo_brand_dir, now,
                                  include_stimuli=include_stimuli)
        self.cache._built_at = None
        return n

    def record_events(self, events: list[Event]) -> int:
        return writes.record_events(self.client, events, self.event_log)

    def apply_deltas(
        self, per_shopper: dict[int, list[writes.OrderedDelta]],
        promotes: Mapping[int, int] | None = None,
    ) -> writes.ApplyReport:
        self.cache.build(self._now)
        return writes.apply_deltas(
            self.client, self.allocator, per_shopper, self._now,
            promotes if promotes is not None else self.cache.promotes)

    def snapshot_worldview(self, shopper_id: int) -> WorldviewSnapshot:
        return writes.snapshot_worldview(self.client, shopper_id, self._now)

    def supersede(self, rel: str, a: int, b: int, *,
                  cause_kind: str | EventType | None = None,
                  cause_id: int | None = None) -> None:
        ck = cause_kind.value if isinstance(cause_kind, EventType) else cause_kind
        writes.supersede(self.client, rel, a, b, self._now,
                         cause_kind=ck, cause_id=cause_id)

    def seed_preference(self, shopper_id: int, concept_id: int, w: float,
                        t: int | None = None) -> None:
        writes.seed_preference(self.client, shopper_id, concept_id, w,
                               self._now if t is None else t)

    def close(self) -> None:
        self.client.close()
