"""FormulaMind — the C2 Mind implementation (P0 backbone).

One instance per (run, stimulus): the engine/runner constructs it with the
frozen ObjectiveView and binds the stimulus under decision via
for_stimulus(). All three stages stay pure functions of their arguments plus
that frozen view (CONTRACT v3.2 convention, pending ack).

This facade only forwards; Law-12 separation lives in the implementation
modules (appraisal.py may name traits, choice.py may name coeffs, never the
other way — source-scanned in tests/test_registry.py).
"""

from __future__ import annotations

from typing import Any

from ..contracts.enums import Action
from ..contracts.types import (
    Appraisal,
    AppraisalTraits,
    ChoiceCoeffs,
    DecisionContext,
    Event,
    EvidenceDelta,
    Scalars,
    WorldviewSnapshot,
)
from . import appraisal, choice, consolidation
from .calibration import (
    DEFAULT_APPRAISAL_PARAMS,
    DEFAULT_CHOICE_PARAMS,
    AppraisalParams,
    ChoiceParams,
)
from .objective_view import ObjectiveView


class FormulaMind:
    def __init__(
        self,
        view: ObjectiveView,
        stimulus_id: int | None = None,
        appraisal_params: AppraisalParams = DEFAULT_APPRAISAL_PARAMS,
        choice_params: ChoiceParams = DEFAULT_CHOICE_PARAMS,
    ):
        self.view = view
        self.appraisal_params = appraisal_params
        self.choice_params = choice_params
        self._stim = view.facts(stimulus_id) if stimulus_id is not None else None

    def for_stimulus(self, stimulus_id: int) -> "FormulaMind":
        return FormulaMind(self.view, stimulus_id, self.appraisal_params, self.choice_params)

    def appraise(self, ctx: DecisionContext, traits: AppraisalTraits) -> Appraisal:
        return appraisal.appraise(ctx, traits, stim=self._stim, params=self.appraisal_params)

    def decide(self, a: Appraisal, s: Scalars, coeffs: ChoiceCoeffs, rng: Any) -> Action:
        kind = self._stim.kind if self._stim is not None else "creative"
        return choice.decide(a, s, coeffs, rng, kind=kind, params=self.choice_params)

    def consolidate(
        self, events: list[Event], snapshot: WorldviewSnapshot
    ) -> list[EvidenceDelta]:
        return consolidation.consolidate(events, snapshot, view=self.view)
