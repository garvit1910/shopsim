"""Calibration layer — every tunable mind constant in one greppable place.

These are Phase-4-tunable calibration parameters, NOT contract constants:
evidence.py (Appendix F) is frozen by hash and never touched here. Values are
grounded in /eval/market-research.md (2026-08-17) and validated by
engine/bench/calibrate_choice.py against the researched base-rate bands:

    P(CLICK | exposure)      0.5–2%   (display/social CTR benchmarks)
    P(BROWSE | visit)        ~0.5     (1 − typical bounce)
    P(CART  | browse)        0.10–0.20 (fashion add-to-cart ~7% of sessions)
    P(BUY   | cart)          0.24–0.28 (1 − cart abandonment 72–76%)

Stage keys are Action values: "CLICK", "BROWSE", "CART", "BUY".
"""

from __future__ import annotations

from dataclasses import dataclass, field

# The five P0 appraisal dimensions, in registry order.
APPRAISAL_DIMS = (
    "relevance",
    "credibility",
    "brand_message_fatigue",
    "offer_attractiveness",
    "expectation_alignment",
)

STAGES = ("CLICK", "BROWSE", "CART", "BUY")


@dataclass(frozen=True)
class AppraisalParams:
    # relevance = clamp01(w_pref·(pref strength × recency) + w_goal·(need strength × urgency))
    w_pref: float = 0.6
    w_goal: float = 0.8
    # credibility abstention floor for an unknown brand (anchored to the
    # scripted stand-in's NO_BELIEF_CREDIBILITY) + how far trust_orientation
    # can tilt low-confidence credibility either way.
    no_belief_credibility: float = 0.2
    trust_orientation_span: float = 0.4
    # offer_attractiveness = clamp01(claimed_pct / offer_norm) × deal_proneness;
    # 30% saturates the perceived deal (routine promo depth tops out 20–30%,
    # market-research §3).
    offer_norm: float = 0.30
    # F2 cold gate (unaware + no paths + no belief => engagement ≈ 0):
    cold_credibility_factor: float = 0.5
    cold_offer_factor: float = 0.25
    # Social proof (registry row 20, P1 — CONTRACT v3.8-draft). How far a
    # trusted peer's experience can move credibility: contribution is
    # w_social x (2 x valence - 1), so a neutral peer signal (valence 0.5)
    # moves nothing and the term is symmetric around it. DEFAULT 0.0 — the
    # motif is retrieved and reported but never read, which is what keeps
    # every pre-social run byte-identical. A social-enabled config sets it.
    w_social: float = 0.0


@dataclass(frozen=True)
class ChoiceParams:
    """decide() utility constants. Per-shopper heterogeneity lives in
    ChoiceCoeffs (impulsivity τ, price_sensitivity, budget, stage_bases θ_s);
    everything population-level lives here."""

    # W[stage][dim] — relevance matters far more at CART/BUY than CLICK, so
    # goal-gating emerges from the single relevance entry point (Law 12).
    stage_weights: tuple[tuple[str, tuple[tuple[str, float], ...]], ...] = (
        ("CLICK", (("relevance", 1.2), ("credibility", 0.6),
                   ("brand_message_fatigue", -1.0), ("offer_attractiveness", 0.8),
                   ("expectation_alignment", 0.3))),
        ("BROWSE", (("relevance", 1.0), ("credibility", 0.8),
                    ("brand_message_fatigue", -0.6), ("offer_attractiveness", 0.6),
                    ("expectation_alignment", 1.5))),
        ("CART", (("relevance", 1.6), ("credibility", 1.0),
                  ("brand_message_fatigue", -0.3), ("offer_attractiveness", 1.0),
                  ("expectation_alignment", 0.8))),
        ("BUY", (("relevance", 2.2), ("credibility", 1.4),
                 ("brand_message_fatigue", -0.2), ("offer_attractiveness", 1.0),
                 ("expectation_alignment", 0.6))),
    )
    # rows 11+12: the single asset-repetition entry (γ·adstock − δ·wearout)
    gamma_adstock: float = 0.5
    adstock_cap: float = 2.0
    delta_wearout: float = 0.8
    wearout_free_exposures: int = 2  # exposures_72h under this wear nothing
    wearout_scale: float = 4.0  # further exposures to saturate wearout
    # row 13: realized price, losses ×2
    loss_aversion: float = 2.0
    # row 4: active-need budget-cap damp on BUY
    budget_cap_damp: float = 0.25

    def weights(self, stage: str) -> dict[str, float]:
        for name, dims in self.stage_weights:
            if name == stage:
                return dict(dims)
        raise KeyError(f"no stage weights for {stage!r}")


# Population-default stage thresholds θ_s (segments shift these via
# theta_adjust; shoppers carry them in ChoiceCoeffs.stage_bases). Derived so a
# typical warm-shopper appraisal lands in the researched bands above with
# τ = 1.0; verified by bench/calibrate_choice.py.
DEFAULT_STAGE_BASES: tuple[tuple[str, float], ...] = (
    ("CLICK", 6.0),
    ("BROWSE", 2.3),
    ("CART", 3.7),
    ("BUY", 3.2),
)

DEFAULT_APPRAISAL_PARAMS = AppraisalParams()
DEFAULT_CHOICE_PARAMS = ChoiceParams()
