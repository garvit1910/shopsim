"""Choice-model calibration harness (Phase 2.4 checkpoint; opt-in like
bench_phase1 — never wired into pytest).

Generates the authored 13-segment population, sweeps a plausible exposure mix
(cold / aware / preference-hit / goal-on shoppers over the demo stimulus),
and reports population-mean funnel probabilities against the researched bands
in /eval/market-research.md:

    P(CLICK | exposure)   0.002–0.05   (0.5–5% PLAN checkpoint band)
    P(BROWSE | visit)     0.35–0.70
    P(CART | browse)      0.05–0.25
    P(BUY | cart)         0.10–0.45

Run:  cd engine && uv run python bench/calibrate_choice.py
Exits nonzero on a band miss so it can gate manually.
"""

from __future__ import annotations

import sys
from pathlib import Path

from shopsim.contracts.types import DecisionContext
from shopsim.minds.appraisal import appraise
from shopsim.minds.calibration import DEFAULT_CHOICE_PARAMS
from shopsim.minds.choice import _buy_probability, _gate_probability
from shopsim.minds.objective_view import ObjectiveView
from shopsim.population import PopulationConfig, generate_population, load_segment_specs

REPO = Path(__file__).resolve().parents[2]

# exposure-context mix (shares of an exposed audience on one warm campaign):
#   cold        never saw the brand, no paths, no belief   (F2 gate)
#   aware       saw the brand before, no motif hits
#   pref_hit    aware + a live preference_fit motif
#   goal_on     aware + preference_fit + an active need
MIX = (("cold", 0.35), ("aware", 0.40), ("pref_hit", 0.20), ("goal_on", 0.05))

BANDS = {
    "P(CLICK|exposure)": (0.002, 0.05),
    "P(BROWSE|visit)": (0.35, 0.70),
    "P(CART|browse)": (0.05, 0.25),
    "P(BUY|cart)": (0.10, 0.45),
}


def _ctx(case: str) -> DecisionContext:
    scalars = {
        "shopper_id": 1000041, "aware_of_brand": case != "cold",
        "adstock": 0.0 if case == "cold" else 0.5,
        "exposures_72h": 0 if case == "cold" else 1,
        "last_seen_t": None if case == "cold" else 1755150000,
        "reference_price": {"3000001": 39.0}, "current_price_gap": -0.15,
        "budget_left": 120.0, "cart": [], "trust_belief": None,
        "quality_belief": None, "active_need": None, "habit": None,
    }
    motifs = []
    if case in ("pref_hit", "goal_on"):
        motifs.append({"type": "preference_fit", "strength": 0.55, "evidence": 2.0,
                       "recency": 0.9,
                       "path": [1000041, "PREFERS", 5003, "CLAIMS", 2000003]})
        scalars["trust_belief"] = {"value": 0.6, "evidence": 2.0,
                                   "confidence": 2.0 / 2.7}
    if case == "goal_on":
        scalars["active_need"] = {"category": 5504, "strength": 0.8, "urgency": 0.7,
                                  "budget_cap": 90.0}
        motifs.append({"type": "goal_fit", "strength": 0.8, "urgency": 0.7,
                       "path": [1000041, "NEEDS", 5504, "IN_CATEGORY", 3000001,
                                "OFFERS", 2000003]})
    return DecisionContext.from_dict({"scalars": scalars, "motifs": motifs})


def main() -> None:
    specs = load_segment_specs(REPO / "fixtures" / "demo-brand" / "personas.json")
    pop = generate_population(PopulationConfig(seed=7, population_size=500, segments=specs))
    view = ObjectiveView.from_catalog(REPO / "fixtures" / "demo-brand")
    stim = view.facts(2000003)
    params = DEFAULT_CHOICE_PARAMS

    sums = {k: 0.0 for k in BANDS}
    contexts = {case: _ctx(case) for case, _ in MIX}
    for sh in pop:
        click = browse = cart = buy = 0.0
        for case, share in MIX:
            ctx = contexts[case]
            a = appraise(ctx, sh.traits, stim)
            s = ctx.scalars
            click += share * _gate_probability("CLICK", a, s, sh.coeffs, params)
            browse += share * _gate_probability("BROWSE", a, s, sh.coeffs, params)
            cart += share * _gate_probability("CART", a, s, sh.coeffs, params)
            buy += share * _buy_probability(a, s, sh.coeffs, params)
        sums["P(CLICK|exposure)"] += click
        sums["P(BROWSE|visit)"] += browse
        sums["P(CART|browse)"] += cart
        sums["P(BUY|cart)"] += buy

    ok = True
    print(f"population n={len(pop)}, 13 segments, exposure mix {dict(MIX)}\n")
    for name, total in sums.items():
        mean = total / len(pop)
        lo, hi = BANDS[name]
        hit = lo <= mean <= hi
        ok &= hit
        print(f"  {'PASS' if hit else 'MISS'}  {name}: {mean:.4f}  (band {lo}–{hi})")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
