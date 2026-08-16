"""Every Cypher statement in the system (decision 10: all Cypher lives inside
HydraMem). Builders return (query, params) Statements for client.py.

Rel types and property names are interpolated ONLY after validation against
schema.py's whitelists; all values travel as Bolt parameters. Reads project
explicit properties — never whole nodes — so nothing outside a whitelist can
leak into a payload.

Law 15: `latent_quality` / `ship_reliability` appear in exactly one template
(INGEST_LATENT_PROPS, a write). No read template may name them; the node-prop
whitelists in schema.py exclude them, and a source-scan unit test pins this.

Verified-shape notes (infra/README.md):
- writes are single statements; no MATCH...CREATE / MERGE...SET compounds
- edge CREATE/MERGE is one-hop, anchored on ids, inline props OK
- supersede = MATCH ...-[e:REL]->... WHERE e.valid_to > $now SET e.valid_to = $now
- UNWIND batch reads return adjacency only (row field + destination id)
- SPpaths is bare-CALL only
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from .client import Statement
from . import schema


class CypherTemplateError(ValueError):
    pass


def _check_rel(rel: str) -> tuple[str, ...]:
    try:
        return schema.ALL_EDGES[rel]
    except KeyError:
        raise CypherTemplateError(f"unknown relationship type {rel!r}") from None


def _check_edge_props(rel: str, props: Iterable[str]) -> None:
    allowed = _check_rel(rel)
    bad = [p for p in props if p not in allowed]
    if bad:
        raise CypherTemplateError(f"props {bad} not allowed on :{rel} (allowed: {allowed})")


def _check_node_props(family: str, props: Iterable[str]) -> None:
    try:
        allowed = schema.NODE_PROPS[family]
    except KeyError:
        raise CypherTemplateError(f"unknown node family {family!r}") from None
    bad = [p for p in props if p not in allowed]
    if bad:
        raise CypherTemplateError(f"props {bad} not allowed on {family} nodes (allowed: {allowed})")


# ---------------------------------------------------------------------------
# writes
# ---------------------------------------------------------------------------


def set_node_props(family: str, node_id: int, props: Mapping[str, Any]) -> Statement:
    """MATCH (n {id}) SET n.p1 = $p1, ... — nodes are implicit by id, so this
    is also node 'creation'. Multi-assignment SET is micro-probe M1."""
    if not props:
        raise CypherTemplateError("set_node_props needs at least one prop")
    _check_node_props(family, props)
    assignments = ", ".join(f"n.{k} = ${k}" for k in props)
    return (f"MATCH (n {{id: $__id}}) SET {assignments}", {"__id": node_id, **props})


# The ONLY Cypher that may name the latent objective params (Law 15).
INGEST_LATENT_PROPS = (
    "MATCH (n {id: $__id}) SET n.latent_quality = $__lq, n.ship_reliability = $__sr"
)


def ingest_latent_props(product_id: int, lq: float, sr: float) -> Statement:
    return (INGEST_LATENT_PROPS, {"__id": product_id, "__lq": lq, "__sr": sr})


def create_edge(
    rel: str, a: int, b: int, props: Mapping[str, Any] | None = None, *, merge: bool = False
) -> Statement:
    """One-hop edge write, inline props. CREATE for append-only episodic
    edges (MERGE would dedup repeat events); MERGE for idempotent objective
    edges and supersession re-creates keyed by distinct t."""
    props = props or {}
    _check_edge_props(rel, props)
    params: dict[str, Any] = {"__a": a, "__b": b}
    prop_str = ""
    if props:
        prop_str = " {" + ", ".join(f"{k}: ${k}" for k in props) + "}"
        params.update(props)
    verb = "MERGE" if merge else "CREATE"
    return (f"{verb} (a {{id: $__a}})-[:{rel}{prop_str}]->(b {{id: $__b}})", params)


def supersede_edge(
    rel: str, a: int, b: int, now: int, extra_sets: Mapping[str, Any] | None = None
) -> Statement:
    """The verified supersession pattern. extra_sets adds e.g. the NEEDS
    satisfied-with-cause receipt (closed_cause_kind / closed_cause_id)."""
    extra_sets = extra_sets or {}
    _check_edge_props(rel, extra_sets)
    if rel not in schema.BITEMPORAL_EDGES:
        raise CypherTemplateError(f":{rel} is not bitemporal; nothing to supersede")
    sets = "e.valid_to = $__now"
    params: dict[str, Any] = {"__a": a, "__b": b, "__now": now}
    for k, v in extra_sets.items():
        sets += f", e.{k} = ${k}"
        params[k] = v
    return (
        f"MATCH (a {{id: $__a}})-[e:{rel}]->(b {{id: $__b}}) "
        f"WHERE e.valid_to > $__now SET {sets}",
        params,
    )


def supersede_expects(shopper_id: int, concept_id: int, about: int, now: int) -> Statement:
    """EXPECTS is logically keyed by (concept, brand): several brands can set
    expectations on one concept, so the supersede filters on e.about too
    (compound WHERE — probe M3 verified)."""
    return (
        "MATCH (a {id: $__a})-[e:EXPECTS]->(b {id: $__b}) "
        "WHERE e.valid_to > $__now AND e.about = $__about SET e.valid_to = $__now",
        {"__a": shopper_id, "__b": concept_id, "__now": now, "__about": about},
    )


def close_belief_node(belief_id: int, now: int) -> Statement:
    return ("MATCH (n {id: $__id}) SET n.valid_to = $__now", {"__id": belief_id, "__now": now})


def delete_edge(rel: str, a: int, b: int) -> Statement:
    _check_rel(rel)
    return (f"MATCH (a {{id: $__a}})-[e:{rel}]->(b {{id: $__b}}) DELETE e", {"__a": a, "__b": b})


def delete_edges_batch(rel: str, pairs: list[tuple[int, int]]) -> Statement:
    """Batched DELETE (probed: legal ONLY with BOTH endpoints anchored —
    unanchored-destination UNWIND deletes are rejected). Test cleanup only."""
    _check_rel(rel)
    rows = [{"a": a, "b": b} for a, b in pairs]
    return (
        f"UNWIND $rows AS row MATCH (s {{id: row.a}})-[e:{rel}]->(x {{id: row.b}}) DELETE e",
        {"rows": rows},
    )


# ---------------------------------------------------------------------------
# reads (edge props => per-source singles)
# ---------------------------------------------------------------------------


def node_props(family: str, node_id: int, props: Iterable[str]) -> Statement:
    props = tuple(props)
    _check_node_props(family, props)
    projection = ", ".join(f"n.{p} AS {p}" for p in props)
    return (f"MATCH (n {{id: $__id}}) RETURN {projection}", {"__id": node_id})


def _projection(edge_props: tuple[str, ...], dst_alias: str = "dst") -> str:
    parts = [f"x.id AS {dst_alias}"]
    parts += [f"e.{p} AS {p}" for p in edge_props]
    return ", ".join(parts)


def live_edges(rel: str, a: int, now: int, edge_props: tuple[str, ...] = ()) -> Statement:
    """Live (unsuperseded) edges from a: WHERE e.valid_to > $now."""
    _check_edge_props(rel, edge_props)
    if rel not in schema.BITEMPORAL_EDGES:
        raise CypherTemplateError(f":{rel} has no valid_to; use all_edges/events_since")
    return (
        f"MATCH (a {{id: $__a}})-[e:{rel}]->(x) WHERE e.valid_to > $__now "
        f"RETURN {_projection(edge_props)}",
        {"__a": a, "__now": now},
    )


def events_since(rel: str, a: int, since: int, edge_props: tuple[str, ...] = ("t",)) -> Statement:
    """Episodic edges newer than `since` (window reads: SAW, BOUGHT, ...)."""
    _check_edge_props(rel, edge_props)
    return (
        f"MATCH (a {{id: $__a}})-[e:{rel}]->(x) WHERE e.t > $__since "
        f"RETURN {_projection(edge_props)}",
        {"__a": a, "__since": since},
    )


def all_edges(rel: str, a: int, edge_props: tuple[str, ...] = ()) -> Statement:
    """Full history — no WHERE. Supersession chains, episodic totals."""
    _check_edge_props(rel, edge_props)
    return (
        f"MATCH (a {{id: $__a}})-[e:{rel}]->(x) RETURN {_projection(edge_props)}",
        {"__a": a},
    )


def edge_history(rel: str, a: int, b: int, edge_props: tuple[str, ...] = ()) -> Statement:
    """Both ends anchored: the version chain for one (a, b) pair."""
    _check_edge_props(rel, edge_props)
    projection = ", ".join(f"e.{p} AS {p}" for p in edge_props) or "e.t AS t"
    return (
        f"MATCH (a {{id: $__a}})-[e:{rel}]->(b {{id: $__b}}) RETURN {projection}",
        {"__a": a, "__b": b},
    )


def live_holds(shopper_id: int, now: int) -> Statement:
    """Hot-path belief read: HOLDS-edge liveness + denormalized belief-node
    props in one statement (destination node props — micro-probe M2)."""
    return (
        "MATCH (a {id: $__a})-[e:HOLDS]->(x) WHERE e.valid_to > $__now "
        "RETURN x.id AS dst, x.value AS value, x.evidence AS evidence, "
        "x.about_id AS about_id, x.that_id AS that_id",
        {"__a": shopper_id, "__now": now},
    )


def holds_history(shopper_id: int) -> Statement:
    """All belief versions ever held (as-of-T reads sort client-side)."""
    return (
        "MATCH (a {id: $__a})-[e:HOLDS]->(x) "
        "RETURN x.id AS dst, x.value AS value, x.evidence AS evidence, "
        "x.about_id AS about_id, x.that_id AS that_id, x.t AS t, x.valid_to AS valid_to",
        {"__a": shopper_id},
    )


def adj_batch(rel: str, source_ids: list[int]) -> Statement:
    """The one legal batch-read shape: adjacency only, no edge props."""
    _check_rel(rel)
    rows = [{"sid": i} for i in source_ids]
    return (
        f"UNWIND $rows AS row MATCH (s {{id: row.sid}})-[e:{rel}]->(x) RETURN row.sid, x.id",
        {"rows": rows},
    )


def sppaths(a: int, b: int, rel_types: list[str], max_len: int | None = None) -> Statement:
    """Route A: bare CALL only (any MATCH prefix is rejected)."""
    for rel in rel_types:
        _check_rel(rel)
    max_len = max_len or schema.DEFAULT_PARAMS.max_path_len
    if max_len > schema.DEFAULT_PARAMS.max_path_len:
        raise CypherTemplateError(f"maxLen {max_len} exceeds the {schema.DEFAULT_PARAMS.max_path_len} cap")
    return (
        "CALL algo.SPpaths({sourceNode: $__a, targetNode: $__b, "
        f"relTypes: {rel_types!r}, maxLen: {max_len}}}) YIELD path RETURN path",
        {"__a": a, "__b": b},
    )
