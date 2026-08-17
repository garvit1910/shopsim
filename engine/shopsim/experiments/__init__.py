"""Phase 4 — Experiment Adapters v3 (CONTRACT v3.4-draft).

Adapters expand experiment specs into ordinary run_configs and drive the
REAL Phase-3 runner through its programmatic API (RunConfig / RunStore /
SimRunner / replay.branch) — one engine, three stimulus feeds. Every
experiment lever lives inside the generated run_config.json, so config_hash
covers it and branch/resume semantics are untouched. No second runner, no
raw Cypher, no behavioral logic outside the Phase-2 minds.
"""

from .specs import load_spec  # noqa: F401
