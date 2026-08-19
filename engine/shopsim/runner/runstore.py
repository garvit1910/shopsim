"""Run registry, run directories, atomic file writes, manifest assembly.

Layout (CONTRACT v3.3):
    <repo>/runs/registry.json      {"next_run_index": N, "runs": [...]}
    <repo>/runs/<run_id>/          events.jsonl, manifest.json, progress.json,
                                   results.json, results_state.json

Every run gets a fresh run_index (fresh shopper/belief id block). The registry
starts at run_index 10 — blocks 0-9 are reserved for the story graph and the
integration tests (test_minds_real uses block 8).

results.json and manifest.json contain no wall-clock values, so a same-seed
rerun is byte-identical (the S1 hash checkpoint); wall time lives only in
progress.json.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import hashlib

from ..eventlog import manifest_hashes
from .config import RunConfig, canonical_json

FIRST_RUN_INDEX = 10


def write_json_atomic(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, sort_keys=True) + "\n")
    os.replace(tmp, path)


class RunStore:
    def __init__(self, root: Path):
        self.runs_dir = root / "runs"
        self.runs_dir.mkdir(exist_ok=True)
        self.registry_path = self.runs_dir / "registry.json"

    def _registry(self) -> dict:
        if self.registry_path.exists():
            return json.loads(self.registry_path.read_text())
        return {"next_run_index": FIRST_RUN_INDEX, "runs": []}

    def allocate(self, cfg: RunConfig, arm_name: str, kind: str = "run") -> tuple[int, Path]:
        reg = self._registry()
        run_index = reg["next_run_index"]
        reg["next_run_index"] = run_index + 1
        run_id = f"r{run_index:03d}-{cfg.label}-{arm_name}"
        run_dir = self.runs_dir / run_id
        run_dir.mkdir()
        reg["runs"].append({
            "run_id": run_id, "run_index": run_index, "label": cfg.label,
            "arm": arm_name, "kind": kind, "seed": cfg.seed,
            "config_hash": cfg.config_hash(arm_name), "dir": str(run_dir),
            "status": "created",
        })
        write_json_atomic(self.registry_path, reg)
        return run_index, run_dir

    def set_status(self, run_id: str, status: str) -> None:
        reg = self._registry()
        for row in reg["runs"]:
            if row["run_id"] == run_id:
                row["status"] = status
        write_json_atomic(self.registry_path, reg)

    def find(self, run_id_or_dir: str) -> dict:
        reg = self._registry()
        for row in reg["runs"]:
            if row["run_id"] == run_id_or_dir or row["dir"] == str(run_id_or_dir):
                return row
        # tolerate a path to the run dir
        p = Path(run_id_or_dir)
        for row in reg["runs"]:
            if Path(row["dir"]).resolve() == p.resolve():
                return row
        raise KeyError(f"unknown run {run_id_or_dir!r}")

    def latest_for(self, label: str, arm: str) -> dict:
        rows = [r for r in self._registry()["runs"]
                if r["label"] == label and r["arm"] == arm]
        if not rows:
            raise KeyError(f"no registered run for label={label!r} arm={arm!r}")
        return rows[-1]

    def rows(self) -> list[dict]:
        return self._registry()["runs"]


def build_manifest(cfg: RunConfig, arm_name: str, run_index: int, view_hash: str) -> dict:
    """The run manifest: Law-13 hashes + run identity. Replays/resumes refuse
    on mismatch (resume: all hashes; branch: all but config_hash)."""
    hashes = manifest_hashes(
        perception_cache=_dir_bytes(cfg.perception_cache),
        appraisal_cache=None,  # P0: no LLM appraisal
        goal_config=cfg.goal_config_path,
        latent_quality=cfg.catalog_dir / "latent_quality.csv",
    )
    social = {}
    if cfg.social is not None:
        # C3 lists social_config_hash as optional, so it is ABSENT (not null)
        # when there is no social layer: every pre-v3.8 manifest, and every
        # social-off run, stays byte-identical (CONTRACT v3.8-draft).
        social["social_config_hash"] = hashlib.sha256(
            canonical_json(cfg.raw["population"]["social"]).encode()).hexdigest()
    return {
        **hashes,
        **social,
        "config_hash": cfg.config_hash(arm_name),
        "view_hash": view_hash,
        "seed": cfg.seed,
        "run_index": run_index,
        "label": cfg.label,
        "arm": arm_name,
        "t0": cfg.t0,
        "tick_seconds": cfg.tick_seconds,
        "ticks": cfg.ticks,
        "mind": {"decide": cfg.mind_decide, "consolidate": cfg.mind_consolidate},
    }


def _dir_bytes(d: Path) -> bytes:
    """Canonical bytes of a directory of files (perception cache)."""
    parts = []
    for p in sorted(Path(d).glob("*.json")):
        parts.append(p.name.encode() + b"\0" + p.read_bytes())
    return b"\0".join(parts)


SHARED_HASH_KEYS = (
    "evidence_hash", "perception_cache_hash", "goal_config_hash",
    "latent_quality_hash", "view_hash",
)


def check_hashes(recorded: dict, current: dict, *, include_config: bool) -> list[str]:
    keys = SHARED_HASH_KEYS + (("config_hash",) if include_config else ())
    return [
        f"{k}: recorded {recorded.get(k)} != current {current.get(k)}"
        for k in keys
        if recorded.get(k) != current.get(k)
    ]
