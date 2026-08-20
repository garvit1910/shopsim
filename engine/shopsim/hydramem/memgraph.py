"""Memory-graph exporter (Phase 5.9) — a shopper cohort's subgraph as nodes
and edges, for the dashboard's 04 Graph exhibit.

This is NOT a new retrieval path. It reads the same edges reads.py already
reads, through the same cypher templates, and it adds nothing the store does
not literally hold. What it adds is *shape*: reads.py collapses the graph into
C1 scalars and motifs, this hands back the topology so D3 can draw it. If a
node or an edge appears on screen, a row came out of HydraDB for it.

Bitemporality is EXPORTED, not resolved. Every edge carries its own `t` and
`valid_to` plus a `time` discipline, and the client filters
`t <= as_of < valid_to` — the same as-of pattern as reads.ObjectiveCache.build
and web/components/Inspector.tsx. One fetch then buys the whole day scrub with
no further round-trips.

Node typing (why it is not a pure id-range switch): shopper ids are
1_000_000 + run_index * 100_000, so from run_index 10 onward they run straight
through the creative/product/page blocks — offset 2 of run 44 is 5_400_002.
The shopper set is instead recovered exactly: per the schema catalog,
TRUSTS_PERSON is the ONLY relationship whose destination is a shopper, so
{focus} union {TRUSTS_PERSON destinations} is complete, and everything left
over classifies safely by range.
"""

from __future__ import annotations

from typing import Any, Iterable

from ..contracts.enums import Category, Concept
from ..contracts.ids import (
    BELIEF_BASE,
    BRAND_BASE,
    CATEGORY_MAX,
    CATEGORY_MIN,
    CONCEPT_MAX,
    CONCEPT_MIN,
    CREATIVE_BASE,
    PAGE_VARIANT_BASE,
    PRODUCT_BASE,
    shopper_offset,
)
from . import cypher, schema

# Shopper-rooted relationships, in the order the aside lists them. Props are
# taken straight from the schema catalog, so this can never drift out of sync
# with what cypher.py will accept.
SHOPPER_ROOTED: tuple[str, ...] = (
    "PREFERS",
    "NEEDS",
    "HABIT",
    "EXPECTS",
    "REFERENCE_PRICE",
    *schema.EPISODIC_EDGE_TYPES,
    "TRUSTS_PERSON",
)

_ASPECT_NAMES = {v: k for k, v in schema.ASPECT_IDS.items()}

# HydraDB admission control rejects an UNWIND batch above this many
# items ("client_query_batch_items ... exceeds limit 1024"), so every
# adj_batch probe is chunked.
ADJ_BATCH_MAX = 1_000

# Relationships whose destination is another shopper. Exactly one, and the
# node-typing argument above depends on it staying that way.
_SHOPPER_VALUED = tuple(schema.SOCIAL_EDGES)


def _family(rel: str) -> str:
    if rel in schema.EPISODIC_EDGE_TYPES:
        return "episodic"
    if rel in schema.SOCIAL_EDGES:
        return "social"
    if rel in schema.SUBJECTIVE_EDGES:
        return "subjective"
    if rel in schema.PREFERENCE_EDGES:
        return "preference"
    return "objective"


def _time_discipline(rel: str) -> str:
    """How the client must filter this edge for an as-of-day read."""
    if rel in schema.BITEMPORAL_EDGES:
        return "bitemporal"  # t <= as_of < valid_to
    if rel in schema.EPISODIC_EDGE_TYPES:
        return "event"  # t <= as_of
    return "static"  # always present (objective closure, TRUSTS_PERSON)


def node_kind(nid: int, shoppers: frozenset[int]) -> str:
    """Node family. `shoppers` must be the complete shopper set (see module
    docstring) — without it the ranges genuinely overlap."""
    if nid in shoppers:
        return "shopper"
    if nid >= BELIEF_BASE:
        return "belief"
    if nid >= PAGE_VARIANT_BASE:
        return "page"
    if nid >= PRODUCT_BASE:
        return "product"
    if nid >= CREATIVE_BASE:
        return "creative"
    if nid in _ASPECT_NAMES:
        return "aspect"
    if nid >= BRAND_BASE:
        return "brand"
    if CATEGORY_MIN <= nid <= CATEGORY_MAX:
        return "category"
    if CONCEPT_MIN <= nid <= CONCEPT_MAX:
        return "concept"
    return "anchor"


def _enum_name(enum_cls, nid: int) -> str | None:
    try:
        return enum_cls(nid).name.lower()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# read plans
# ---------------------------------------------------------------------------


