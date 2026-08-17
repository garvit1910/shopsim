"""Phase 4: the calibration block reaches minds and population without
touching evidence.py or the default-path draws (CONTRACT v3.4-draft)."""

from pathlib import Path

import pytest

from shopsim.minds.calibration import DEFAULT_STAGE_BASES
from shopsim.population.factory import (
    PopulationConfig,
    generate_population,
    load_segment_specs,
)

REPO = Path(__file__).resolve().parents[2]
PERSONAS = REPO / "fixtures" / "demo-brand" / "personas.json"


@pytest.fixture(scope="module")
def specs():
    return load_segment_specs(PERSONAS)


def test_default_stage_bases_default_is_module_object(specs):
    cfg = PopulationConfig(seed=57, population_size=10, segments=specs)
    assert cfg.stage_bases is DEFAULT_STAGE_BASES


def test_stage_bases_shift_theta_without_changing_draws(specs):
    base = generate_population(PopulationConfig(
        seed=57, population_size=25, segments=specs))
    shifted_bases = tuple(
        (stage, v + (0.7 if stage == "CLICK" else 0.0))
        for stage, v in DEFAULT_STAGE_BASES)
    shifted = generate_population(PopulationConfig(
        seed=57, population_size=25, segments=specs, stage_bases=shifted_bases))

    for a, b in zip(base, shifted):
        # rng consumption identical: everything but theta is untouched
        assert a.shopper_id == b.shopper_id
        assert a.segment_id == b.segment_id
        assert a.priors == b.priors
        assert a.traits == b.traits
        assert a.coeffs.impulsivity == b.coeffs.impulsivity
        assert a.coeffs.price_sensitivity == b.coeffs.price_sensitivity
        assert a.budget == b.budget
        ta, tb = dict(a.coeffs.stage_bases), dict(b.coeffs.stage_bases)
        assert tb["CLICK"] == pytest.approx(ta["CLICK"] + 0.7)
        for stage in ("BROWSE", "CART", "BUY"):
            assert tb[stage] == ta[stage]


def test_stage_bases_wrong_stages_rejected(specs):
    with pytest.raises(ValueError, match="stage_bases stages"):
        PopulationConfig(seed=57, population_size=5, segments=specs,
                         stage_bases=(("CLICK", 6.0), ("BUY", 3.2)))
