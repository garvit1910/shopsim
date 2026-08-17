"""CLI: python -m shopsim.runner <run|resume|branch|serve|export-fixtures> ...

    run             --config CFG [--arm NAME] [--mind scripted|formula]
                    [--crash-after phase:tick] [--quiet]
    resume          --config CFG --run <run_id|dir> [--quiet]
    branch          --config CFG --arm NAME [--quiet]
    serve           --config CFG [--port 8000]
    export-fixtures --config CFG --out DIR
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from .config import RunConfig
from .loop import RunnerState, SimRunner
from .replay import branch as run_branch
from .results import validate_results
from .rollback import load_records, rollback_partial, split_at_last_marker, truncate_log
from .runstore import RunStore, check_hashes, write_json_atomic


def _load_cfg(args) -> RunConfig:
    cfg = RunConfig.load(args.config)
    if getattr(args, "mind", None):
        cfg.raw.setdefault("mind", {})
        cfg.raw["mind"]["decide"] = args.mind
        cfg.raw["mind"]["consolidate"] = args.mind
        cfg.mind_decide = args.mind
        cfg.mind_consolidate = args.mind
    return cfg


def cmd_run(args) -> int:
    cfg = _load_cfg(args)
    arm_name = args.arm or cfg.arms[0].name
    if cfg.arm(arm_name).branch_from is not None:
        print(f"arm {arm_name!r} is a branch arm — use `branch`", file=sys.stderr)
        return 2
    store = RunStore(cfg.root)
    run_index, run_dir = store.allocate(cfg, arm_name)
    print(f"run {run_dir.name} (block {run_index})")
    runner = SimRunner(cfg, arm_name, run_index, run_dir,
                       crash_after=args.crash_after, quiet=args.quiet)
    runner.prepare(seed_graph=True)
    store.set_status(run_dir.name, "running")
    results = runner.run()
    store.set_status(run_dir.name, "complete")
    problems = validate_results(results)
    if problems:
        print("C3 validation problems: " + "; ".join(problems), file=sys.stderr)
        return 1
    print(f"complete: {run_dir / 'results.json'}")
    runner.close()
    return 0


def cmd_resume(args) -> int:
    cfg = _load_cfg(args)
    store = RunStore(cfg.root)
    row = store.find(args.run)
    arm_name = row["arm"]
    if cfg.config_hash(arm_name) != row["config_hash"]:
        print("resume refused: run_config changed since the run started (Law 13)",
              file=sys.stderr)
        return 2
    run_dir = Path(row["dir"])
    records = load_records(run_dir / "events.jsonl")
    clean, partial, last_marker = split_at_last_marker(records)
    from_tick = (last_marker["tick"] + 1) if last_marker else 0
    print(f"resume {row['run_id']}: last complete tick "
          f"{last_marker['tick'] if last_marker else 'none'}, "
          f"{len(partial)} partial records")

    runner = SimRunner(cfg, arm_name, row["run_index"], run_dir, quiet=args.quiet)
    runner.prepare(seed_graph=False)
    stored_manifest = json.loads((run_dir / "manifest.json").read_text())
    problems = check_hashes(stored_manifest, runner.manifest, include_config=True)
    if problems:
        print("resume refused — manifest mismatch (Law 13): " + "; ".join(problems),
              file=sys.stderr)
        return 2

    if partial:
        t_partial = cfg.now_at(from_tick)
        promo_products = sorted(runner.promo.windows) if runner.promo else []
        n = rollback_partial(runner.mem.client, partial, t_partial, promo_products)
        print(f"rolled back partial tick {from_tick} ({n} statements)")
        truncate_log(run_dir / "events.jsonl", clean)
        runner.log.close()
        from ..eventlog import JsonlEventLog
        runner.log = JsonlEventLog(run_dir / "events.jsonl")
        runner.mem.event_log = runner.log

    if last_marker:
        runner.mem.allocator._counters["belief"] = last_marker["belief_counter"]
        snap_path = run_dir / f"results_state_{last_marker['tick']}.json"
        snap = json.loads(snap_path.read_text())
        assert snap["tick"] == last_marker["tick"]
        from .results import ResultsAccumulator
        runner.results = ResultsAccumulator.from_state(
            snap["state"], segment_by_offset=runner.segment_by_offset,
            drift_concepts=runner.results.drift_concepts,
            hero_product=runner.results.hero_product)

    state = RunnerState()
    state.rebuild_from_records(clean, cfg.t0, cfg.tick_seconds, runner.page_of)
    store.set_status(row["run_id"], "running")
    results = runner.run(from_tick=from_tick, state=state)
    store.set_status(row["run_id"], "complete")
    print(f"complete: {run_dir / 'results.json'}")
    runner.close()
    return 0


def cmd_branch(args) -> int:
    cfg = _load_cfg(args)
    if not args.arm:
        print("branch needs --arm", file=sys.stderr)
        return 2
    store = RunStore(cfg.root)
    run_branch(cfg, args.arm, store, quiet=args.quiet)
    print("branch complete")
    return 0


def cmd_serve(args) -> int:
    cfg = _load_cfg(args)
    from .api import serve
    serve(cfg.root, port=args.port)
    return 0


def cmd_export_fixtures(args) -> int:
    cfg = _load_cfg(args)
    store = RunStore(cfg.root)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    write_json_atomic(out / "run_config.json", cfg.raw)

    primary_results = None
    merged_funnel: dict = {}
    for arm in cfg.arms:
        row = store.latest_for(cfg.label, arm.name)
        src = Path(row["dir"])
        arm_dir = out / arm.name
        arm_dir.mkdir(exist_ok=True)
        for name in ("events.jsonl", "manifest.json", "results.json", "progress.json"):
            shutil.copy(src / name, arm_dir / name)
        results = json.loads((src / "results.json").read_text())
        merged_funnel.update(results["funnel"])
        if arm.branch_from is None and primary_results is None:
            primary_results = results
        _export_shoppers(cfg, row, arm_dir)

    assert primary_results is not None
    merged = dict(primary_results)
    merged["funnel"] = merged_funnel
    problems = validate_results(merged)
    if problems:
        print("merged results.json is not C3-valid: " + "; ".join(problems),
              file=sys.stderr)
        return 1
    write_json_atomic(out / "results.json", merged)
    print(f"fixtures exported to {out}")
    return 0


def _export_shoppers(cfg: RunConfig, row: dict, arm_dir: Path) -> None:
    """Worldview/trace/preference-history samples: the Maya twin offsets plus
    the two most active buyers (Phase 5.3 drill-down fixtures)."""
    from ..contracts.enums import EventType
    from ..hydramem.real import HydraMem

    records = load_records(Path(row["dir"]) / "events.jsonl")
    buys: dict[int, int] = {}
    for rec in records:
        if rec.get("type") == EventType.BOUGHT.value:
            o = rec["shopper_id"] % 100_000
            buys[o] = buys.get(o, 0) + 1
    offsets = [41, 42] + [o for o, _ in sorted(buys.items(), key=lambda kv: -kv[1])
                          if o not in (41, 42)][:2]

    mem = HydraMem(run_index=row["run_index"])
    mem.set_tick(tick=cfg.ticks - 1, now=cfg.now_at(cfg.ticks - 1))
    shoppers_dir = arm_dir / "shoppers"
    shoppers_dir.mkdir(exist_ok=True)
    from ..contracts.ids import shopper_id as make_sid
    try:
        for o in offsets:
            sid = make_sid(row["run_index"], o)
            payload = {
                "offset": o,
                "shopper_id": sid,
                "worldview": mem.get_shopper_worldview(sid),
                "trace_ecostride_sale": mem.get_trace(sid, 2000003),
                "preference_history_eco": mem.get_preference_history(sid, 5003),
            }
            write_json_atomic(shoppers_dir / f"offset_{o}.json", payload)
    finally:
        mem.close()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="shopsim.runner")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--config", required=True)
        sp.add_argument("--mind", choices=("scripted", "formula"))
        sp.add_argument("--quiet", action="store_true")

    sp = sub.add_parser("run")
    common(sp)
    sp.add_argument("--arm")
    sp.add_argument("--crash-after", help="phase:tick fault injection, e.g. consolidation:7")
    sp.set_defaults(fn=cmd_run)

    sp = sub.add_parser("resume")
    common(sp)
    sp.add_argument("--run", required=True)
    sp.set_defaults(fn=cmd_resume)

    sp = sub.add_parser("branch")
    common(sp)
    sp.add_argument("--arm", required=True)
    sp.set_defaults(fn=cmd_branch)

    sp = sub.add_parser("serve")
    common(sp)
    sp.add_argument("--port", type=int, default=8000)
    sp.set_defaults(fn=cmd_serve)

    sp = sub.add_parser("export-fixtures")
    common(sp)
    sp.add_argument("--out", required=True)
    sp.set_defaults(fn=cmd_export_fixtures)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
