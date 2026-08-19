"""CLI: python -m shopsim.analytics report --run <run_id|dir> [options]

    report  --run RUN [--config CFG] [--write] [--no-graph] [--json]
            [--n-boot N]

The Phase-6 checkpoint "one command from a run directory -> full report".
Recomputes the whole C3 MetricsReport from what the run left on disk (the
newest results_state snapshot) plus, unless --no-graph, one read-only sweep of
the worldview store for the belief and provenance blocks.

--write refreshes the run's results.json in place. Without it the command is
strictly read-only, which is what you want mid-demo.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _resolve(root: Path, run: str) -> tuple[Path, int]:
    """(run_dir, run_index) from a run id or a path. The registry is the
    authority on run_index; a bare directory falls back to its manifest."""
    from ..runner.runstore import RunStore

    p = Path(run)
    if p.is_dir():
        run_dir = p.resolve()
        try:
            return run_dir, int(RunStore(root).find(run_dir.name)["run_index"])
        except (KeyError, OSError):
            manifest = json.loads((run_dir / "manifest.json").read_text())
            return run_dir, int(manifest["run_index"])
    row = RunStore(root).find(run)  # raises KeyError with a plain message
    return Path(row["dir"]), int(row["run_index"])


def _segments(root: Path, run_dir: Path, config: str | None) -> tuple[dict, list[str]]:
    """The offset -> segment map, needed only for per-segment CIs.

    Experiment-launched runs keep their run_config beside the experiment; CLI
    runs keep it wherever the operator put it, hence --config.
    """
    from ..runner.config import RunConfig

    cfg_path = None
    if config:
        cfg_path = Path(config)
    else:
        try:
            manifest = json.loads((run_dir / "manifest.json").read_text())
            guess = root / "runs" / "experiments" / manifest["label"] / "run_config.json"
            cfg_path = guess if guess.exists() else None
        except (OSError, KeyError):
            cfg_path = None
    if cfg_path is None or not Path(cfg_path).exists():
        return {}, ["no run_config found — pass --config for per-segment intervals"]

    cfg = RunConfig.load(cfg_path)
    from ..contracts.ids import shopper_offset
    from ..population.factory import (
        PopulationConfig, generate_population, load_segment_specs)

    _ap, _cp, stage_bases = cfg.calibration()
    shoppers = generate_population(PopulationConfig(
        seed=cfg.seed, population_size=cfg.population_size,
        segments=load_segment_specs(cfg.personas_path), run_index=0,
        stage_bases=stage_bases))
    return {shopper_offset(s.shopper_id): s.segment_id for s in shoppers}, []


def cmd_report(args) -> int:
    from ..runner.config import find_repo_root
    from ..runner.runstore import write_json_atomic
    from .report import render, report_for_run

    root = find_repo_root(Path.cwd())
    try:
        run_dir, run_index = _resolve(root, args.run)
    except KeyError as ex:
        print(f"error: {ex}", file=sys.stderr)
        return 2
    segment_by_offset, notes = _segments(root, run_dir, args.config)
    results, more = report_for_run(
        run_dir, run_index=run_index, use_graph=not args.no_graph,
        segment_by_offset=segment_by_offset, n_boot=args.n_boot)
    notes += more

    if args.json:
        print(json.dumps(results, indent=1, sort_keys=True))
    else:
        print(render(results, notes))

    from ..runner.results import validate_results
    problems = validate_results(results)
    if problems:
        print("C3 validation problems: " + "; ".join(problems), file=sys.stderr)
        return 1
    if args.write:
        write_json_atomic(run_dir / "results.json", results)
        print(f"\nwritten: {run_dir / 'results.json'}", file=sys.stderr)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="shopsim.analytics")
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("report")
    sp.add_argument("--run", required=True, help="run id (r042-...) or run directory")
    sp.add_argument("--config", help="run_config.json, for per-segment intervals")
    sp.add_argument("--write", action="store_true", help="refresh results.json in place")
    sp.add_argument("--no-graph", action="store_true",
                    help="skip the belief/provenance sweep (never wait on the store)")
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--n-boot", type=int, default=None)
    sp.set_defaults(fn=cmd_report)

    args = p.parse_args(argv)
    if getattr(args, "n_boot", None) is None:
        from .metrics import N_BOOT
        args.n_boot = N_BOOT
    try:
        return args.fn(args)
    except (FileNotFoundError, ValueError, RuntimeError) as ex:
        print(f"error: {ex}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
