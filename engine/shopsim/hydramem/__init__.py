"""HydraMem — the six-state worldview store.

`mock.MockHydraMem` is Garvit's C1 stand-in (canned contexts from fixtures).
The real HydraMem (Atishay, Phase 1) lands here as `real.py` with the same
`get_decision_context` signature and must pass the same contract tests.
"""

from .mock import MockHydraMem

__all__ = ["MockHydraMem"]
