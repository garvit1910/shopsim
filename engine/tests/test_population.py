"""Phase 2.1 — population factory: seeded, reproducible, scale-ready.

Scale is config (agreed 2026-08-17): the architecture must accept up to 50
segments and populations up to the run block (5,000+ shoppers) without code
changes; the shipped default is the 13 authored personas.json segments.
"""

import dataclasses

import pytest

from shopsim.contracts.ids import CONCEPT_MIN, SHOPPER_BASE, SHOPPER_RUN_BLOCK
from shopsim.contracts.types import AppraisalTraits, ChoiceCoeffs
from shopsim.population import (
    PopulationConfig,
    SegmentSpec,
    generate_population,
    load_segment_specs,
)
from shopsim.population.factory import (
    IMPULSIVITY_MAX,
    IMPULSIVITY_MIN,
    PRIOR_W_MAX,
    PRIOR_W_MIN,
    STAGE_ORDER,
)


@pytest.fixture(scope="module")
def specs(fixtures_dir):
    return load_segment_specs(fixtures_dir / "demo-brand" / "personas.json")


def _config(specs, n=200, seed=42):
    return PopulationConfig(seed=seed, population_size=n, segments=specs)


def test_thirteen_authored_segments(specs):
    assert len(specs) == 13
    assert abs(sum(s.share for s in specs) - 1.0) < 1e-9
    assert len({s.segment_id for s in specs}) == 13


def test_same_seed_identical_population(specs):
    a = generate_population(_config(specs))
    b = generate_population(_config(specs))
    assert a == b


def test_different_seed_differs(specs):
    a = generate_population(_config(specs, seed=42))
    b = generate_population(_config(specs, seed=43))
    assert a != b


def test_growing_population_preserves_existing_shoppers(specs):
    small = generate_population(_config(specs, n=50))
    large = generate_population(_config(specs, n=200))
    assert large[:50] == small


def test_persona_family_split_and_bounds(specs):
    pop = generate_population(_config(specs, n=300))
    for sh in pop:
        assert isinstance(sh.traits, AppraisalTraits)
        assert isinstance(sh.coeffs, ChoiceCoeffs)
        # priors are the ONLY preference entry — never mirrored into traits
        assert sh.priors, "every shopper carries seeded preference priors"
        for _, w in sh.priors:
            assert PRIOR_W_MIN <= w <= PRIOR_W_MAX
        for name in ("trust_orientation", "deal_proneness", "novelty_seeking"):
            assert 0.0 <= getattr(sh.traits, name) <= 1.0
        assert IMPULSIVITY_MIN <= sh.coeffs.impulsivity <= IMPULSIVITY_MAX
        assert sh.coeffs.budget >= 30.0
        assert sh.coeffs.budget == sh.budget
        assert tuple(s for s, _ in sh.coeffs.stage_bases) == STAGE_ORDER


def test_segment_shares_roughly_respected(specs):
    pop = generate_population(_config(specs, n=2000))
    counts = {}
    for sh in pop:
        counts[sh.segment_id] = counts.get(sh.segment_id, 0) + 1
    for spec in specs:
        observed = counts.get(spec.segment_id, 0) / len(pop)
        assert abs(observed - spec.share) < 0.03, (spec.name, observed, spec.share)


def test_shopper_ids_stay_in_run_block(specs):
    pop = generate_population(_config(specs, n=100))
    for sh in pop:
        assert SHOPPER_BASE <= sh.shopper_id < SHOPPER_BASE + SHOPPER_RUN_BLOCK
    run1 = generate_population(dataclasses.replace(_config(specs, n=10), run_index=1))
    assert all(sh.shopper_id >= SHOPPER_BASE + SHOPPER_RUN_BLOCK for sh in run1)


def _synthetic_specs(k: int) -> tuple[SegmentSpec, ...]:
    concepts = list(range(5000, 5029))
    return tuple(
        SegmentSpec(
            segment_id=1001 + i,
            name=f"synthetic_{i}",
            share=1.0 / k,
            prior_means=tuple(sorted(
                (concepts[(i + j) % len(concepts)], 0.3 + 0.4 * ((i + j) % 3) / 2)
                for j in range(3))),
            trait_means=(("trust_orientation", 0.5), ("deal_proneness", 0.5),
                         ("novelty_seeking", 0.5)),
            impulsivity_mean=1.0,
            price_sensitivity_mean=0.6,
            budget_mean=120.0,
            budget_sd=25.0,
        )
        for i in range(k)
    )


def test_architecture_supports_50_segments_and_5000_shoppers():
    """The scale checkpoint: pure config, no code changes, deterministic."""
    cfg = PopulationConfig(seed=7, population_size=5000, segments=_synthetic_specs(50))
    pop = generate_population(cfg)
    assert len(pop) == 5000
    seen_segments = {sh.segment_id for sh in pop}
    assert len(seen_segments) == 50
    # spot-check determinism without paying for a full second generation
    again = [pop[i] == generate_population(
        PopulationConfig(seed=7, population_size=i + 1, segments=_synthetic_specs(50)))[i]
        for i in (0, 1234, 4999)]
    assert all(again)


def test_config_validation():
    specs = _synthetic_specs(2)
    with pytest.raises(ValueError, match="shares"):
        PopulationConfig(seed=1, population_size=10,
                         segments=(dataclasses.replace(specs[0], share=0.9), specs[1]))
    with pytest.raises(ValueError, match="population_size"):
        PopulationConfig(seed=1, population_size=SHOPPER_RUN_BLOCK + 1, segments=specs)
    bad = dataclasses.replace(specs[0], segment_id=CONCEPT_MIN, share=0.5)
    with pytest.raises(ValueError, match="segment_id"):
        PopulationConfig(seed=1, population_size=10,
                         segments=(bad, dataclasses.replace(specs[1], share=0.5)))
