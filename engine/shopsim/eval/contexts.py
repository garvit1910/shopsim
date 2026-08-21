"""The analytic tier's world: real populations, real catalogs, synthetic contexts.

`bench/calibrate_choice.py` established the shape (generate the authored
population, build contexts for a plausible exposure mix, average the gate
probabilities, compare against the researched bands). This module is that idea
made reusable and parameterised, so every analytic law and the calibration fit
share ONE context factory instead of each inventing its own.

Nothing here re-implements mind arithmetic. Contexts go through
`DecisionContext.from_dict`, so the same validator that guards a real retrieval
guards a synthetic one; scoring goes through the real `appraise()` and the real
`stage_probabilities()`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..contracts.types import DecisionContext
from ..minds.appraisal import appraise
from ..minds.calibration import (
    DEFAULT_APPRAISAL_PARAMS,
    DEFAULT_CHOICE_PARAMS,
    DEFAULT_STAGE_BASES,
)
from ..minds.choice import stage_probabilities
from ..minds.objective_view import ObjectiveView, StimulusFacts
from ..population import PopulationConfig, generate_population, load_segment_specs


def repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "fixtures").is_dir() and (parent / "engine").is_dir():
            return parent
    raise RuntimeError("repo root not found (needs fixtures/ + engine/)")


@dataclass(frozen=True)
class Profile:
    """A named calibration: exactly the three objects a run's `calibration`
    block resolves to, so an analytic result and a real run can be compared
    without a translation layer."""

    name: str
    appraisal: object = DEFAULT_APPRAISAL_PARAMS
    choice: object = DEFAULT_CHOICE_PARAMS
    stage_bases: tuple = DEFAULT_STAGE_BASES

    @classmethod
    def from_block(cls, name: str, block: dict | None) -> "Profile":
        from ..runner.config import parse_calibration

        ap, cp, sb = parse_calibration(block or None)
        return cls(name=name, appraisal=ap, choice=cp, stage_bases=sb)

    @classmethod
    def load(cls, path: Path | str) -> "Profile":
        import json

        raw = json.loads(Path(path).read_text())
        return cls.from_block(raw.get("name", Path(path).stem),
                              raw.get("calibration", raw))


def population(seed: int, size: int, *, personas: str | Path | None = None,
               stage_bases=DEFAULT_STAGE_BASES):
    root = repo_root()
    path = Path(personas) if personas else root / "fixtures" / "demo-brand" / "personas.json"
    return generate_population(PopulationConfig(
        seed=seed, population_size=size, segments=load_segment_specs(path),
        stage_bases=stage_bases))


def catalog_view(catalog: str | Path = "fixtures/demo-brand",
                 cache: str | Path | None = None) -> ObjectiveView:
    """The frozen view a run would build, including PERCEIVED claims when the
    catalog ships a perception cache (nisolo does; demo-brand's authored
    creatives.json is the fallback the view already handles)."""
    root = repo_root()
    cdir = root / catalog if not Path(catalog).is_absolute() else Path(catalog)
    if cache is None:
        guess = cdir / "perception-cache"
        cache = guess if guess.is_dir() else root / "fixtures" / "perception-cache"
    from ..perception.cache import perceived_maps
    from ..perception.perceive import perceive_catalog

    def _offline(*_a, **_k):
        raise RuntimeError("analytic tier is offline: perception comes from the cache")

    perceived, calls = perceive_catalog(cdir, cache_dir=Path(cache), call=_offline)
    assert calls == 0
    claims, offers = perceived_maps(perceived)
    return ObjectiveView.from_catalog(cdir, claims, offers)


# ---------------------------------------------------------------------------
# context construction
# ---------------------------------------------------------------------------

# The exposure-context mix a warm campaign actually reaches, as shares of an
# exposed audience. Carried over from bench/calibrate_choice.py's MIX and
# extended with the two states a 30-60 day run spends most of its impressions
# in, which the original mix had no row for:
#   learned   the shopper has engaged before, so a LEARNED PREFERS edge is what
#             preference_fit reads (the dominant state after ~week one)
#   fatigued  same, plus a saturating brand_semantic_fatigue motif
DEFAULT_MIX: tuple[tuple[str, float], ...] = (
    ("cold", 0.20),      # unaware, no paths, no belief  -> the F2 gate
    ("aware", 0.28),     # saw the brand, no motif hits
    ("prior_hit", 0.18),  # a seeded preference prior matches the creative
    ("learned", 0.22),   # a learned preference matches it
    ("fatigued", 0.08),  # learned + heavy same-story repetition
    ("goal_on", 0.04),   # in-market: an active need in the offered category
)

_CASE_DEFAULTS = {
    #            pref   recency fatigue adstock exp72 aware trust  need
    "cold":      (None, None,   None,   0.0,    0,    False, None,  False),
    "aware":     (None, None,   None,   0.9,    1,    True,  None,  False),
    "prior_hit": (0.55, 0.85,   None,   1.2,    2,    True,  0.60,  False),
    "learned":   (0.72, 0.90,   0.18,   1.6,    2,    True,  0.62,  False),
    "fatigued":  (0.72, 0.90,   0.75,   2.0,    5,    True,  0.62,  False),
    "goal_on":   (0.72, 0.90,   0.20,   1.6,    2,    True,  0.65,  True),
}


def make_context(case: str, *, kind: str = "creative", shopper_id: int = 1_000_041,
                 price_gap: float = -0.05, budget_left: float = 240.0,
                 ref_price: float | None = 39.0, violation: float | None = None,
                 exposures_72h: int | None = None, adstock: float | None = None,
                 pref_strength: float | None = None,
                 fatigue: float | None = None,
                 in_cart: bool = False,
                 need: tuple[float, float, float] | None = None) -> DecisionContext:
    """One synthetic DecisionContext. Every override is explicit so a law can
    sweep exactly one input (F1 sweeps exposures_72h, F3 sweeps the price gap)
    while the rest of the context stays fixed."""
    d = _CASE_DEFAULTS[case]
    pw, prec, fat, ads, e72, aware, trust_v, has_need = d
    if pref_strength is not None:
        pw = pref_strength
        prec = prec if prec is not None else 0.9
    if fatigue is not None:
        fat = fatigue
    if adstock is not None:
        ads = adstock
    if exposures_72h is not None:
        e72 = exposures_72h

    motifs: list[dict] = []
    # A page carries no CLAIMS, so preference_fit and brand fatigue cannot fire
    # there (hydramem/reads.py: both iterate stim.claims, empty for pages).
    if kind == "creative":
        if pw:
            motifs.append({"type": "preference_fit", "strength": pw, "evidence": 2.0,
                           "recency": prec, "path": [shopper_id, "PREFERS", 5003,
                                                     "CLAIMS", 2000003]})
        if fat:
            motifs.append({"type": "brand_semantic_fatigue", "strength": fat,
                           "recency": 0.9, "brand": 6001,
                           "path": [shopper_id, "SAW", 2000001, "CLAIMS", 5003,
                                    "CLAIMS", 2000003]})
    if violation is not None and kind == "page":
        motifs.append({"type": "expectation_violation", "strength": violation,
                       "path": [shopper_id, "EXPECTS", 5003, "NOT_SHOWN_BY", 4000002]})

    active_need = None
    if has_need or need is not None:
        strength, urgency, cap = need or (0.8, 0.7, 220.0)
        active_need = {"category": 5504, "strength": strength,
                       "urgency": urgency, "budget_cap": cap}
        motifs.append({"type": "goal_fit", "strength": strength, "urgency": urgency,
                       "path": [shopper_id, "NEEDS", 5504, "IN_CATEGORY", 3000001,
                                "OFFERS" if kind == "creative" else "PAGE_FOR", 2000003]})

    trust = None
    if trust_v is not None:
        from ..contracts import evidence as ev
        e = 3.0
        trust = {"value": trust_v, "evidence": e, "confidence": ev.confidence(e)}

    return DecisionContext.from_dict({
        "scalars": {
            "shopper_id": shopper_id, "aware_of_brand": aware,
            "adstock": ads, "exposures_72h": e72,
            "last_seen_t": None if case == "cold" else 1_755_150_000,
            "reference_price": ({"3000001": ref_price} if ref_price else {}),
            "current_price_gap": price_gap, "budget_left": budget_left,
            "cart": [3000001] if in_cart else [],
            "trust_belief": trust, "quality_belief": None,
            "active_need": active_need, "habit": None,
        },
        "motifs": motifs,
    })


def preference_fit_for(shopper, stim, *, learned: bool = False,
                       claim_min: float = 0.05, pref_min_w: float = 0.05):
    """The preference_fit a REAL retrieval would return for this shopper on this
    stimulus, or None when there is genuinely no overlap.

    Reproduces hydramem/reads.py's selection rule exactly, because the rule is
    the interesting part: retrieval keeps only the SINGLE strongest hit, ranked
    by (prior weight x claim strength), and reports that hit's `w` as the motif
    strength — not the product, and not a sum over every match. A study that
    used a flat strength instead (as this module first did) makes every creative
    look alike to the mind, which is exactly the failure the rank-agreement
    study caught.

    `learned` models a shopper who has since engaged: the held weight has been
    blended toward PREF_TARGET by a couple of behavioural events, using the one
    formula rather than a fudge factor.
    """
    from ..contracts import evidence as ev
    from ..contracts.enums import EventType

    priors = dict(shopper.priors)
    best = None
    for concept, strength in (stim.claims if stim is not None else {}).items():
        if strength < claim_min or concept not in priors:
            continue
        w = priors[concept]
        if w < pref_min_w:
            continue
        rank = w * strength
        if best is None or rank > best[0]:
            best = (rank, concept, w)
    if best is None:
        return None
    _rank, concept, w = best
    if learned:
        # two browse-grade events' worth of engagement, through the one formula
        weight = ev.EVIDENCE_TABLE[EventType.BROWSED].pref_weight * 2
        w, _e = ev.blend(w, ev.PRIOR_E0, ev.PREF_TARGET, weight)
    return concept, w


def shopper_context(case: str, shopper, stim, *, kind: str = "creative",
                    **overrides) -> DecisionContext:
    """A context for THIS shopper on THIS stimulus.

    Same cases as `make_context`, but the preference_fit motif is derived from
    the shopper's own priors intersected with the stimulus's own claims, so a
    creative whose message nobody in the population cares about scores lower
    than one whose message lands. `make_context` keeps the population-average
    behaviour for the calibration mix, where the per-shopper detail averages out.
    """
    pref = None
    if case in ("prior_hit", "learned", "fatigued", "goal_on") and kind == "creative":
        pref = preference_fit_for(shopper, stim, learned=case != "prior_hit")
    return make_context(
        case, kind=kind, shopper_id=shopper.shopper_id,
        pref_strength=(pref[1] if pref else 0.0), **overrides)


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------


def gate_means(pop, cases: dict, stim: StimulusFacts | None,
               profile: Profile, mix=DEFAULT_MIX) -> dict[str, float]:
    """Mix-weighted, population-mean P(advance) per gate.

    `cases` maps a case name to (DecisionContext, kind). Creative contexts
    contribute a CLICK gate; page contexts contribute BROWSE/CART/BUY — the same
    split `stage_probabilities` enforces, so a page never invents a click gate it
    does not have and the two phases are averaged over their own denominators.
    """
    totals: dict[str, float] = {}
    weights: dict[str, float] = {}
    for sh in pop:
        for case, share in mix:
            entry = cases.get(case)
            if entry is None:
                continue
            ctx, kind = entry
            a = appraise(ctx, sh.traits, stim, params=profile.appraisal)
            for stage, p in stage_probabilities(a, ctx.scalars, sh.coeffs,
                                                kind=kind,
                                                params=profile.choice).items():
                totals[stage] = totals.get(stage, 0.0) + share * p
                weights[stage] = weights.get(stage, 0.0) + share
    return {k: totals[k] / weights[k] for k in sorted(totals)}


def funnel_mix(pop, stim: StimulusFacts | None, profile: Profile,
               *, mix=DEFAULT_MIX, violation_share: float = 0.0,
               price_gap: float = -0.05) -> dict:
    """The whole funnel under one profile: CLICK from creative contexts,
    BROWSE/CART/BUY from the page contexts the same shoppers land on.

    `violation_share` is the fraction of page traffic hitting a variant that
    breaks an expectation (the seeded A/B). Reference runs set it to 0 — a
    normal site does not send half its visitors to a deliberately inconsistent
    page, and leaving it on is what made the committed runs read a 63-67% bounce
    rate against a researched 45-55%.
    """
    creative = {case: (make_context(case, kind="creative", price_gap=price_gap),
                       "creative")
                for case, _ in mix}
    click = gate_means(pop, creative, stim, profile, mix)["CLICK"]

    def page_rates(violation):
        pages = {case: (make_context(case, kind="page", price_gap=price_gap,
                                     violation=violation), "page")
                 for case, _ in mix}
        return gate_means(pop, pages, stim, profile, mix)

    clean = page_rates(None)
    if violation_share:
        bad = page_rates(0.45)
        w = violation_share
        page = {k: (1 - w) * clean[k] + w * bad[k] for k in clean}
    else:
        page = clean

    browse, cart, buy = page["BROWSE"], page["CART"], page["BUY"]
    visit_to_purchase = browse * cart * buy
    return {
        "p_click": click,
        "bounce_rate": 1.0 - browse,
        "p_browse": browse,
        "p_cart_given_browse": cart,
        "p_buy_given_cart": buy,
        "visit_to_purchase": visit_to_purchase,
        "buy_per_exposure": click * visit_to_purchase,
    }