def memory_graph_read_plan(shopper_id: int) -> list[tuple[str, cypher.Statement]]:
    """Every shopper-rooted edge, full history, props per the schema catalog.
    Full history (not `live_edges`) because the exhibit scrubs through days:
    liveness is a client-side filter over `t`/`valid_to`, which is also the
    only correct as-of read — `live_edges` alone would admit future-dated
    versions (reads.ObjectiveCache.build makes the same distinction for
    PRICED_AT)."""
    plan = [(rel, cypher.all_edges(rel, shopper_id, schema.ALL_EDGES[rel]))
            for rel in SHOPPER_ROOTED]
    plan.append(("HOLDS", cypher.holds_history(shopper_id)))
    plan.append(("props", cypher.node_props("shopper", shopper_id, ("segment_id",))))
    return plan


def belief_satellite_plan(belief_id: int) -> list[tuple[str, cypher.Statement]]:
    """ABOUT / THAT / DERIVED_FROM for one belief version. DERIVED_FROM is the
    provenance the inspector renders as a sentence; here it stays as edges so
    the cause is a visible hop in the picture."""
    return [
        ("ABOUT", cypher.all_edges("ABOUT", belief_id)),
        ("THAT", cypher.all_edges("THAT", belief_id)),
        ("DERIVED_FROM", cypher.all_edges(
            "DERIVED_FROM", belief_id, schema.ALL_EDGES["DERIVED_FROM"])),
    ]


def product_props_plan(product_id: int) -> tuple[str, cypher.Statement]:
    return ("props", cypher.node_props(
        "product", product_id, ("name", "list_price")))


def has_attr_plan(product_id: int) -> tuple[str, cypher.Statement]:
    return ("HAS_ATTR", cypher.all_edges("HAS_ATTR", product_id))


# ---------------------------------------------------------------------------
# assembly (pure — no client, unit-testable)
# ---------------------------------------------------------------------------


class _Accumulator:
    def __init__(self, shoppers: frozenset[int]):
        self.shoppers = shoppers
        self.nodes: dict[int, dict] = {}
        self.edges: dict[str, dict] = {}

    def node(self, nid: int, **extra) -> dict:
        n = self.nodes.get(nid)
        if n is None:
            n = {"id": nid, "kind": node_kind(nid, self.shoppers),
                 "label": None, "sub": None, "props": {}}
            self.nodes[nid] = n
        for k, v in extra.items():
            if v is None:
                continue
            if k == "props":
                n["props"].update(v)
            else:
                n[k] = v
        return n

    def edge(self, rel: str, src: int, dst: int, props: dict,
             *, owner: int | None = None, time: str | None = None) -> None:
        """One edge per (rel, source, target); every stored row lands in its
        `versions` list.

        Folding rather than emitting a row per statement matters twice over.
        Visually, three VISITED rows on the same page draw three identical
        arcs stacked on each other. Physically, d3.forceLink treats duplicate
        links as parallel springs, so a shopper who visited a page four times
        would be pulled toward it four times as hard — the layout would encode
        an artifact of the event log rather than the shape of the graph. The
        counts are not lost: they ride in `versions`, which is also what the
        day scrub reads (PREFERS supersessions and SAW occurrences filter
        identically, by t/valid_to)."""
        self.node(src)
        self.node(dst)
        key = f"{rel}:{src}:{dst}"
        version = {k: v for k, v in props.items() if v is not None}
        e = self.edges.get(key)
        if e is None:
            e = self.edges[key] = {
                "id": key,
                "source": src,
                "target": dst,
                "rel": rel,
                "family": _family(rel),
                "time": time or _time_discipline(rel),
                "derived": False,
                "owner": owner if owner is not None else src,
                "versions": [],
            }
        if version not in e["versions"]:
            e["versions"].append(version)


