"""Resume protocol: find the last TICK_COMPLETE, roll the partial tick back
by timestamp, truncate the JSONL to the marker (CONTRACT v3.3).

Soundness relies on loop.py's ordering: JSONL precedes graph in every phase,
and every graph write of tick k is stamped t == now_k (creates) or
valid_to == now_k (supersessions). The one write without its own JSONL record
— the promo hook's PRICED_AT move and the consolidation supersessions — are
still identifiable by that timestamp, so the rollback sweeps by timestamp and
never needs a second source of truth. All rollback statements are idempotent:
a crash mid-rollback just re-runs it.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..contracts.enums import EventType
from ..hydramem import cypher, schema

_SUBJECTIVE_SWEEP = ("PREFERS", "EXPECTS", "REFERENCE_PRICE", "NEEDS", "HABIT")


def load_records(path: Path | str) -> list[dict]:
    out = []
    p = Path(path)
    if not p.exists():
        return out
    with open(p, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def split_at_last_marker(records: list[dict]) -> tuple[list[dict], list[dict], dict | None]:
    """(clean records incl. markers, partial tail, last marker or None)."""
    last = None
    for i, rec in enumerate(records):
        if rec.get("type") == "TICK_COMPLETE":
            last = i
    if last is None:
        return [], list(records), None
    return records[: last + 1], records[last + 1:], records[last]


def truncate_log(path: Path | str, clean: list[dict]) -> None:
    p = Path(path)
    tmp = p.with_suffix(".jsonl.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        for rec in clean:
            fh.write(json.dumps(rec, separators=(",", ":"), sort_keys=True) + "\n")
    tmp.replace(p)


def rollback_partial(client, partial: list[dict], t_partial: int,
                     promo_products: list[int]) -> int:
    """Undo every graph write of the incomplete tick. Returns statement count."""
    stmts = []

    # 1. episodic edges named by the partial log records (both endpoints known)
    for rec in partial:
        rel = rec.get("type")
        if rel in schema.EPISODIC_EDGE_TYPES:
            stmts.append(cypher.delete_edges_at_t(
                rel, rec["shopper_id"], rec["subject"], t_partial))

    # 2. subjective + goal sweep for every shopper the partial tick touched
    touched = sorted({rec["shopper_id"] for rec in partial if "shopper_id" in rec})
    for sid in touched:
        for rel in _SUBJECTIVE_SWEEP:
            pairs_new, pairs_closed = set(), set()
            for row in client.run_stmt(cypher.all_edges(rel, sid, ("t", "valid_to"))):
                if row["t"] == t_partial:
                    pairs_new.add(row["dst"])
                elif row["valid_to"] == t_partial:
                    pairs_closed.add(row["dst"])
            for dst in sorted(pairs_new):
                stmts.append(cypher.delete_edges_at_t(rel, sid, dst, t_partial))
            for dst in sorted(pairs_closed):
                stmts.append(cypher.reopen_edges(rel, sid, dst, t_partial))

        # belief versions: new nodes deleted with their satellite edges,
        # superseded nodes reopened (HOLDS edge + node valid_to)
        for row in client.run_stmt(cypher.holds_history(sid)):
            bid = row["dst"]
            if row["t"] == t_partial:
                for d in client.run_stmt(cypher.all_edges("DERIVED_FROM", bid)):
                    stmts.append(cypher.delete_edge("DERIVED_FROM", bid, d["dst"]))
                stmts.append(cypher.delete_edge("ABOUT", bid, row["about_id"]))
                stmts.append(cypher.delete_edge("THAT", bid, row["that_id"]))
                stmts.append(cypher.delete_edges_at_t("HOLDS", sid, bid, t_partial))
            elif row["valid_to"] == t_partial:
                stmts.append(cypher.reopen_edges("HOLDS", sid, bid, t_partial))
                stmts.append(cypher.set_node_props("belief", bid, {
                    "valid_to": schema.VALID_TO_SENTINEL}))

    # 3. the promo hook's PRICED_AT move (config-derived, no log record)
    for pid in sorted(promo_products):
        stmts.append(cypher.delete_edges_at_t(
            "PRICED_AT", pid, schema.PRICEBOOK_ID, t_partial))
        stmts.append(cypher.reopen_edges(
            "PRICED_AT", pid, schema.PRICEBOOK_ID, t_partial))

    client.run_seq(stmts)
    return len(stmts)


def group_by_tick(clean: list[dict]) -> dict[int, list[dict]]:
    """Records per completed tick, in log order (markers excluded)."""
    out: dict[int, list[dict]] = {}
    buffer: list[dict] = []
    for rec in clean:
        if rec.get("type") == "TICK_COMPLETE":
            out[rec["tick"]] = buffer
            buffer = []
        else:
            buffer.append(rec)
    return out
