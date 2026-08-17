"""Perception cache (Law 13): one LLM call per unique stimulus, frozen on
disk, committed with runs. Keyed by sha256(canonical descriptor + prompt
version + model) so any change to what the model sees — or which model looks —
is a new cache entry; replays hash the whole directory into the manifest.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .schema import PerceivedCreative

# default cache location: <repo>/fixtures/perception-cache/
_REPO_MARKER = "fixtures"


def default_cache_dir(start: Path | str | None = None) -> Path:
    here = Path(start) if start else Path(__file__).resolve()
    for parent in here.parents:
        if (parent / _REPO_MARKER).is_dir():
            return parent / _REPO_MARKER / "perception-cache"
    raise FileNotFoundError("fixtures/ not found above " + str(here))


def stimulus_hash(descriptor: dict, prompt_version: str, model: str) -> str:
    blob = json.dumps(
        {"descriptor": descriptor, "prompt_version": prompt_version, "model": model},
        separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()


def _path(cache_dir: Path, creative_id: int, key: str) -> Path:
    return Path(cache_dir) / f"{creative_id}-{key[:16]}.json"


def load(cache_dir: Path, creative_id: int, key: str) -> dict | None:
    p = _path(cache_dir, creative_id, key)
    if not p.exists():
        return None
    entry = json.loads(p.read_text())
    if entry.get("hash") != key:
        return None  # stale filename collision; treat as a miss
    return entry


def store(
    cache_dir: Path,
    creative_id: int,
    key: str,
    descriptor: dict,
    prompt_version: str,
    model: str,
    output: dict,
) -> Path:
    p = _path(cache_dir, creative_id, key)
    p.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "hash": key,
        "creative_id": creative_id,
        "prompt_version": prompt_version,
        "model": model,
        "descriptor": descriptor,
        "output": output,
    }
    p.write_text(json.dumps(entry, indent=2, sort_keys=True) + "\n")
    return p


def cache_dir_hash(cache_dir: Path) -> str:
    """Content hash of the whole cache directory (manifest input)."""
    h = hashlib.sha256()
    for p in sorted(Path(cache_dir).glob("*.json")):
        h.update(p.name.encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def perceived_maps(
    perceived: dict[int, PerceivedCreative],
) -> tuple[dict[int, dict[int, float]], dict[int, dict[int, float]]]:
    """(claims, offers) keyed by creative — the ObjectiveView.from_catalog
    override format."""
    return (
        {cid: p.claims_dict for cid, p in perceived.items()},
        {cid: p.offers_dict for cid, p in perceived.items()},
    )
