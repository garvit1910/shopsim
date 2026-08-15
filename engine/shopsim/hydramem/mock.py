"""MockHydraMem — the C1 stand-in (CONTRACT.md).

Serves canned, schema-validated DecisionContexts from /fixtures/contexts/ so
the minds lane (Phase 2/4/5) never blocks on the real HydraMem. Every fixture
is validated on load; anything violating C1 (including Law-15 latent leaks)
refuses to load at all.

Fixture wrapper format:
    {"name": str, "stimulus_id": int, "index": bool (default true),
     "context": {scalars, motifs}}
`index: false` keeps a file as a schema fixture without serving it (used by
appendix_b_reference.json, which shares a (shopper, stimulus) key with the
twin pair).
"""

from __future__ import annotations

import json
from pathlib import Path

from ..contracts.types import DecisionContext


class MockHydraMem:
    def __init__(self, fixtures_dir: str | Path):
        contexts_dir = Path(fixtures_dir) / "contexts"
        if not contexts_dir.is_dir():
            raise FileNotFoundError(f"no contexts directory at {contexts_dir}")
        self._index: dict[tuple[int, int], DecisionContext] = {}
        self._names: dict[str, tuple[int, int]] = {}
        for path in sorted(contexts_dir.glob("*.json")):
            wrapper = json.loads(path.read_text())
            ctx = DecisionContext.from_dict(wrapper["context"])  # raises on C1 violations
            if not wrapper.get("index", True):
                continue
            key = (ctx.scalars.shopper_id, wrapper["stimulus_id"])
            if key in self._index:
                raise ValueError(f"duplicate canned context for {key} ({path.name})")
            self._index[key] = ctx
            self._names[wrapper["name"]] = key

    def get_decision_context(self, shopper_id: int, stimulus_id: int) -> DecisionContext:
        try:
            return self._index[(shopper_id, stimulus_id)]
        except KeyError:
            available = ", ".join(f"{n}={k}" for n, k in sorted(self._names.items()))
            raise KeyError(
                f"no canned context for shopper {shopper_id} x stimulus {stimulus_id}; "
                f"available: {available}"
            ) from None

    def by_name(self, name: str) -> DecisionContext:
        return self._index[self._names[name]]

    @property
    def cases(self) -> dict[str, tuple[int, int]]:
        return dict(self._names)
