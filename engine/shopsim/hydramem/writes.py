"""Write path: catalog ingestion, episodic events, supersession helpers,
belief versioning, and the EvidenceDelta applier (Law 14).

Delta-kind conventions (EvidenceDeltaKey.kind is a plain str in C2, so new
kinds are contract-compatible; flag additions to Garvit):

    "edge"          PREFERS      subject=shopper, object=concept  (C2 legacy name)
    "belief"        trust Belief subject=shopper, object=brand
    "belief:quality" quality Belief (P1), same shape
    "expects"       EXPECTS      subject=shopper, object=concept; the brand is
                    resolved from the causing creative's PROMOTES edge;
                    applied as alpha-smoothing with alpha = delta.weight
    "ref_price"     REFERENCE_PRICE subject=shopper, object=product;
                    applied via evidence.smooth_reference_price
    "need_satisfy"  NEEDS supersede-with-cause, subject=shopper, object=category
    "habit"         HABIT (P1)   subject=shopper, object=brand; E += weight

Law 14 bounds: |dw| < EPSILON writes are skipped but their evidence still
accumulates into the next written version within the tick (re-base on the
pending fold state); at most MAX_SUBJECTIVE_WRITES_PER_TICK writes per
shopper, lowest priority truncated first. Canonical order (t, event_rank)
within a shopper; shoppers are disjoint subgraphs, so cross-shopper writes
run in parallel (client.run_grouped).
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from ..contracts import evidence
from ..contracts.enums import EventType
from ..contracts.ids import IdAllocator
from ..contracts.types import Event, EvidenceDelta, WorldviewSnapshot
from ..eventlog import JsonlEventLog
from . import cypher, schema
from .client import HydraClient, Statement

SENT = schema.VALID_TO_SENTINEL

# priority per Law 14 (evidence.WRITE_PRIORITY) + the unranked kinds after
_KIND_PRIORITY = {
    "need_satisfy": 0,
    "belief": 1,
    "belief:quality": 1,
    "edge": 2,  # PREFERS
    "expects": 3,
    "ref_price": 4,
    "habit": 5,
}

_ASPECT_FOR_KIND = {"belief": schema.ASPECT_TRUST_ID, "belief:quality": schema.ASPECT_QUALITY_ID}


# ---------------------------------------------------------------------------
# catalog ingestion
# ---------------------------------------------------------------------------


def ingest_catalog(
    client: HydraClient, demo_brand_dir: Path | str, now: int = 0,
    include_stimuli: bool = True,
) -> int:
    """Products, categories, attributes, creatives, pages + the latent table
    (latent props written by the single sanctioned template, Law 15).
    Idempotent: MERGE for edges, SET for node props. Returns statement count.

    include_stimuli=False (Phase 2.2, CONTRACT v3.2 note): skip the authored
    creative/page stimulus edges (CLAIMS/PROMOTES/OFFERS/SHOWS/PAGE_FOR) —
    engine runs write those from the perception cache instead
    (shopsim.perception.writer.write_stimuli); catalog truth (products,
    categories, HAS_ATTR, prices, latent) always comes from here."""
    d = Path(demo_brand_dir)
    stmts: list[Statement] = []

    product_brand: dict[int, int] = {}
    with open(d / "catalog.csv", newline="") as fh:
        for row in csv.DictReader(fh):
            pid = int(row["product_id"])
            brand = int(row["brand_id"])
            product_brand[pid] = brand
            stmts.append(cypher.set_node_props("product", pid, {
                "name": row["name"], "list_price": float(row["list_price"])}))
            stmts.append(cypher.create_edge("LISTS", schema.CATALOG_ID, pid, merge=True))
            stmts.append(cypher.create_edge("SOLD_BY", pid, brand, merge=True))
            stmts.append(cypher.create_edge("IN_CATEGORY", pid, int(row["category_id"]), merge=True))
            for cid in row["attr_concept_ids"].split("|"):
                stmts.append(cypher.create_edge("HAS_ATTR", pid, int(cid), merge=True))
            stmts.append(cypher.create_edge("PRICED_AT", pid, schema.PRICEBOOK_ID, {
                "price": float(row["list_price"]), "t": now, "valid_to": SENT}, merge=True))

    with open(d / "latent_quality.csv", newline="") as fh:
        for row in csv.DictReader(fh):
            stmts.append(cypher.ingest_latent_props(
                int(row["product_id"]), float(row["latent_quality"]),
                float(row["ship_reliability"])))

    if include_stimuli:
        creatives = json.loads((d / "creatives.json").read_text())["creatives"]
        for cr in creatives:
            cid = cr["creative_id"]
            stmts.append(cypher.set_node_props("creative", cid, {"brand_id": cr["brand_id"]}))
            stmts.append(cypher.create_edge("LISTS", schema.CATALOG_ID, cid, merge=True))
            stmts.append(cypher.create_edge("PROMOTES", cid, cr["brand_id"], merge=True))
            for claim in cr["claims"]:
                stmts.append(cypher.create_edge("CLAIMS", cid, claim["concept_id"],
                                                {"strength": claim["strength"]}, merge=True))
            for offer in cr["offers"]:
                stmts.append(cypher.create_edge("OFFERS", cid, offer["product_id"],
                                                {"claimed_pct": offer["claimed_pct"]}, merge=True))

        pages = json.loads((d / "page_variants.json").read_text())["page_variants"]
        for pg in pages:
            pgid = pg["page_id"]
            prod = pg["product_id"]
            stmts.append(cypher.set_node_props("page", pgid, {
                "brand_id": product_brand.get(prod, 0), "product_id": prod}))
            stmts.append(cypher.create_edge("LISTS", schema.CATALOG_ID, pgid, merge=True))
            stmts.append(cypher.create_edge("PAGE_FOR", pgid, prod, merge=True))
            for cid in pg["shows_concept_ids"]:
                stmts.append(cypher.create_edge("SHOWS", pgid, cid, merge=True))

    client.run_seq(stmts)
    return len(stmts)


# ---------------------------------------------------------------------------
# episodic events
# ---------------------------------------------------------------------------


def record_events(
    client: HydraClient, events: list[Event], event_log: JsonlEventLog | None = None
) -> int:
    """JSONL append first (write-ahead), then one CREATE single per episodic
    edge, grouped by shopper for parallel commit. NEED_* records are log-only
    (the NEEDS lifecycle lives as supersessions). Returns edges written."""
    if event_log is not None:
        for e in events:
            event_log.append_event(e)
        event_log.flush()

    groups: dict[int, list[Statement]] = {}
    n = 0
    for e in events:
        rel = e.type.value
        if rel not in schema.EPISODIC_EDGE_TYPES:
            continue  # log-only record
        allowed = schema.EPISODIC_EDGE_TYPES[rel]
        props = {"t": e.t, "run": e.run}
        for k, v in e.props:
            if k in allowed:
                props[k] = v
        groups.setdefault(e.shopper_id, []).append(
            cypher.create_edge(rel, e.shopper_id, e.subject, props))
        n += 1
    client.run_grouped(groups)
    return n


def supersede(
    client: HydraClient,
    rel: str,
    a: int,
    b: int,
    now: int,
    *,
    cause_kind: str | None = None,
    cause_id: int | None = None,
) -> None:
    """Close the live (a)-[rel]->(b) edge; the closed edge with its timestamps
    (and optional cause receipt) IS the record — no re-create."""
    extra: dict = {}
    if cause_kind is not None:
        extra["closed_cause_kind"] = cause_kind
        extra["closed_cause_id"] = cause_id if cause_id is not None else 0
    client.run_stmt(cypher.supersede_edge(rel, a, b, now, extra))


# ---------------------------------------------------------------------------
# worldview reads the applier needs (ids included — the C2 snapshot lacks them)
# ---------------------------------------------------------------------------


@dataclass
class _BeliefRow:
    belief_id: int
    about_id: int
    that_id: int
    value: float
    evidence: float


@dataclass
class _WorldviewState:
    """Live worldview with graph ids, per shopper. The fold mutates this."""

    prefs: dict[int, tuple[float, float]] = field(default_factory=dict)  # concept -> (w, E)
    pref_live: set[int] = field(default_factory=set)  # concepts with a live PREFERS edge
    beliefs: dict[tuple[int, int], _BeliefRow] = field(default_factory=dict)  # (about, that)
    expects: dict[tuple[int, int], float] = field(default_factory=dict)  # (concept, about) -> strength
    ref_price: dict[int, float] = field(default_factory=dict)  # product -> price
    needs: dict[int, tuple[float, float]] = field(default_factory=dict)  # category -> (strength, deadline)
    derived_from: dict[int, list[dict]] = field(default_factory=dict)  # belief_id -> rows


def _read_worldview(client: HydraClient, shopper_id: int, now: int) -> _WorldviewState:
    st = _WorldviewState()
    for row in client.run_stmt(cypher.live_edges("PREFERS", shopper_id, now, ("w", "evidence"))):
        st.prefs[row["dst"]] = (row["w"], row["evidence"])
        st.pref_live.add(row["dst"])
    for row in client.run_stmt(cypher.live_holds(shopper_id, now)):
        b = _BeliefRow(row["dst"], row["about_id"], row["that_id"], row["value"], row["evidence"])
        st.beliefs[(b.about_id, b.that_id)] = b
    for row in client.run_stmt(cypher.live_edges("EXPECTS", shopper_id, now, ("about", "strength"))):
        st.expects[(row["dst"], row["about"])] = row["strength"]
    for row in client.run_stmt(cypher.live_edges("REFERENCE_PRICE", shopper_id, now, ("price",))):
        st.ref_price[row["dst"]] = row["price"]
    for row in client.run_stmt(cypher.live_edges("NEEDS", shopper_id, now,
                                                 ("strength", "deadline_t"))):
        st.needs[row["dst"]] = (row["strength"], row["deadline_t"])
    return st


def snapshot_worldview(client: HydraClient, shopper_id: int, now: int) -> WorldviewSnapshot:
    """The frozen C2 snapshot handed to consolidate()."""
    st = _read_worldview(client, shopper_id, now)
    return WorldviewSnapshot(
        prefs=tuple((c, w, e) for c, (w, e) in sorted(st.prefs.items())),
        beliefs=tuple(
            (b.about_id, b.that_id, b.value, b.evidence)
            for b in sorted(st.beliefs.values(), key=lambda b: b.belief_id)
        ),
        expects=tuple((about, c, s) for (c, about), s in sorted(st.expects.items())),
        reference_price=tuple(sorted(st.ref_price.items())),
        active_needs=tuple((c, s, d) for c, (s, d) in sorted(st.needs.items())),
    )


# ---------------------------------------------------------------------------
# preference seeding (personas: priors as PREFERS edges, E0 = 2)
# ---------------------------------------------------------------------------


def seed_preference(
    client: HydraClient, shopper_id: int, concept_id: int, w: float, t: int,
    evidence_e: float = evidence.PRIOR_E0,
) -> None:
    client.run_stmt(cypher.create_edge("PREFERS", shopper_id, concept_id, {
        "w": w, "evidence": evidence_e, "source": "prior", "cause_kind": "SEED",
        "cause_id": 0, "t": t, "valid_to": SENT}, merge=True))


# ---------------------------------------------------------------------------
# the EvidenceDelta applier
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OrderedDelta:
    t: int
    event_rank: int
    delta: EvidenceDelta


@dataclass
class ApplyReport:
    written: dict[str, int] = field(default_factory=dict)
    skipped_epsilon: int = 0
    dropped_cap: int = 0

    def _bump(self, kind: str) -> None:
        self.written[kind] = self.written.get(kind, 0) + 1


@dataclass
class _PendingWrite:
    priority: int
    order: tuple[int, int]  # (t, event_rank)
    kind: str
    stmts_fn: object  # () -> list[Statement]


def _belief_version_stmts(
    shopper_id: int,
    old: _BeliefRow | None,
    new_id: int,
    about_id: int,
    that_id: int,
    value: float,
    e: float,
    t: int,
    derived_rows: list[dict],
) -> list[Statement]:
    """The client-sequenced belief supersession (old closed before new opened,
    for crash sanity). derived_rows are the NEW version's complete
    DERIVED_FROM rows (carry-forward + trigger row already folded)."""
    stmts: list[Statement] = []
    if old is not None:
        stmts.append(cypher.close_belief_node(old.belief_id, t))
        stmts.append(cypher.supersede_edge("HOLDS", shopper_id, old.belief_id, t))
    stmts.append(cypher.set_node_props("belief", new_id, {
        "value": value, "evidence": e, "about_id": about_id, "that_id": that_id,
        "t": t, "valid_to": SENT}))
    stmts.append(cypher.create_edge("HOLDS", shopper_id, new_id, {"t": t, "valid_to": SENT}))
    stmts.append(cypher.create_edge("ABOUT", new_id, about_id))
    stmts.append(cypher.create_edge("THAT", new_id, that_id))
    for row in derived_rows:
        stmts.append(cypher.create_edge("DERIVED_FROM", new_id, row["target"], {
            "kind": row["kind"], "count": row["count"], "first_t": row["first_t"],
            "last_t": row["last_t"], "weight": row["weight"]}))
    return stmts


def _fold_derived(rows: list[dict], kind: str, target: int, t: int, weight: float) -> list[dict]:
    out = [dict(r) for r in rows]
    for r in out:
        if r["kind"] == kind and r["target"] == target:
            r["count"] += 1
            r["last_t"] = t
            r["weight"] += weight
            return out
    out.append({"kind": kind, "target": target, "count": 1, "first_t": t,
                "last_t": t, "weight": weight})
    return out


class DeltaApplier:
    """Applies per-shopper EvidenceDelta lists. Two phases per call:
    grouped reads (worldview state + DERIVED_FROM provenance), then grouped
    writes — strictly ordered within each shopper, parallel across."""

    def __init__(self, client: HydraClient, allocator: IdAllocator,
                 promotes: Mapping[int, int] | None = None):
        self.client = client
        self.allocator = allocator
        self._promotes: dict[int, int] = dict(promotes or {})

    def _brand_for_creative(self, creative_id: int) -> int:
        if creative_id not in self._promotes:
            rows = self.client.run_stmt(cypher.all_edges("PROMOTES", creative_id))
            self._promotes[creative_id] = rows[0]["dst"] if rows else 0
        return self._promotes[creative_id]

    def apply(self, per_shopper: dict[int, list[OrderedDelta]], now: int) -> ApplyReport:
        report = ApplyReport()
        write_groups: dict[int, list[Statement]] = {}

        for shopper_id, deltas in sorted(per_shopper.items()):
            stmts = self._plan_shopper(shopper_id, deltas, now, report)
            if stmts:
                write_groups[shopper_id] = stmts
        self.client.run_grouped(write_groups)
        return report

    # -- per-shopper planning (pure fold + statement emission) --------------

    def _plan_shopper(
        self, shopper_id: int, deltas: list[OrderedDelta], now: int, report: ApplyReport
    ) -> list[Statement]:
        st = _read_worldview(self.client, shopper_id, now)
        # provenance rows for beliefs that may version this tick
        for od in deltas:
            if od.delta.key.kind in _ASPECT_FOR_KIND:
                aspect = _ASPECT_FOR_KIND[od.delta.key.kind]
                row = st.beliefs.get((od.delta.key.object, aspect))
                if row is not None and row.belief_id not in st.derived_from:
                    st.derived_from[row.belief_id] = [
                        dict(r, target=r.pop("dst"))
                        for r in self.client.run_stmt(cypher.all_edges(
                            "DERIVED_FROM", row.belief_id,
                            ("kind", "count", "first_t", "last_t", "weight")))
                    ]

        pending: list[_PendingWrite] = []
        for od in sorted(deltas, key=lambda o: (o.t, o.event_rank)):
            w = self._fold_one(shopper_id, st, od, report)
            if w is not None:
                pending.append(w)

        # Law 14 cap: keep the MAX highest-priority writes, then restore
        # canonical (t, event_rank) order for execution.
        pending.sort(key=lambda p: (p.priority, p.order))
        kept = pending[: evidence.MAX_SUBJECTIVE_WRITES_PER_TICK]
        report.dropped_cap += len(pending) - len(kept)
        kept.sort(key=lambda p: p.order)
        stmts: list[Statement] = []
        for p in kept:
            report._bump(p.kind)
            stmts.extend(p.stmts_fn())  # type: ignore[operator]
        return stmts

    def _fold_one(
        self, shopper_id: int, st: _WorldviewState, od: OrderedDelta, report: ApplyReport
    ) -> _PendingWrite | None:
        d = od.delta
        kind = d.key.kind
        t, rank = od.t, od.event_rank
        order = (t, rank)

        if kind == "edge":  # PREFERS
            concept = d.key.object
            w0, e0 = st.prefs.get(concept, (0.0, 0.0))
            w1, e1 = evidence.blend(w0, e0, d.target, d.weight)
            st.prefs[concept] = (w1, e1)
            if abs(w1 - w0) < evidence.EPSILON and e0 > 0:
                report.skipped_epsilon += 1
                return None
            had_live = concept in st.pref_live
            st.pref_live.add(concept)
            props = {"w": w1, "evidence": e1, "source": "learned",
                     "cause_kind": d.cause_kind.value, "cause_id": d.cause_id,
                     "t": t, "valid_to": SENT}

            def stmts(had_live=had_live, props=props, concept=concept, t=t):
                out = []
                if had_live:
                    out.append(cypher.supersede_edge("PREFERS", shopper_id, concept, t))
                out.append(cypher.create_edge("PREFERS", shopper_id, concept, props))
                return out

            return _PendingWrite(_KIND_PRIORITY[kind], order, kind, stmts)

        if kind in _ASPECT_FOR_KIND:  # trust / quality belief
            aspect = _ASPECT_FOR_KIND[kind]
            brand = d.key.object
            old = st.beliefs.get((brand, aspect))
            v0, e0 = (old.value, old.evidence) if old else (0.0, 0.0)
            v1, e1 = evidence.blend(v0, e0, d.target, d.weight)
            old_rows = st.derived_from.get(old.belief_id, []) if old else []
            new_rows = _fold_derived(old_rows, d.cause_kind.value, d.cause_id, t, d.weight)
            new_id = self.allocator.next_belief()
            # fold state forward so chained deltas re-base on this version
            st.beliefs[(brand, aspect)] = _BeliefRow(new_id, brand, aspect, v1, e1)
            st.derived_from[new_id] = new_rows
            if old is not None and abs(v1 - v0) < evidence.EPSILON:
                report.skipped_epsilon += 1
                return None

            def stmts(old=old, new_id=new_id, brand=brand, aspect=aspect,
                      v1=v1, e1=e1, t=t, new_rows=new_rows):
                return _belief_version_stmts(
                    shopper_id, old, new_id, brand, aspect, v1, e1, t, new_rows)

            return _PendingWrite(_KIND_PRIORITY[kind], order, kind, stmts)

        if kind == "expects":
            concept = d.key.object
            about = self._brand_for_creative(d.cause_id)
            key = (concept, about)
            s0 = st.expects.get(key, 0.0)
            # alpha-smoothing with alpha = delta.weight (Appendix F: "at weight 0.2")
            s1 = (1 - d.weight) * s0 + d.weight * d.target
            had_live = key in st.expects
            st.expects[key] = s1
            if had_live and abs(s1 - s0) < evidence.EPSILON:
                report.skipped_epsilon += 1
                return None

            def stmts(concept=concept, about=about, s1=s1, t=t, had_live=had_live,
                      cause_id=d.cause_id):
                out = []
                if had_live:
                    out.append(cypher.supersede_expects(shopper_id, concept, about, t))
                out.append(cypher.create_edge("EXPECTS", shopper_id, concept, {
                    "about": about, "strength": s1, "t": t, "valid_to": SENT,
                    "cause_id": cause_id}))
                return out

            return _PendingWrite(_KIND_PRIORITY[kind], order, kind, stmts)

        if kind == "ref_price":
            product = d.key.object
            old_p = st.ref_price.get(product)
            new_p = d.target if old_p is None else evidence.smooth_reference_price(old_p, d.target)
            had_live = old_p is not None
            st.ref_price[product] = new_p

            def stmts(product=product, new_p=new_p, t=t, had_live=had_live):
                out = []
                if had_live:
                    out.append(cypher.supersede_edge("REFERENCE_PRICE", shopper_id, product, t))
                out.append(cypher.create_edge("REFERENCE_PRICE", shopper_id, product, {
                    "price": new_p, "t": t, "valid_to": SENT}))
                return out

            return _PendingWrite(_KIND_PRIORITY[kind], order, kind, stmts)

        if kind == "need_satisfy":
            category = d.key.object
            if category not in st.needs:
                return None  # no live need to satisfy
            del st.needs[category]

            def stmts(category=category, t=t, ck=d.cause_kind.value, cid=d.cause_id):
                return [cypher.supersede_edge("NEEDS", shopper_id, category, t, {
                    "closed_cause_kind": ck, "closed_cause_id": cid})]

            return _PendingWrite(_KIND_PRIORITY[kind], order, kind, stmts)

        if kind == "habit":  # P1
            brand = d.key.object
            rows = self.client.run_stmt(cypher.live_edges("HABIT", shopper_id, now=od.t,
                                                          edge_props=("evidence",)))
            cur = {r["dst"]: r["evidence"] for r in rows}
            e1 = cur.get(brand, 0.0) + d.weight
            had_live = brand in cur

            def stmts(brand=brand, e1=e1, t=t, had_live=had_live):
                out = []
                if had_live:
                    out.append(cypher.supersede_edge("HABIT", shopper_id, brand, t))
                out.append(cypher.create_edge("HABIT", shopper_id, brand, {
                    "evidence": e1, "t": t, "valid_to": SENT}))
                return out

            return _PendingWrite(_KIND_PRIORITY[kind], order, kind, stmts)

        raise ValueError(f"unknown EvidenceDelta kind {kind!r}")


def apply_deltas(
    client: HydraClient,
    allocator: IdAllocator,
    per_shopper: dict[int, list[OrderedDelta]],
    now: int,
    promotes: Mapping[int, int] | None = None,
) -> ApplyReport:
    return DeltaApplier(client, allocator, promotes).apply(per_shopper, now)
