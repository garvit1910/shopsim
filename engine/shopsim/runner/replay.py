"""Branch = replay + diverge (PLAN.md 3.2, CONTRACT v3.3).

Arm B replays arm A's JSONL into a FRESH shopper block up to the divergence
tick T — re-ingesting events with shopper ids remapped by offset and the
worldview RECOMPUTED by running the manifest-recorded consolidator over each
tick's events (never from stored deltas) — then continues live with arm B's
config delta from T on.

Remapped fields: `shopper_id` (by offset into the new block) and `run`.
Unchanged: `subject`, `cause_creative`, `cause_id`, prices, `sat`, `t`
(objective ids are global; timestamps are shared world time). Belief ids are
allocator-fresh in the new block.

Refusal: the source manifest's shared hashes (evidence, perception cache,
goal config, latent table, view) and the mind record must match the current
build — config_hash is the one hash allowed to differ (it IS the branch).

The promo hook is skipped for the replayed prefix: PRICED_AT history is
shared objective state the source arm already wrote; the as-of price reads
serve it (hydramem.reads.ObjectiveCache).

Per-tick sanity: the replayed applier's satisfied_needs must equal the
logged NEED_SATISFIED set — recomputation and record must agree.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..contracts.enums import EventType
from ..contracts.ids import shopper_offset
from ..contracts.types import Event
from ..eventlog import read_events
from ..hydramem import cypher, schema
from ..hydramem.writes import ApplyReport, OrderedDelta
from .config import RunConfig
from .loop import RunnerState, SimRunner
from .rollback import group_by_tick, split_at_last_marker
from .runstore import RunStore, check_hashes, write_json_atomic

_BASE_KEYS = {"type", "shopper_id", "t", "run", "subject"}


def _remap_event(rec: dict, run_index: int, sid_of) -> Event:
    props = tuple(sorted(
        (k, v) for k, v in rec.items() if k not in _BASE_KEYS))
    return Event(
        type=EventType(rec["type"]),
        shopper_id=sid_of(shopper_offset(rec["shopper_id"])),
        t=rec["t"],
        run=run_index,
        subject=rec["subject"],
        props=props,
    )


def branch(cfg: RunConfig, arm_name: str, store: RunStore, *,
           crash_after: str | None = None, quiet: bool = False) -> dict:
    arm = cfg.arm(arm_name)
    if arm.branch_from is None or arm.divergence_tick is None:
        raise ValueError(f"arm {arm_name!r} has no branch_from/divergence_tick")
    src_row = store.latest_for(cfg.label, arm.branch_from)
    src_dir = Path(src_row["dir"])
    src_manifest = json.loads((src_dir / "manifest.json").read_text())
    clean, partial, last_marker = split_at_last_marker(read_events(src_dir / "events.jsonl"))
    if partial:
        raise RuntimeError(f"source run {src_row['run_id']} has a partial tick — "
                           "resume it before branching")
    if last_marker is None or last_marker["tick"] < arm.divergence_tick - 1:
        raise RuntimeError(f"source run {src_row['run_id']} has not reached "
                           f"divergence tick {arm.divergence_tick}")
    by_tick = group_by_tick(clean)
    T = arm.divergence_tick

    run_index, run_dir = store.allocate(cfg, arm_name, kind="branch")
    runner = SimRunner(cfg, arm_name, run_index, run_dir,
                       crash_after=crash_after, quiet=quiet)
    runner.prepare(seed_graph=True)

    problems = check_hashes(src_manifest, runner.manifest, include_config=False)
    if problems:
        raise RuntimeError("replay refused — manifest hash mismatch (Law 13): "
                           + "; ".join(problems))
    if src_manifest.get("mind") != runner.manifest["mind"]:
        raise RuntimeError("replay refused — mind record differs from the source run")

    runner.results.decisions_from_tick = T
    state = RunnerState()
    for tick in range(T):
        _replay_tick(runner, state, by_tick.get(tick, []), tick)
    store.set_status(run_dir.name, "replayed")

    results = runner.run(from_tick=T, state=state)
    store.set_status(run_dir.name, "complete")
    return results


def _replay_tick(runner: SimRunner, state: RunnerState, recs: list[dict], tick: int) -> None:
    cfg, mem, log = runner.cfg, runner.mem, runner.log
    now = cfg.now_at(tick)
    run = runner.run_index
    mem.set_tick(tick=tick, now=now, tick_start=now)

    goal_stmts: dict[int, list] = {}
    episodic: list[Event] = []
    expected_satisfied: set[tuple[int, int, int]] = set()

    for rec in recs:
        rtype = rec["type"]
        offset = shopper_offset(rec["shopper_id"])
        sid = runner.sid_of(offset)
        if rtype == EventType.NEED_ACTIVATED.value:
            log.append_event(_remap_event(rec, run, runner.sid_of))
            goal_stmts.setdefault(sid, []).append(cypher.create_edge(
                "NEEDS", sid, rec["subject"], {
                    "strength": rec["strength"], "budget_cap": rec["budget_cap"],
                    "deadline_t": rec["deadline_t"], "t": rec["t"],
                    "valid_to": schema.VALID_TO_SENTINEL, "source": rec["source"]}))
            state.goal.apply_record({**rec, "shopper_id": sid}, cfg.t0, cfg.tick_seconds)
        elif rtype == EventType.NEED_EXPIRED.value:
            log.append_event(_remap_event(rec, run, runner.sid_of))
            goal_stmts.setdefault(sid, []).append(cypher.supersede_edge(
                "NEEDS", sid, rec["subject"], rec["t"], {
                    "closed_cause_kind": EventType.NEED_EXPIRED.value,
                    "closed_cause_id": 0}))
            state.goal.apply_record({**rec, "shopper_id": sid}, cfg.t0, cfg.tick_seconds)
        elif rtype == EventType.NEED_SATISFIED.value:
            # not applied directly: consolidation below must reproduce it
            expected_satisfied.add((offset, rec["subject"], rec["cause_id"]))
        else:
            episodic.append(_remap_event(rec, run, runner.sid_of))
    log.flush()
    mem.client.run_grouped(goal_stmts)

    # episodic re-ingest (writes the branch's own JSONL + graph edges)
    mem.record_events(episodic)
    runner.results.observe_events(episodic, tick)

    # worldview recomputation — identical to the live loop's step 8
    from ..hydramem import writes as hw
    events_by_offset: dict[int, list[Event]] = {}
    for e in episodic:
        events_by_offset.setdefault(shopper_offset(e.shopper_id), []).append(e)
    active = sorted(events_by_offset)
    snaps = hw.snapshot_worldviews(mem.client, [runner.sid_of(o) for o in active], now)
    per_shopper: dict[int, list[OrderedDelta]] = {}
    for o in active:
        sid = runner.sid_of(o)
        deltas = runner.consolidator.consolidate(events_by_offset[o], snaps[sid])
        if deltas:
            per_shopper[sid] = [OrderedDelta(now, i, d) for i, d in enumerate(deltas)]
    report = mem.apply_deltas(per_shopper) if per_shopper else ApplyReport()

    got = {(shopper_offset(sid), cat, pid) for sid, cat, pid in report.satisfied_needs}
    if got != expected_satisfied:
        raise RuntimeError(
            f"replay divergence at tick {tick}: recomputed need satisfactions {got} "
            f"!= logged {expected_satisfied} — evidence.py or the log has drifted")
    for sid, cat, pid in report.satisfied_needs:
        o = shopper_offset(sid)
        log.append({"type": EventType.NEED_SATISFIED.value, "shopper_id": sid,
                    "subject": cat, "t": now, "run": run,
                    "cause_kind": EventType.BOUGHT.value, "cause_id": pid})
        entry = state.goal.live.pop((o, cat), None)
        if entry is not None:
            runner.results.observe_satisfaction(entry[1], tick)
    log.flush()

    # cross-tick state from the replayed records
    for e in episodic:
        o = shopper_offset(e.shopper_id)
        etick = (e.t - cfg.t0) // cfg.tick_seconds
        if e.type is EventType.SAW:
            state.saw.record(o, etick, e.subject)
        elif e.type is EventType.CARTED:
            cause = e.prop("cause_creative", 0)
            state.carts[o] = (e.subject, runner.page_of(o, cause) or 0, cause, etick)
        elif e.type is EventType.BOUGHT:
            state.carts.pop(o, None)
            state.fulfil.record_bought(o, e.subject, e.t, etick)
        elif e.type is EventType.ABANDONED:
            state.carts.pop(o, None)

    runner.results.end_tick_sweep(tick, now, mem)
    write_json_atomic(runner.run_dir / f"results_state_{tick}.json",
                      {"tick": tick, "state": runner.results.state()})
    stale = runner.run_dir / f"results_state_{tick - 2}.json"
    if stale.exists():
        stale.unlink()
    log.append({"type": "TICK_COMPLETE", "tick": tick, "t": now, "run": run,
                "n_events": len(episodic),
                "belief_counter": mem.allocator._counters["belief"]})
    log.sync()
    if not runner.quiet:
        print(f"[{runner.arm.name}] replayed tick {tick}: {len(episodic)} events")
