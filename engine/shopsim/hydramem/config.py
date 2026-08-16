"""Connection config for the real HydraMem (Phase 1).

Environment overrides:
    SHOPSIM_HYDRA_URI         Bolt URI (default bolt://127.0.0.1:7687)
    SHOPSIM_HYDRA_TOKEN       literal bearer token
    SHOPSIM_HYDRA_TOKEN_FILE  path to a token file
    SHOPSIM_HYDRA_WORKERS     parallel session count for grouped ops

Without overrides the token is read from <repo>/infra/hydradb-data/auth-token
(created by infra/up.sh), found by walking up from this file.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_BOLT_URI = "bolt://127.0.0.1:7687"
DEFAULT_WORKERS = 8


def _default_token_file() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "infra" / "hydradb-data" / "auth-token"
        if candidate.exists():
            return candidate
    return None


@dataclass(frozen=True)
class HydraConfig:
    bolt_uri: str = DEFAULT_BOLT_URI
    token: str = ""
    workers: int = DEFAULT_WORKERS

    @classmethod
    def from_env(cls) -> "HydraConfig":
        uri = os.environ.get("SHOPSIM_HYDRA_URI", DEFAULT_BOLT_URI)
        token = os.environ.get("SHOPSIM_HYDRA_TOKEN", "")
        if not token:
            tf = os.environ.get("SHOPSIM_HYDRA_TOKEN_FILE")
            path = Path(tf) if tf else _default_token_file()
            if path is None or not path.exists():
                raise FileNotFoundError(
                    "HydraDB auth token not found. Set SHOPSIM_HYDRA_TOKEN or "
                    "SHOPSIM_HYDRA_TOKEN_FILE, or run infra/up.sh once."
                )
            token = path.read_text().strip()
        workers = int(os.environ.get("SHOPSIM_HYDRA_WORKERS", str(DEFAULT_WORKERS)))
        return cls(bolt_uri=uri, token=token, workers=workers)
