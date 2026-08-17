"""Experiment orchestration: spec → generated run_config → the REAL runner,
arm by arm, then a comparison report (Phase 4, CONTRACT v3.4-draft).

Arms run in declared order (builders put shelf-aligning zero-discount arms
first and promo-heavy arms last); branch arms run right after their source —
replay.branch enforces the hash discipline. Fresh arms share the seed, so
populations are identical across arms by construction.
"""

from __future__ import annotations

from pathlib import Path

from ..runner.config import RunConfig, find_repo_root
from ..runner.loop import SimRunner
from ..runner.replay import branch
from ..runner.results import validate_results
from ..runner.runstore import RunStore, write_json_atomic
from .build import build_run_config
from .compare import build_comparison
from .specs import load_spec


def run_experiment(spec_path: Path | str, *, out_dir: Path | str | None = None,
                   quiet: bool = True) -> Path:
    """Returns the experiment dir holding run_config.json + comparison.json.
    Per-arm run dirs live in the ordinary runs/ registry."""
    spec_path = Path(spec_path)
    spec = load_spec(spec_path)
    root = find_repo_root(spec_path.parent)
    raw = build_run_config(spec, root)

    exp_dir = (Path(out_dir) if out_dir is not None
               else root / "runs" / "experiments" / spec.name)
    exp_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = exp_dir / "run_config.json"
    write_json_atomic(cfg_path, raw)

    cfg = RunConfig.load(cfg_path)
    store = RunStore(cfg.root)
    results_by_arm: dict[str, dict] = {}
    for arm in cfg.arms:  # declared order IS the execution order
        if arm.branch_from is not None:
            if arm.branch_from not in results_by_arm:
                raise ValueError(
                    f"arm {arm.name}: branch_from {arm.branch_from!r} must be "
                    "declared (and therefore run) before the branch")
            results_by_arm[arm.name] = branch(cfg, arm.name, store, quiet=quiet)
            continue
        run_index, run_dir = store.allocate(cfg, arm.name)
        if not quiet:
            print(f"[{spec.name}] arm {arm.name} -> {run_dir.name} (block {run_index})")
        runner = SimRunner(cfg, arm.name, run_index, run_dir, quiet=quiet)
        try:
            runner.prepare(seed_graph=True)
            store.set_status(run_dir.name, "running")
            results_by_arm[arm.name] = runner.run()
            store.set_status(run_dir.name, "complete")
        finally:
            runner.close()

    problems = []
    for name, results in results_by_arm.items():
        problems += [f"{name}: {p}" for p in validate_results(results)]
    if problems:
        raise RuntimeError("experiment results not C3-valid: " + "; ".join(problems))

    comparison = build_comparison(raw, results_by_arm)
    write_json_atomic(exp_dir / "comparison.json", comparison)
    return exp_dir
