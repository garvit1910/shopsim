"""HydraMem — the six-state worldview store.

`mock.MockHydraMem` is Garvit's C1 stand-in (canned contexts from fixtures).
`real.HydraMem` (Atishay, Phase 1) is the graph-backed implementation with
the same `get_decision_context` signature; it passes the same contract tests
(run them with SHOPSIM_HYDRAMEM=real against a live HydraDB).
"""

from .mock import MockHydraMem
from .real import HydraMem

__all__ = ["MockHydraMem", "HydraMem"]
