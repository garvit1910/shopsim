"""ScriptedMind / ScriptedConsolidate — Atishay's C2 stand-in (CONTRACT.md, Phase 0.3).

Scalars only, deterministic, pure. The runner (Phase 3) drives this until
Garvit's real minds land at Sync S1; both must pass the same contract tests.

PLAN §0's "+0.05 to one concept per CLICK" is nominal shorthand: we emit
evidence.py's CLICK row (weight 0.10, target PREF_TARGET) and let the engine's
blend apply it, which reproduces the golden chain's first hop (0.45 -> 0.476)
instead of inventing a second update rule. Stand-in internals are not
contract-frozen.
"""

from __future__ import annotations

from typing import Any

from shopsim.contracts.enums import Action, Concept, EventType
from shopsim.contracts.evidence import EVIDENCE_TABLE, PREF_TARGET
from shopsim.contracts.types import (
    Appraisal,
    AppraisalTraits,
    ChoiceCoeffs,
    DecisionContext,
    Event,
    EvidenceDelta,
    EvidenceDeltaKey,
    Scalars,
    WorldviewSnapshot,
)

# Scripted/test-only threshold: an aware shopper clicks once adstock reaches this.
CLICK_ADSTOCK_THRESHOLD = 0.3

# Abstention floor: no trust belief = unknown brand = neutral-low credibility.
NO_BELIEF_CREDIBILITY = 0.2

_NEUTRAL = 0.5


class ScriptedConsolidate:
    """Pure consolidate(): only CLICKED earns preference evidence (Law 14 / F7)."""

    def consolidate(
        self, events: list[Event], snapshot: WorldviewSnapshot
    ) -> list[EvidenceDelta]:
        concept = snapshot.prefs[0][0] if snapshot.prefs else int(Concept.ECO_FRIENDLY)
        deltas: list[EvidenceDelta] = []
        for e in sorted(events, key=lambda e: (e.shopper_id, e.t)):
            if e.type is not EventType.CLICKED:
                continue
            deltas.append(
                EvidenceDelta(
                    key=EvidenceDeltaKey(kind="edge", subject=e.shopper_id, object=concept),
                    target=PREF_TARGET,
                    weight=EVIDENCE_TABLE[EventType.CLICKED].pref_weight,
                    cause_kind=EventType.CLICKED,
                    cause_id=e.subject,
                )
            )
        return deltas


class ScriptedMind:
    """C2 Mind protocol, scalars only (may read active_need scalars — sanctioned
    for the scripted stand-in per CONTRACT.md). Never reads ctx.motifs."""

    def appraise(self, ctx: DecisionContext, traits: AppraisalTraits) -> Appraisal:
        s = ctx.scalars
        credibility = (
            s.trust_belief.value if s.trust_belief is not None else NO_BELIEF_CREDIBILITY
        )
        return Appraisal(
            relevance=_NEUTRAL,
            credibility=credibility,
            brand_message_fatigue=_NEUTRAL,
            offer_attractiveness=_NEUTRAL,
            expectation_alignment=_NEUTRAL,
        )

    def decide(self, a: Appraisal, s: Scalars, coeffs: ChoiceCoeffs, rng: Any) -> Action:
        # rng deliberately unused: the stand-in is deterministic by construction.
        if s.active_need is not None and s.reference_price:
            price = min(s.reference_price.values()) * (1 + s.current_price_gap)
            if price <= s.active_need.budget_cap and price <= s.budget_left:
                return Action.BUY
        if s.aware_of_brand and s.adstock >= CLICK_ADSTOCK_THRESHOLD:
            return Action.CLICK
        return Action.IGNORE

    def consolidate(
        self, events: list[Event], snapshot: WorldviewSnapshot
    ) -> list[EvidenceDelta]:
        return ScriptedConsolidate().consolidate(events, snapshot)
