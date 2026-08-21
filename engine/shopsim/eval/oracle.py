"""PLAN 7.3 — rank agreement against a synthetic oracle.

The question: when the simulator says creative A will out-perform creative B,
does it agree with an independent reading of what this population wants? If the
five appraisal dims, the sigmoid gates, the per-shopper thresholds and the
segment mix collectively scramble an ordering that is obvious from the
population's own priors, the machinery is adding noise rather than structure.

**The oracle, and what it is honestly worth.** For each creative it computes

    score = mean_over_shoppers( sum_over_claims( prior_w x claim_strength ) )
            + deal_weight x claimed_pct

i.e. a marketing analyst's heuristic: how much of what this ad says does this
population already care about, plus how good the deal is. It reads the
population's TRUE priors directly from the factory.

That makes this a **construct-validity** check, not an external validation, and
the report says so. The oracle is not independent of the simulator's inputs —
both read the same priors — but it is independent of its *mechanism*: the oracle
sums over every matching concept, while the mind keeps only the single strongest
preference_fit motif, decays it by recency, mixes it with four other dimensions,
and pushes the result through a per-shopper sigmoid. Agreement means that
pipeline preserves the ordering it should. Disagreement would be a real finding,
which is why the number is worth computing.

Spearman is implemented here (average ranks + Pearson on ranks) rather than
pulled from scipy: it is fifteen lines, and the engine ships numpy only.
"""

from __future__ import annotations

from .contexts import (DEFAULT_MIX, Profile, catalog_view, population,
                       shopper_context)
from ..minds.appraisal import appraise
from ..minds.choice import stage_probabilities

DEAL_WEIGHT = 1.0


def _ranks(values: list[float]) -> list[float]:
    """Average ranks, so ties do not silently become an arbitrary order."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(a: list[float], b: list[float]) -> float | None:
    if len(a) != len(b) or len(a) < 3:
        return None
    ra, rb = _ranks(a), _ranks(b)
    n = len(ra)
    ma, mb = sum(ra) / n, sum(rb) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    da = sum((x - ma) ** 2 for x in ra) ** 0.5
    db = sum((y - mb) ** 2 for y in rb) ** 0.5
    return None if da == 0 or db == 0 else num / (da * db)


def oracle_score(shoppers, stim) -> float:
    """Ground truth for one creative against one population."""
    if stim is None:
        return 0.0
    total = 0.0
    for sh in shoppers:
        priors = dict(sh.priors)
        total += sum(priors.get(concept, 0.0) * strength
                     for concept, strength in stim.claims.items())
    return total / len(shoppers) + DEAL_WEIGHT * stim.max_claimed_pct


def sim_score(shoppers, stim, profile: Profile, mix=DEFAULT_MIX) -> float:
    """What the simulator predicts: mix-weighted mean P(CLICK) on this creative.

    The full mind path — real appraise(), real gate math, real per-shopper
    thresholds — over the same exposure-state mix the calibration uses.
    """
    total = weight = 0.0
    for sh in shoppers:
        contexts = {case: shopper_context(case, sh, stim, kind="creative")
                    for case, _ in mix}
        for case, share in mix:
            ctx = contexts[case]
            a = appraise(ctx, sh.traits, stim, params=profile.appraisal)
            total += share * stage_probabilities(
                a, ctx.scalars, sh.coeffs, kind="creative",
                params=profile.choice)["CLICK"]
            weight += share
    return total / weight


def rank_agreement(*, seeds=(11, 23, 37, 53, 71), size: int = 300,
                   catalog: str = "fixtures/demo-brand",
                   creatives: tuple[int, ...] | None = None,
                   profile: Profile | None = None,
                   threshold: float = 0.7) -> dict:
    profile = profile or Profile("default")
    view = catalog_view(catalog)
    if creatives is None:
        creatives = tuple(sorted(
            sid for sid, f in view.stimuli.items() if f.kind == "creative"))
    per_seed, table = [], {}
    for seed in seeds:
        pop = population(seed, size, stage_bases=profile.stage_bases)
        oracle = [oracle_score(pop, view.facts(c)) for c in creatives]
        sim = [sim_score(pop, view.facts(c), profile) for c in creatives]
        rho = spearman(oracle, sim)
        per_seed.append({"seed": seed, "spearman": None if rho is None else round(rho, 5),
                         "oracle": [round(x, 5) for x in oracle],
                         "sim": [round(x, 6) for x in sim]})
        table[seed] = (oracle, sim)

    rhos = [r["spearman"] for r in per_seed if r["spearman"] is not None]
    mean_rho = sum(rhos) / len(rhos) if rhos else None
    worst = min(rhos) if rhos else None
    return {
        "creatives": list(creatives),
        "catalog": catalog,
        "seeds": list(seeds),
        "population_size": size,
        "per_seed": per_seed,
        "mean_spearman": None if mean_rho is None else round(mean_rho, 5),
        "worst_spearman": None if worst is None else round(worst, 5),
        "threshold": threshold,
        "passed": bool(mean_rho is not None and mean_rho >= threshold),
        "tier": "analytic",
        "caveat": (
            "Construct validity, not external validation: the oracle reads the "
            "same population priors the simulator does, so agreement shows the "
            "mind's mechanism preserves an ordering that is already implicit in "
            "its inputs. It is not evidence that either ranking matches a real "
            "market."),
    }


def confirm_on_runs(results_by_creative: dict[int, dict], oracle_by_creative: dict[int, float],
                    *, threshold: float = 0.7) -> dict:
    """The DB-backed half: does the ordering survive a real run?

    Takes realised per-creative CTR out of `funnel_by_creative` (which Phase 4
    already dimensions) and ranks it against the same oracle scores. Small
    numbers of creatives and real sampling noise mean this is a confirmation,
    not the headline — the headline is the multi-seed analytic study above.
    """
    creatives = sorted(set(results_by_creative) & set(oracle_by_creative))
    sim, oracle, detail = [], [], []
    for c in creatives:
        row = results_by_creative[c]
        saw = row.get("SAW", 0)
        ctr = row.get("CLICKED", 0) / saw if saw else None
        if ctr is None:
            continue
        sim.append(ctr)
        oracle.append(oracle_by_creative[c])
        detail.append({"creative": c, "ctr": round(ctr, 6), "exposures": saw,
                       "oracle": round(oracle_by_creative[c], 5)})
    rho = spearman(oracle, sim)
    return {"tier": "scenario", "creatives": [d["creative"] for d in detail],
            "detail": detail, "spearman": None if rho is None else round(rho, 5),
            "threshold": threshold,
            "passed": bool(rho is not None and rho >= threshold),
            "note": "realised CTR from one live run; sampling noise on a handful "
                    "of creatives makes this a confirmation of the analytic study, "
                    "not a replacement for it"}
