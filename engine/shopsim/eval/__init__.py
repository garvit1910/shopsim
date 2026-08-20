"""Phase 7 — calibration & evals.

Three tiers, because cost should match value:

  * **analytic**  pure mind arithmetic over the real population factory and the
    real ObjectiveView — no database, milliseconds, any number of seeds. Carries
    F1, F2, F3, F6, F8, F10, the rank-agreement study, and the whole calibration
    fit.
  * **scenario**  real runs on the live store through the ordinary experiment
    path. Carries F4, F5, F7b, F9, F11, F12 — the laws that only exist once
    learning, retrieval and the graph are in the loop.
  * **audit**     assertions over artifacts a finished run already wrote. F7a
    lives here: `provenance_coverage.prefers.cause_kinds` is computed by
    Phase 6 already, so the invariant is an assertion, not a new sweep.

Nothing in this package is imported by the engine's decision path. It reads the
same public surfaces the runner uses (`appraise`, `stage_probabilities`,
`evidence.blend`) so a law can never drift from the behaviour it certifies.
"""

from .laws import LawResult, TIERS  # noqa: F401
