"""decide() — the staged behavioral choice model, P0 (Phase 2.4).

Law 12: this module must never name the appraisal-traits type (source-
scanned); the decide() signature carries no traits parameter. Inputs:
Appraisal + raw Scalars + ChoiceCoeffs + a seeded rng (exposes .random()).

Funnel (two-phase, agreed 2026-08-17):
    creative context → one CLICK gate            → IGNORE | CLICK
    page context     → BROWSE → CART → BUY gates → BOUNCE | ABANDON | CART* | BUY
Each gate: U_s = Σ_d W[s,d]·A[d] + γ·min(adstock, cap) − δ·wearout
           (+ post-click realized-price term, losses ×2)
           P(advance) = σ((U_s − θ_s)/τ),  τ = coeffs.impulsivity (row 15)
One rng draw per gate reached, in fixed stage order — same seed ⇒ same
action sequence. A page walk that passes CART but fails the BUY gate returns
CART (the cart persists; a later decision resumes at BUY via scalars.cart —
row 18).

Price for the BUY guards (rows 4 + 16) is the sanctioned derivation
price = reference_price × (1 + current_price_gap) — exact whenever the
shopper has a reference price (anyone past PRICE_SEEN does); with no
reference price the guards cannot fire. The hard budget block zeroes the BUY
probability but still consumes the gate's draw, keeping rng streams aligned
across guard differences (twin runs stay comparable).
"""

from __future__ import annotations

import math
from typing import Any

from ..contracts.enums import Action
from ..contracts.types import Appraisal, ChoiceCoeffs, Scalars
from .calibration import DEFAULT_CHOICE_PARAMS, ChoiceParams

_DIM_VALUES = {
    "relevance": lambda a: a.relevance,
    "credibility": lambda a: a.credibility,
    "brand_message_fatigue": lambda a: a.brand_message_fatigue,
    "offer_attractiveness": lambda a: a.offer_attractiveness,
    "expectation_alignment": lambda a: a.expectation_alignment,
}


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def _wearout(exposures_72h: int, params: ChoiceParams) -> float:
    over = exposures_72h - params.wearout_free_exposures
    return max(0.0, min(1.0, over / params.wearout_scale))


def asset_wearout(exposures_72h: int, params: ChoiceParams = DEFAULT_CHOICE_PARAMS) -> float:
    """The 0..1 asset-repetition level decide() subtracts (row 12), exposed as
    a pure public helper for MEASUREMENT (CONTRACT v3.8-draft: the report's
    fatigue `asset` channel must be the number the utility actually used, not a
    re-derivation). Read-only — calling it creates no second entry point, the
    same way stage_probabilities() exposes the gate math without deciding."""
    return _wearout(exposures_72h, params)


def _price(s: Scalars) -> float | None:
    """Sanctioned derivation; None = unknown (no reference price yet)."""
    if not s.reference_price:
        return None
    ref = min(s.reference_price.values())
    if ref <= 0:
        return None
    return ref * (1.0 + s.current_price_gap)


def _gate_probability(
    stage: str, a: Appraisal, s: Scalars, coeffs: ChoiceCoeffs, params: ChoiceParams
) -> float:
    weights = params.weights(stage)
    u = sum(w * _DIM_VALUES[dim](a) for dim, w in weights.items())
    u += params.gamma_adstock * min(s.adstock, params.adstock_cap)  # row 11
    u -= params.delta_wearout * _wearout(s.exposures_72h, params)  # row 12
    if stage != "CLICK":  # row 13: realized price, post-click stages only
        gap = s.current_price_gap
        u -= coeffs.price_sensitivity * (params.loss_aversion * gap if gap > 0 else gap)
    return _sigmoid((u - coeffs.stage_base(stage)) / coeffs.impulsivity)


def _buy_probability(
    a: Appraisal, s: Scalars, coeffs: ChoiceCoeffs, params: ChoiceParams
) -> float:
    p = _gate_probability("BUY", a, s, coeffs, params)
    price = _price(s)
    if price is not None:
        if price > s.budget_left:  # row 16: hard block
            return 0.0
        if s.active_need is not None and price > s.active_need.budget_cap:
            p *= params.budget_cap_damp  # row 4: ×0.25 damp
    return p


def stage_probabilities(
    a: Appraisal,
    s: Scalars,
    coeffs: ChoiceCoeffs,
    kind: str = "creative",
    params: ChoiceParams = DEFAULT_CHOICE_PARAMS,
) -> dict[str, float]:
    """Pure, rng-free view of the same gate math decide() draws against
    (CONTRACT v3.5-draft item 4 — the Phase-5 decision-preview surface).
    Creative contexts expose the CLICK gate; page contexts the
    BROWSE/CART/BUY gates, BUY including the budget guards (rows 4 + 16).
    The decision path is unchanged and never calls this."""
    if kind == "creative":
        return {"CLICK": _gate_probability("CLICK", a, s, coeffs, params)}
    if kind != "page":
        raise ValueError(f"unknown stimulus kind {kind!r}")
    return {
        "BROWSE": _gate_probability("BROWSE", a, s, coeffs, params),
        "CART": _gate_probability("CART", a, s, coeffs, params),
        "BUY": _buy_probability(a, s, coeffs, params),
    }


def decide(
    a: Appraisal,
    s: Scalars,
    coeffs: ChoiceCoeffs,
    rng: Any,
    kind: str = "creative",
    params: ChoiceParams = DEFAULT_CHOICE_PARAMS,
) -> Action:
    if kind == "creative":
        if rng.random() < _gate_probability("CLICK", a, s, coeffs, params):
            return Action.CLICK
        return Action.IGNORE

    if kind != "page":
        raise ValueError(f"unknown stimulus kind {kind!r}")

    # row 18: resume at BUY when a stimulus product is already carted
    in_cart = bool(set(s.cart) & set(s.reference_price))
    if not in_cart:
        if rng.random() >= _gate_probability("BROWSE", a, s, coeffs, params):
            return Action.BOUNCE
        if rng.random() >= _gate_probability("CART", a, s, coeffs, params):
            return Action.BROWSE  # deepest stage reached; no cart, so no ABANDON
    if rng.random() < _buy_probability(a, s, coeffs, params):
        return Action.BUY
    # a fresh cart survives the failed BUY gate (resume later via scalars.cart);
    # a resumed cart that fails BUY again is abandoned.
    return Action.CART if not in_cart else Action.ABANDON
