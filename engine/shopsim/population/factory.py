"""Population factory (Phase 2.1) — seeded, reproducible shoppers.

Three persona families per shopper, split per Law 12:
  * preference priors  -> seeded PREFERS edges only (E0 = 2, registry row 1);
    never re-multiplied in appraisal.
  * AppraisalTraits    -> appraise() only.
  * ChoiceCoeffs       -> decide() only (θ_s = calibration defaults + segment
    shift + per-shopper jitter).

Scale is configuration: `population_size` and the segment list are
PopulationConfig fields (validated up to 50 segments / full run block —
5,000+ shoppers — by tests/test_population.py). Segment parameters live in
fixtures/demo-brand/personas.json (see /eval/market-research.md for the
grounding of every number there).

Determinism: shopper i's identity depends only on (seed, i) via
SeedSequence((seed, POPULATION_STREAM, i)) — one substream per shopper, fixed
draw order (segment, priors, traits, coeffs, θ jitter). Growing the
population never changes existing shoppers; same seed => byte-identical
population.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..contracts import evidence
from ..contracts.ids import (
    CONCEPT_MIN,
    SEGMENT_BASE,
    SHOPPER_RUN_BLOCK,
    shopper_id as make_shopper_id,
)
from ..contracts.types import AppraisalTraits, ChoiceCoeffs
from ..minds.calibration import DEFAULT_STAGE_BASES

# Substream tag for population draws (Law 13: seeded substreams keyed by
# stable tuples). int.from_bytes(b"pop") — stable, collision-free vs the
# runner's "goal"/"fulfil"/"social" streams.
POPULATION_STREAM = int.from_bytes(b"pop", "big")

PRIOR_W_MIN, PRIOR_W_MAX = 0.05, 0.95
TRAIT_MIN, TRAIT_MAX = 0.0, 1.0
IMPULSIVITY_MIN, IMPULSIVITY_MAX = 0.4, 2.0
PRICE_SENS_MIN, PRICE_SENS_MAX = 0.05, 1.5
BUDGET_MIN = 30.0

TRAIT_FIELDS = ("trust_orientation", "deal_proneness", "novelty_seeking")
STAGE_ORDER = tuple(name for name, _ in DEFAULT_STAGE_BASES)


@dataclass(frozen=True)
class SegmentSpec:
    segment_id: int
    name: str
    share: float
    prior_means: tuple[tuple[int, float], ...]  # (concept_id, mean w), sorted
    trait_means: tuple[tuple[str, float], ...]
    impulsivity_mean: float
    price_sensitivity_mean: float
    budget_mean: float
    budget_sd: float
    theta_adjust: tuple[tuple[str, float], ...] = ()

    def theta(self, stage: str, base: dict[str, float] | None = None) -> float:
        b = dict(DEFAULT_STAGE_BASES) if base is None else base
        return b[stage] + dict(self.theta_adjust).get(stage, 0.0)


@dataclass(frozen=True)
class PopulationConfig:
    seed: int
    population_size: int
    segments: tuple[SegmentSpec, ...]
    run_index: int = 0
    prior_sd: float = 0.08
    trait_sd: float = 0.08
    impulsivity_sd: float = 0.15
    price_sensitivity_sd: float = 0.10
    theta_jitter_sd: float = 0.15
    # CONTRACT v3.4-draft: Phase-4 calibration override; the default is the
    # module object, so untouched configs draw byte-identical populations
    stage_bases: tuple[tuple[str, float], ...] = DEFAULT_STAGE_BASES

    def __post_init__(self):
        if tuple(n for n, _ in self.stage_bases) != STAGE_ORDER:
            raise ValueError(
                f"stage_bases stages must be {STAGE_ORDER} in order, "
                f"got {tuple(n for n, _ in self.stage_bases)}")
        if not 0 < self.population_size <= SHOPPER_RUN_BLOCK:
            raise ValueError(
                f"population_size {self.population_size} outside (0, {SHOPPER_RUN_BLOCK}]")
        if not self.segments:
            raise ValueError("at least one segment required")
        total = sum(s.share for s in self.segments)
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"segment shares sum to {total}, expected 1.0")
        for s in self.segments:
            if not SEGMENT_BASE <= s.segment_id < CONCEPT_MIN:
                raise ValueError(
                    f"segment_id {s.segment_id} outside [{SEGMENT_BASE}, {CONCEPT_MIN})")


@dataclass(frozen=True)
class Shopper:
    shopper_id: int
    segment_id: int
    budget: float
    priors: tuple[tuple[int, float], ...]  # (concept_id, w) — seeded PREFERS
    traits: AppraisalTraits
    coeffs: ChoiceCoeffs


def load_segment_specs(personas_path: Path | str) -> tuple[SegmentSpec, ...]:
    data = json.loads(Path(personas_path).read_text())
    specs = []
    for seg in data["segments"]:
        budget = seg["coeffs"]["budget"]
        specs.append(SegmentSpec(
            segment_id=seg["segment_id"],
            name=seg["name"],
            share=seg["share"],
            prior_means=tuple(sorted(
                (int(cid), float(w)) for cid, w in seg["prior_means"].items())),
            trait_means=tuple((f, float(seg["traits"][f])) for f in TRAIT_FIELDS),
            impulsivity_mean=float(seg["coeffs"]["impulsivity"]),
            price_sensitivity_mean=float(seg["coeffs"]["price_sensitivity"]),
            budget_mean=float(budget[0]),
            budget_sd=float(budget[1]),
            theta_adjust=tuple(sorted(
                (str(k), float(v)) for k, v in seg.get("theta_adjust", {}).items())),
        ))
    return tuple(specs)


def _clip(x: float, lo: float, hi: float) -> float:
    return float(min(hi, max(lo, x)))


def _draw_shopper(config: PopulationConfig, offset: int) -> Shopper:
    rng = np.random.default_rng(
        np.random.SeedSequence((config.seed, POPULATION_STREAM, offset)))

    # 1. segment (cumulative share)
    u = rng.random()
    cum = 0.0
    spec = config.segments[-1]
    for s in config.segments:
        cum += s.share
        if u < cum:
            spec = s
            break

    # 2. priors (sorted concept order — draw order is part of determinism)
    priors = tuple(
        (cid, _clip(rng.normal(mean, config.prior_sd), PRIOR_W_MIN, PRIOR_W_MAX))
        for cid, mean in spec.prior_means
    )

    # 3. traits
    tvals = {
        name: _clip(rng.normal(mean, config.trait_sd), TRAIT_MIN, TRAIT_MAX)
        for name, mean in spec.trait_means
    }
    traits = AppraisalTraits(**tvals)

    # 4. coeffs
    impulsivity = _clip(rng.normal(spec.impulsivity_mean, config.impulsivity_sd),
                        IMPULSIVITY_MIN, IMPULSIVITY_MAX)
    price_sensitivity = _clip(
        rng.normal(spec.price_sensitivity_mean, config.price_sensitivity_sd),
        PRICE_SENS_MIN, PRICE_SENS_MAX)
    budget = float(max(BUDGET_MIN, rng.normal(spec.budget_mean, spec.budget_sd)))

    # 5. per-stage θ = calibration base + segment shift + shopper jitter
    theta_base = dict(config.stage_bases)
    stage_bases = tuple(
        (stage, spec.theta(stage, theta_base) + float(rng.normal(0.0, config.theta_jitter_sd)))
        for stage in STAGE_ORDER
    )
    coeffs = ChoiceCoeffs(
        impulsivity=impulsivity,
        price_sensitivity=price_sensitivity,
        budget=budget,
        stage_bases=stage_bases,
    )

    return Shopper(
        shopper_id=make_shopper_id(config.run_index, offset),
        segment_id=spec.segment_id,
        budget=budget,
        priors=priors,
        traits=traits,
        coeffs=coeffs,
    )


def generate_population(config: PopulationConfig) -> list[Shopper]:
    return [_draw_shopper(config, i) for i in range(config.population_size)]


def seed_population(mem, shoppers: list[Shopper], t: int = 0) -> int:
    """Write shopper node props + prior PREFERS edges through the real
    HydraMem (single admitted writer = the engine holding `mem`). Shoppers
    are disjoint subgraphs, so groups commit in parallel. Returns statement
    count. Prop shape matches hydramem.writes.seed_preference exactly."""
    from ..hydramem import cypher, schema  # engine-side dependency, not mind-side

    groups: dict[int, list] = {}
    n = 0
    for sh in shoppers:
        stmts = [cypher.set_node_props("shopper", sh.shopper_id, {
            "segment_id": sh.segment_id, "budget": sh.budget})]
        for concept_id, w in sh.priors:
            stmts.append(cypher.create_edge("PREFERS", sh.shopper_id, concept_id, {
                "w": w, "evidence": evidence.PRIOR_E0, "source": "prior",
                "cause_kind": "SEED", "cause_id": 0, "t": t,
                "valid_to": schema.VALID_TO_SENTINEL}, merge=True))
        groups[sh.shopper_id] = stmts
        n += len(stmts)
    mem.client.run_grouped(groups)
    return n