def assemble_memory_graph(
    *,
    focus_ids: Iterable[int],
    rows_by_shopper: dict[int, dict[str, list[dict]]],
    belief_rows: dict[int, dict[str, list[dict]]],
    peer_rows: dict[int, dict[str, list[dict]]],
    product_rows: dict[int, dict[str, list[dict]]],
    cache: Any,
    creative_names: dict[str, str] | None = None,
) -> dict:
    """Build {nodes, edges} from raw rows. Pure: `cache` only needs the
    reads.ObjectiveCache attribute surface (creatives, pages, product_brand,
    product_category, prices), so a plain stub satisfies it in tests."""
    focus = list(dict.fromkeys(int(f) for f in focus_ids))
    creative_names = creative_names or {}

    # The complete shopper set, per the module docstring: the focus plus every
    # TRUSTS_PERSON destination. Computed BEFORE any node is typed.
    shoppers = set(focus)
    for rows in rows_by_shopper.values():
        for rel in _SHOPPER_VALUED:
            shoppers.update(r["dst"] for r in rows.get(rel, ()))
    shoppers.update(peer_rows)
    acc = _Accumulator(frozenset(shoppers))
    belief_window: dict[int, dict] = {}

    # -- the people ---------------------------------------------------------
    for sid in shoppers:
        rows = rows_by_shopper.get(sid, {})
        props = (rows.get("props") or [{}])[0]
        acc.node(sid,
                 label=f"Shopper {shopper_offset(sid)}",
                 sub=f"#{shopper_offset(sid):04d}",
                 props={"offset": shopper_offset(sid),
                        "segment_id": props.get("segment_id"),
                        "focus": sid in focus,
                        "peer": sid not in focus})

    # -- each focus shopper's own edges -------------------------------------
    for sid in focus:
        rows = rows_by_shopper.get(sid, {})
        for rel in SHOPPER_ROOTED:
            for r in rows.get(rel, ()):
                acc.edge(rel, sid, r["dst"],
                         {k: v for k, v in r.items() if k != "dst"})
        # beliefs: HOLDS edge + the belief node's denormalized props
        for r in rows.get("HOLDS", ()):
            bid = r["dst"]
            belief_window[bid] = {"t": r.get("t"), "valid_to": r.get("valid_to")}
            acc.edge("HOLDS", sid, bid, {"t": r.get("t"), "valid_to": r.get("valid_to")})
            aspect = _ASPECT_NAMES.get(r.get("that_id"), str(r.get("that_id")))
            acc.node(bid, label=f"belief · {aspect}",
                     props={"value": r.get("value"), "evidence": r.get("evidence"),
                            "about_id": r.get("about_id"), "that_id": r.get("that_id"),
                            "aspect": aspect, "t": r.get("t"),
                            "valid_to": r.get("valid_to"), "holder": sid})

    # -- belief satellites: ABOUT / THAT / DERIVED_FROM ---------------------
    # A belief gets a FRESH node id per version, so a shopper who revised
    # their trust three times leaves three belief nodes behind. ABOUT/THAT/
    # DERIVED_FROM carry no time of their own, which would pin every retired
    # version on screen forever; they are stamped with the belief node's own
    # t/valid_to window instead, so a superseded version and its whole
    # provenance fan retire together when the day scrub moves past it.
    for bid, sat in belief_rows.items():
        window = belief_window.get(bid, {})
        for rel in ("ABOUT", "THAT", "DERIVED_FROM"):
            for r in sat.get(rel, ()):
                acc.edge(rel, bid, r["dst"],
                         {**{k: v for k, v in r.items() if k != "dst"}, **window},
                         time="bitemporal")

    # -- peer stubs: the friend's side of the social path -------------------
    # Only where the product is already on screen, which is what keeps a
    # degree-4 trust graph from dragging in the whole population.
    known_products = {nid for nid in acc.nodes
                      if node_kind(nid, acc.shoppers) == "product"}
    for peer, rows in peer_rows.items():
        if peer in focus:
            continue
        for name, rel in (("peer_bought", "BOUGHT"), ("peer_experienced", "EXPERIENCED")):
            for r in rows.get(name, ()):
                if r["dst"] not in known_products:
                    continue
                acc.edge(rel, peer, r["dst"],
                         {k: v for k, v in r.items() if k != "dst"})

    # -- reciprocal trust ---------------------------------------------------
    # seed_population writes TRUSTS_PERSON in BOTH directions (retrieval reads
    # outgoing edges only), so a mutual pair is two stored rows. Both are
    # exported — they are both really there, and Explain walks the directed
    # one — but the flag lets the canvas draw one arc per pair instead of two
    # arcs sitting on top of each other.
    for e in acc.edges.values():
        if e["rel"] != "TRUSTS_PERSON":
            continue
        e["reciprocal"] = f"TRUSTS_PERSON:{e['target']}:{e['source']}" in acc.edges

    # -- objective closure --------------------------------------------------
    # This is what makes a concept, brand or product that two shoppers both
    # touch ONE node rather than two copies: every creative/page/product on
    # screen is closed over its own objective edges, which are global.
    _close_objective(acc, cache, product_rows)

    # -- labels -------------------------------------------------------------
    for nid, n in acc.nodes.items():
        kind = n["kind"]
        if kind == "concept":
            n["label"] = _enum_name(Concept, nid) or f"concept {nid}"
        elif kind == "category":
            n["label"] = _enum_name(Category, nid) or f"category {nid}"
        elif kind == "brand":
            n["label"] = n["label"] or f"Brand {nid}"
        elif kind == "product":
            props = (product_rows.get(nid, {}).get("props") or [{}])[0]
            n["props"].update({k: v for k, v in props.items() if v is not None})
            n["label"] = props.get("name") or f"Product {nid}"
            n["sub"] = "product"
        elif kind == "creative":
            n["label"] = creative_names.get(str(nid)) or f"Ad {nid}"
            n["sub"] = "creative"
        elif kind == "page":
            n["label"] = f"Page {nid}"
            n["sub"] = "page variant"
        elif kind == "aspect":
            n["label"] = _ASPECT_NAMES.get(nid, f"aspect {nid}")
        elif kind == "anchor":
            n["label"] = f"anchor {nid}"

    for e in acc.edges.values():
        e["versions"].sort(key=lambda v: (v.get("t") is None, v.get("t", 0)))
        e["count"] = len(e["versions"])

    return {
        "nodes": sorted(acc.nodes.values(), key=lambda n: n["id"]),
        "edges": sorted(acc.edges.values(), key=lambda e: e["id"]),
    }


