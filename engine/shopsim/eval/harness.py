"""Running the eval: profile merging, scenario execution, artifact collection.

Scenarios are ordinary `run_config.json` files under `eval/specs/`, executed
through the ordinary `SimRunner`/`replay.branch` path. They are NOT a parallel
simulation stack — a face-validity law proved on a special code path proves
nothing about the engine that ships.

Every scenario declares its calibration by naming a profile, which is merged
into the raw config before loading. The merge happens BEFORE `config_hash` is
taken, so the hash covers the profile: a run can never claim a calibration it
did not use.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from .contexts import repo_root


def eval_dir() -> Path:
    return repo_root() / "eval"


def load_profile(name_or_path: str) -> dict:
    """A profile's `calibration` block by name (eval/profiles/<name>.json) or path."""
    p = Path(name_or_path)
    if not p.exists():
        p = eval_dir() / "profiles" / f"{name_or_path}.json"
    raw = json.loads(p.read_text())
    return raw.get("calibration", {})


def materialize(config_path: Path | str, profile: str | None,
                out_dir: Path | str, *, label: str | None = None,
                overrides: dict | None = None) -> Path:
    """Write `config_path` + the profile's calibration into a runnable config.

    Returned path is what the runner is pointed at. The file is committed under
    eval/ rather than a temp dir on purpose: the exact config a published number
    came from has to be inspectable afterwards.
    """
    raw = json.loads(Path(config_path).read_text())
    if profile:
        # DEEP merge, profile first: a scenario may need one knob moved off the
        # profile (F7b shuts the CLICK gate) without restating the rest, and a
        # shallow replace would silently discard that override.
        merged = load_profile(profile)
        own = raw.get("calibration") or {}
        for group, values in own.items():
            if isinstance(values, dict) and isinstance(merged.get(group), dict):
                merged[group] = {**merged[group], **values}
            else:
                merged[group] = values
        raw["calibration"] = merged
        raw.setdefault("comment", "")
        raw["comment"] = f"[profile: {profile}] " + raw["comment"]
    if label:
        raw["label"] = label
    for k, v in (overrides or {}).items():
        raw[k] = v
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{raw['label']}.json"
    out.write_text(json.dumps(raw, indent=2) + "\n")
    return out


@dataclass
class RunOutcome:
    label: str
    arm: str
    run_id: str
    run_dir: Path
    wall_s: float
    results: dict

    @property
    def trace_path(self) -> Path:
        from .trace import TRACE_FILENAME
        return self.run_dir / TRACE_FILENAME


def run_config(config_path: Path | str, *, arm: str | None = None,
               trace: bool = False, quiet: bool = True) -> RunOutcome:
    """One arm, start to finish, in-process (no subprocess, so a failure raises
    here with its real traceback instead of an exit code)."""
    from ..runner.config import RunConfig
    from ..runner.loop import SimRunner
    from ..runner.runstore import RunStore

    cfg = RunConfig.load(config_path)
    arm_name = arm or cfg.arms[0].name
    store = RunStore(cfg.root)
    run_index, run_dir = store.allocate(cfg, arm_name)
    started = time.perf_counter()
    runner = SimRunner(cfg, arm_name, run_index, run_dir, quiet=quiet,
                       trace_decisions=trace)
    try:
        runner.prepare(seed_graph=True)
        store.set_status(run_dir.name, "running")
        results = runner.run()
        store.set_status(run_dir.name, "complete")
    finally:
        runner.close()
    return RunOutcome(label=cfg.label, arm=arm_name, run_id=run_dir.name,
                      run_dir=run_dir, wall_s=round(time.perf_counter() - started, 2),
                      results=results)


def branch_arm(config_path: Path | str, arm: str, *, quiet: bool = True) -> RunOutcome:
    """A branch arm through the real replay path — the F9 twin.

    Branching rather than re-running is the point: everything before the
    divergence tick is the parent's own log replayed, so the twin shares actual
    history instead of a second simulation that merely started from the same
    seed. `replay.branch` refuses on any manifest-hash mismatch (Law 13), which
    is what makes the pair comparable at all.
    """
    from ..runner.config import RunConfig
    from ..runner.replay import branch as run_branch
    from ..runner.runstore import RunStore

    cfg = RunConfig.load(config_path)
    store = RunStore(cfg.root)
    started = time.perf_counter()
    results = run_branch(cfg, arm, store, quiet=quiet)
    row = store.latest_for(cfg.label, arm)
    run_dir = Path(row["dir"])
    return RunOutcome(label=cfg.label, arm=arm, run_id=run_dir.name, run_dir=run_dir,
                      wall_s=round(time.perf_counter() - started, 2), results=results)


def load_results(run_dir: Path | str) -> dict:
    return json.loads((Path(run_dir) / "results.json").read_text())


def quality_catalogs(good: float, bad: float, out_root: Path | None = None
                     ) -> tuple[Path, Path]:
    """Two copies of the demo catalog differing ONLY in latent_quality.csv.

    Generated rather than committed: they are the same seven products twice
    over, and a reviewer diffing two near-identical catalog directories learns
    nothing. `make eval` regenerates them, so the artifact stays reproducible.

    latent_quality is objective truth the shopper cannot read (Law 15) — it
    reaches them only as EXPERIENCED satisfaction after the fulfilment lag,
    which is exactly what makes F11 a test of the loop rather than of the mind.
    """
    import csv
    import shutil

    root = repo_root()
    src = root / "fixtures" / "demo-brand"
    out_root = Path(out_root or (eval_dir() / "fixtures"))
    made = []
    for name, q in (("quality-good", good), ("quality-bad", bad)):
        dst = out_root / name
        if dst.exists():
            shutil.rmtree(dst)
        dst.mkdir(parents=True)
        for f in ("catalog.csv", "creatives.json", "page_variants.json",
                  "personas.json", "goal_config.json", "promo_schedule.json"):
            if (src / f).exists():
                shutil.copy2(src / f, dst / f)
        with (src / "latent_quality.csv").open(newline="") as fh:
            rows = list(csv.DictReader(fh))
            fields = list(rows[0])
        for r in rows:
            r["latent_quality"] = f"{q:.2f}"
        with (dst / "latent_quality.csv").open("w", newline="") as fh:
            wr = csv.DictWriter(fh, fieldnames=fields)
            wr.writeheader()
            wr.writerows(rows)
        (dst / "README.md").write_text(
            f"# {name} — generated by shopsim.eval.harness.quality_catalogs\n\n"
            f"A copy of `fixtures/demo-brand` with every product's "
            f"`latent_quality` forced to **{q:.2f}**. Nothing else differs, so "
            f"the two arms of F11 share a view_hash and differ only in the one "
            f"hash that should differ: `latent_quality_hash`.\n\n"
            f"Regenerated by `make eval`; do not hand-edit.\n")
        made.append(dst)
    return made[0], made[1]
