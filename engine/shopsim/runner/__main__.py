"""CLI: python -m shopsim.runner <run|resume|branch|serve|export-fixtures> ...

    run             --config CFG [--arm NAME] [--mind scripted|formula]
                    [--crash-after phase:tick] [--quiet] [--trace-decisions]
    resume          --config CFG --run <run_id|dir> [--quiet]
    branch          --config CFG --arm NAME [--quiet]
    serve           --config CFG [--port 8000]
    export-fixtures --config CFG --out DIR
    export-graph    --config CFG --run RUN_ID --out FILE.json [--previews]
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
                       crash_after=args.crash_after, quiet=args.quiet,
                       trace_decisions=getattr(args, "trace_decisions", False))
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
            hero_product=runner.results.hero_product,
            choice_params=runner.results.choice_params,
            w_social=runner.results.w_social)

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


def cmd_export_graph(args) -> int:
    """Freeze one run's social memory graph into a committed fixture.

    Same move as _export_shoppers, one level up: read the live graph through
    the shipped HydraMem API at a pinned as-of clock and write the payload to
    disk, so the dashboard can show it forever without the store.

    That matters because shopper worldviews live ONLY in HydraDB. `runs/`
    keeps events and results, but the graph goes with the store, and the store
    gets archived and recreated routinely (infra/README.md's reset ritual).
    Reading it live meant the 04 Graph exhibit blanked every time somebody
    reset before a timed run, and reshaped itself run to run in between.

    The traces are captured too, not just nodes and edges: Explain mode reads
    them, and recomputing motifs client-side would mean the dashboard
    inventing graph structure, which is the one thing it must never do.
    """
    cfg = _load_cfg(args)
    store = RunStore(cfg.root)
    row = store.find(args.run)
    run_dir = Path(row["dir"])
    man = json.loads((run_dir / "manifest.json").read_text())

    # As-of the last fully consolidated tick — the same clock the API pins
    # every graph read to, so the capture matches what the live page showed.
    progress_path = run_dir / "progress.json"
    head = man["ticks"] - 1
    if progress_path.exists():
        head = min(head, json.loads(progress_path.read_text()).get("tick", head))
    now = man["t0"] + head * man["tick_seconds"]

    from ..contracts.ids import shopper_id as make_sid
    from ..hydramem.real import HydraMem

    mem = HydraMem(run_index=row["run_index"])
    try:
        mem.set_tick(tick=head, now=now, tick_start=now)
        candidates = mem.find_social_triads()
        if not candidates:
            print(f"export-graph: {row['run_id']} has no TRUSTS_PERSON edges in the "
                  "store — either it was built without population.social, or its "
                  "store has been archived away", file=sys.stderr)
            return 1
        focus = candidates[0]
        creative_names = _creative_names(cfg)

        # --previews (v3.12-draft, the Shopper Mind capture): every scheduled
        # creative and its landing page for the pinned shopper (focus[0]) is
        # forced on screen, traced, and appraised — met or not — so the page
        # can show the retrieval path AND the decision math for any demo ad
        # without the store. Baked by the same code the live endpoint runs
        # (runner/preview.py); traits/coeffs still never leave the process.
        pv = None
        demo_stimuli: list[dict] = []
        stim_ids: set[int] = set()
        if args.previews:
            from .preview import build_population, build_preview_ctx, compute_preview
            try:
                pv = build_preview_ctx(cfg, row["arm"])
            except ValueError as ex:
                print(f"export-graph: {ex}", file=sys.stderr)
                return 1
            offset0 = focus["offsets"][0]
            for cid in sorted({r.creative_id for r in pv["sched"]}):
                page_id = pv["page_of"](offset0, cid)
                demo_stimuli.append({"creative_id": cid, "page_id": page_id})
                stim_ids.add(cid)
                if page_id is not None:
                    stim_ids.add(int(page_id))

        graph = mem.get_memory_graph(focus["shopper_ids"],
                                     creative_names=creative_names,
                                     extra_stimuli=sorted(stim_ids))

        # Explain offers exactly the stimuli a shopper actually met, so the
        # capture walks the edges just read rather than the whole catalog —
        # except the pinned shopper under --previews, whose demo stimuli are
        # all traced so the Mind page never lacks a retrieval path.
        traces: dict[str, dict] = {}
        for sid, offset in zip(focus["shopper_ids"], focus["offsets"]):
            met = {e["target"] for e in graph["edges"]
                   if e["source"] == sid and e["rel"] in ("SAW", "VISITED")}
            if pv is not None and offset == focus["offsets"][0]:
                met |= stim_ids
            traces[str(offset)] = {
                str(stim): mem.get_trace(sid, stim) for stim in sorted(met)}

        previews: dict[str, dict] = {}
        if pv is not None:
            _specs, shoppers = build_population(cfg, row["run_index"])
            offset0 = focus["offsets"][0]
            sid0 = focus["shopper_ids"][0]
            previews[str(offset0)] = {}
            for stim in sorted(stim_ids):
                ctx = mem.get_decision_context(sid0, stim)
                previews[str(offset0)][str(stim)] = compute_preview(
                    pv, ctx, shoppers[offset0], offset0, stim, head)
    finally:
        mem.close()

    payload = {
        "comment": (
            f"Frozen capture of the 04 Graph exhibit, taken from {row['run_id']} "
            f"as of day {head} of {man['ticks']}. Every node, edge and trace here "
            "came out of HydraDB through the shipped read API — this is a "
            "photograph of a real run, not a mock. It is committed because "
            "shopper worldviews live only in the graph store, and that store is "
            "archived and recreated routinely (infra/README.md); reading it live "
            "meant the exhibit blanked after every reset and reshaped itself run "
            "to run. WHAT THIS IS NOT: it does not reflect whichever simulation "
            "is currently loaded or running, and the page says so. Regenerate "
            "with `python -m shopsim.runner export-graph` — see the README beside "
            "this file."),
        "captured": {
            "run_id": row["run_id"],
            "run_index": row["run_index"],
            "arm": row.get("arm"),
            "label": row.get("label"),
            "head_tick": head,
        },
        "run_id": row["run_id"],
        "run_index": row["run_index"],
        "t0": man["t0"],
        "tick_seconds": man["tick_seconds"],
        "ticks": man["ticks"],
        "head_tick": head,
        "social_enabled": True,
        "focus": focus["offsets"],
        "candidates": candidates,
        "nodes": graph["nodes"],
        "edges": graph["edges"],
        "traces": traces,
    }
    if pv is not None:
        payload["comment"] += (
            " PREVIEWS: this capture also carries `catalog_key`, `demo_stimuli` "
            "and `previews` (offset -> stimulus -> the exact decision-preview "
            "envelope, computed at export time by the same appraise()/"
            "stage_probabilities() the live endpoint runs) — the Shopper Mind "
            "page reads those, v3.12-draft.")
        payload["catalog_key"] = cfg.catalog_dir.name
        payload["demo_stimuli"] = demo_stimuli
        payload["previews"] = previews
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(out, payload)
    n_traces = sum(len(v) for v in traces.values())
    n_previews = sum(len(v) for v in previews.values())
    print(f"graph exported to {out}: {len(payload['nodes'])} nodes, "
          f"{len(payload['edges'])} edges, {n_traces} traces, "
          f"{n_previews} previews, "
          f"focus offsets {focus['offsets']} ({focus['why']})")
    return 0


def _creative_names(cfg: RunConfig) -> dict[str, str]:
    """Ad names off the run's own catalog, so the frozen graph reads in words
    rather than ids. Missing catalog is not fatal — labels are decoration."""
    path = cfg.catalog_dir / "creatives.json"
    if not path.exists():
        return {}
    doc = json.loads(path.read_text())
    return {str(r["creative_id"]): r.get("name", str(r["creative_id"]))
            for r in doc.get("creatives", [])}


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
    sp.add_argument("--trace-decisions", action="store_true",
                    help="write decisions.jsonl beside the run (Phase 7 calibration "
                         "input). Off by default: no file, no branch in the tick "
                         "loop, byte-identical results.json")
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

    sp = sub.add_parser("export-graph")
    common(sp)
    sp.add_argument("--run", required=True)
    sp.add_argument("--out", required=True)
    sp.add_argument("--previews", action="store_true",
                    help="also bake decision previews (appraisal + gate "
                         "probabilities) for the pinned shopper x every "
                         "scheduled creative and its landing page — the "
                         "Shopper Mind capture (v3.12-draft)")
    sp.set_defaults(fn=cmd_export_graph)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