def _close_objective(acc: _Accumulator, cache: Any,
                     product_rows: dict[int, dict[str, list[dict]]]) -> None:
    """Two passes: creatives/pages first (they introduce products), then the
    products those brought in. Emitted through acc.edge, so every endpoint
    becomes a real node — a dangling edge would break the force layout."""
    for _ in range(2):
        for nid in list(acc.nodes):
            kind = node_kind(nid, acc.shoppers)
            if kind == "creative":
                meta = getattr(cache, "creatives", {}).get(nid)
                if meta is None:
                    continue
                for concept, strength in meta["claims"].items():
                    acc.edge("CLAIMS", nid, concept, {"strength": strength})
                for product, pct in meta["offers"].items():
                    acc.edge("OFFERS", nid, product, {"claimed_pct": pct})
                if meta.get("brand"):
                    acc.edge("PROMOTES", nid, meta["brand"], {})
            elif kind == "page":
                meta = getattr(cache, "pages", {}).get(nid)
                if meta is None:
                    continue
                for concept in meta["shows"]:
                    acc.edge("SHOWS", nid, concept, {})
                if meta.get("product"):
                    acc.edge("PAGE_FOR", nid, meta["product"], {})
            elif kind == "product":
                brand = getattr(cache, "product_brand", {}).get(nid)
                if brand:
                    acc.edge("SOLD_BY", nid, brand, {})
                category = getattr(cache, "product_category", {}).get(nid)
                if category:
                    acc.edge("IN_CATEGORY", nid, category, {})
                price = getattr(cache, "prices", {}).get(nid)
                if price is not None:
                    acc.node(nid, props={"price_now": price})
                # HAS_ATTR closes a product onto the concepts shoppers also
                # prefer — the most common place two worldviews meet.
                for r in product_rows.get(nid, {}).get("HAS_ATTR", ()):
                    acc.edge("HAS_ATTR", nid, r["dst"], {})


# ---------------------------------------------------------------------------
# triad discovery
# ---------------------------------------------------------------------------


def triangles(adj: dict[int, set[int]]) -> list[tuple[int, int, int]]:
    """Every mutually-trusting triple, deterministically ordered."""
    out = []
    for a in sorted(adj):
        for b in sorted(n for n in adj[a] if n > a):
            for c in sorted(n for n in adj.get(b, ()) if n > b and n in adj[a]):
                out.append((a, b, c))
    return out


def score_triad(triad: tuple[int, int, int], bought: dict[int, set[int]],
                experienced: dict[int, set[int]], degree: dict[int, int]
                ) -> tuple[int, int, int]:
    """Rank candidate triples for the exhibit. A triple is only worth drawing
    if it can actually SHOW the mechanism, so the first key counts members who
    both bought something and lived with it — that is the
    TRUSTS_PERSON -> BOUGHT -> EXPERIENCED path the social_proof motif walks.
    Ties break on purchases, then on total episodic degree."""
    lived = sum(1 for m in triad if bought.get(m) and experienced.get(m))
    buys = sum(len(bought.get(m, ())) for m in triad)
    return (lived, buys, sum(degree.get(m, 0) for m in triad))


def why_triad(triad: tuple[int, int, int], bought: dict[int, set[int]],
              experienced: dict[int, set[int]]) -> str:
    lived = [m for m in triad if bought.get(m) and experienced.get(m)]
    if lived:
        names = ", ".join(f"#{shopper_offset(m):04d}" for m in lived)
        return f"{names} bought and experienced — the social_proof path is live"
    if any(bought.get(m) for m in triad):
        return "a member bought, but no delivery landed inside the window"
    return "mutually trusting, but nobody in the triple bought anything"
