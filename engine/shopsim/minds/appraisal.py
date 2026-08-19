"""Formula appraise() — P0 (Phase 2.3). The ONLY module whose source may
reference AppraisalTraits (Law 12; enforced by tests/test_registry.py's
source-scan — this module must never name the choice-coeffs type).

Five interpretable 0..1 dims from real DecisionContext motifs + scalars +
traits (+ the mind-bound StimulusFacts for claimed_pct — registry row 9's
stimulus-side input; see objective_view.py). Every input enters exactly once,
per the ENTRY_POINTS registry:

    preference_fit motif (strength × recency)  ┐
    goal_fit motif (strength × urgency)        ┴→ relevance         (rows 2, 3)
    trust_belief × trait trust_orientation      → credibility       (rows 5, 6)
    aware_of_brand                              → F2 cold gate      (row 7)
    brand_semantic_fatigue motif                → fatigue dim       (row 8)
    stimulus claimed_pct × trait deal_proneness → offer dim         (row 9)
    expectation_violation motif                 → 1 − alignment     (row 10)
    social_proof motif (valence x w_social)     → credibility       (row 20, P1)

Preference priors already live in the PREFERS weights behind preference_fit —
nothing here multiplies an affinity again. The novelty dim stays None;
concept_saturation motifs and habit / quality scalars present in a context are
deliberately ignored at P0. social_proof is reported whenever the motif is
present and only MOVES credibility when a config sets w_social > 0 (default
0.0) — so a run without the social layer is bit-for-bit the P0 run.
"""

from __future__ import annotations

from ..contracts.enums import MotifType
from ..contracts.types import Appraisal, AppraisalTraits, DecisionContext, Motif
from .calibration import DEFAULT_APPRAISAL_PARAMS, AppraisalParams
from .objective_view import StimulusFacts


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _strongest(ctx: DecisionContext, mtype: MotifType) -> Motif | None:
    best = None
    for m in ctx.motifs:
        if m.type is mtype and (best is None or (m.strength or 0.0) > (best.strength or 0.0)):
            best = m
    return best


def _most_trusted_peer(ctx: DecisionContext) -> Motif | None:
    """social_proof motifs carry `valence` and `peer_trust`, never `strength`
    (MOTIF_REQUIRED_FIELDS), so they need their own selector: the signal that
    counts is the one from the most trusted peer."""
    best = None
    for m in ctx.motifs:
        if m.type is MotifType.SOCIAL_PROOF and (
                best is None or (m.peer_trust or 0.0) > (best.peer_trust or 0.0)):
            best = m
    return best


def appraise(
    ctx: DecisionContext,
    traits: AppraisalTraits,
    stim: StimulusFacts | None = None,
    params: AppraisalParams = DEFAULT_APPRAISAL_PARAMS,
) -> Appraisal:
    s = ctx.scalars

    # -- relevance (rows 2 + 3) --------------------------------------------
    pref = _strongest(ctx, MotifType.PREFERENCE_FIT)
    pf = pref.strength * (pref.recency if pref.recency is not None else 1.0) if pref else 0.0
    goal = _strongest(ctx, MotifType.GOAL_FIT)
    gf = goal.strength * goal.urgency if goal else 0.0
    relevance = _clamp01(params.w_pref * pf + params.w_goal * gf)

    # -- credibility (rows 5 + 6): abstention floors, never invented ---------
    tilt = params.trust_orientation_span * (traits.trust_orientation - 0.5)
    b = s.trust_belief
    if b is None:
        credibility = _clamp01(params.no_belief_credibility + tilt)
    else:
        # shrink the belief value toward neutral by (1 − confidence); the
        # orientation tilt only fills the uncertain remainder, so a
        # high-confidence belief is barely tiltable (F10-adjacent behavior).
        v_eff = 0.5 + (b.value - 0.5) * b.confidence
        credibility = _clamp01(v_eff + tilt * (1.0 - b.confidence))

    # -- social_proof (row 20, P1): what people they trust actually lived ----
    # Read as-of the previous tick by retrieval, so there is no intra-tick
    # feedback loop. It joins CREDIBILITY rather than standing alone (PLAN 2.3:
    # "credibility <- trust belief ... + social_proof valence"), which keeps the
    # dimension count at the calibrated five; the dim is still reported so the
    # trace and the dashboard can show that the path was there.
    peer = _most_trusted_peer(ctx)
    social = peer.valence if peer is not None else None
    if social is not None and params.w_social:
        credibility = _clamp01(credibility + params.w_social * (2.0 * social - 1.0))

    # -- brand_message_fatigue (row 8) -------------------------------------
    fat = _strongest(ctx, MotifType.BRAND_SEMANTIC_FATIGUE)
    fatigue = _clamp01(fat.strength) if fat else 0.0

    # -- offer_attractiveness (row 9): the PERCEIVED deal -------------------
    # (the realized price gap enters decide() only — row 13)
    claimed_pct = stim.max_claimed_pct if stim is not None else 0.0
    offer = _clamp01(claimed_pct / params.offer_norm) * traits.deal_proneness

    # -- expectation_alignment (row 10): pages carry violation motifs -------
    viol = _strongest(ctx, MotifType.EXPECTATION_VIOLATION)
    alignment = _clamp01(1.0 - viol.strength) if viol else 1.0

    # -- F2 cold gate (row 7): unaware + no paths + no belief ⇒ ≈ 0 ---------
    if not s.aware_of_brand and b is None and not ctx.motifs:
        relevance = 0.0
        credibility *= params.cold_credibility_factor
        offer *= params.cold_offer_factor

    return Appraisal(
        relevance=relevance,
        credibility=credibility,
        brand_message_fatigue=fatigue,
        offer_attractiveness=offer,
        expectation_alignment=alignment,
        social_proof=social,
    )
