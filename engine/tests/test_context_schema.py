"""C1: every canned context validates; abstention is structural; round-trips hold."""

import copy

import pytest

from shopsim.contracts.types import DecisionContext, validate_context


def test_all_fixture_contexts_validate(context_wrappers):
    for name, wrapper in context_wrappers:
        problems = validate_context(wrapper["context"])
        assert not problems, f"{name}: {problems}"


def test_round_trip(context_wrappers):
    for name, wrapper in context_wrappers:
        ctx = DecisionContext.from_dict(wrapper["context"])
        again = DecisionContext.from_dict(ctx.to_dict())
        assert again == ctx, f"{name} did not round-trip"


def test_abstention_case_is_structural(mock):
    ctx = mock.by_name("unknown-brand-abstention")
    s = ctx.scalars
    assert s.trust_belief is None  # no belief node = unknown
    assert s.quality_belief is None
    assert s.active_need is None
    assert not s.aware_of_brand
    assert ctx.motifs == ()  # no paths = no knowledge


def _base(context_wrappers) -> dict:
    for name, wrapper in context_wrappers:
        if wrapper["name"] == "twin-need-on":
            return copy.deepcopy(wrapper["context"])
    raise AssertionError("twin-need-on fixture missing")


def test_missing_scalar_rejected(context_wrappers):
    broken = _base(context_wrappers)
    del broken["scalars"]["trust_belief"]
    assert validate_context(broken)


def test_inconsistent_confidence_rejected(context_wrappers):
    broken = _base(context_wrappers)
    broken["scalars"]["trust_belief"]["confidence"] = 0.5  # E=3.0 says 0.81
    assert any("inconsistent" in p for p in validate_context(broken))


def test_goal_fit_requires_active_need(context_wrappers):
    broken = _base(context_wrappers)
    broken["scalars"]["active_need"] = None  # goal_fit motif still present
    assert any("goal_fit" in p for p in validate_context(broken))


def test_explanatory_motif_rejected_in_context(context_wrappers):
    broken = _base(context_wrappers)
    broken["motifs"].append(
        {"type": "experience_path", "path": [1000042, "EXPERIENCED", 3000001]}
    )
    assert any("trace-only" in p for p in validate_context(broken))


def test_latent_leak_rejected(context_wrappers):
    broken = _base(context_wrappers)
    broken["scalars"]["latent_quality"] = 0.85
    assert any("Law 15" in p for p in validate_context(broken))


def test_from_dict_raises_on_invalid():
    with pytest.raises(ValueError):
        DecisionContext.from_dict({"scalars": {}, "motifs": []})
