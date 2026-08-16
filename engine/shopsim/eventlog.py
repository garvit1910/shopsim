"""JSONL event log + run-manifest hashing (Law 13).

The JSONL log is the replay source of truth: episodic events AND the
NEED_ACTIVATED/EXPIRED/SATISFIED lifecycle records land here; worldview
supersessions are recomputed on replay from events + evidence.py, never
logged. replay() itself is Phase 3 — this module is its input format.

Record shape (one JSON object per line):
    {"type": "SAW", "shopper_id": 1000042, "t": 1755150000, "run": 0,
     "subject": 2000003, ...payload props (price/sat/...)}
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, IO

from .contracts.types import Event


class JsonlEventLog:
    """Append-only writer. Callers append BEFORE graph writes (write-ahead:
    a crash mid-batch is re-derivable from the log)."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh: IO[str] = open(self.path, "a", encoding="utf-8")

    def append(self, record: dict[str, Any]) -> None:
        self._fh.write(json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n")

    def append_event(self, event: Event) -> None:
        rec: dict[str, Any] = {
            "type": event.type.value,
            "shopper_id": event.shopper_id,
            "t": event.t,
            "run": event.run,
            "subject": event.subject,
        }
        rec.update({k: v for k, v in event.props})
        self.append(rec)

    def flush(self) -> None:
        self._fh.flush()

    def close(self) -> None:
        self._fh.flush()
        self._fh.close()

    def __enter__(self) -> "JsonlEventLog":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def read_events(path: Path | str) -> list[dict[str, Any]]:
    """Load every record (tests + Phase-3 replay)."""
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_source(source: Path | str | bytes | None) -> str | None:
    if source is None:
        return None
    if isinstance(source, bytes):
        return _sha256(source)
    return _sha256(Path(source).read_bytes())


def manifest_hashes(
    *,
    perception_cache: Path | str | bytes | None = None,
    appraisal_cache: Path | str | bytes | None = None,
    goal_config: Path | str | bytes | None = None,
    latent_quality: Path | str | bytes | None = None,
    social_config: Path | str | bytes | None = None,
) -> dict[str, str | None]:
    """The five manifest hashes (+ social, P1). evidence_hash always comes
    from the contracts/evidence.py file bytes — the single source of
    behavioral learning; replays refuse to run if any hash changed."""
    from .contracts import evidence

    hashes: dict[str, str | None] = {
        "evidence_hash": _hash_source(Path(evidence.__file__)),
        "perception_cache_hash": _hash_source(perception_cache),
        "appraisal_cache_hash": _hash_source(appraisal_cache),
        "goal_config_hash": _hash_source(goal_config),
        "latent_quality_hash": _hash_source(latent_quality),
    }
    social = _hash_source(social_config)
    if social is not None:
        hashes["social_config_hash"] = social
    return hashes
