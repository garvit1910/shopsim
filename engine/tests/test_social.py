"""The social layer (P1, pulled forward in Phase 6 — CONTRACT v3.8-draft).

Two halves, both opt-in:
  * the seeded small-world factory that writes TRUSTS_PERSON, and
  * the social_proof -> credibility channel, weighted by w_social.

The through-line of every test here is that the layer is BYTE-NEUTRAL when it
is off: a run_config without `population.social` must produce exactly the graph
and exactly the appraisals it produced before the layer existed.
"""

from dataclasses import replace
from pathlib import Path

import pytest

from shopsim.analytics import metrics
from shopsim.contracts.enums import Action, MotifType
from shopsim.contracts.types import AppraisalTraits
from shopsim.hydramem.mock import MockHydraMem
from shopsim.minds.appraisal import appraise
from shopsim.minds.calibration import DEFAULT_APPRAISAL_PARAMS, AppraisalParams
from shopsim.minds.objective_view import StimulusFacts
from shopsim.population.factory import DEFAULT_SOCIAL, SocialConfig, social_graph
from shopsim.runner.config import parse_social
from shopsim.runner.results import BY_SHOPPER_FIELDS, ResultsAccumulator

REPO = Path(__file__).resolve().parents[2]
NEUTRAL = AppraisalTraits(0.5, 0.5, 0.5)
STIM = StimulusFacts(  # the Appendix-B stimulus, same as test_appraise.py
    stimulus_id=2000003, kind="creative", brand_id=6001,
    claims={5003: 0.9, 5005: 0.6, 5011: 0.8},
    offers={3000001: 0.15}, products={3000001: 5504})
ON = SocialConfig(enabled=True)


# ---------------------------------------------------------------------------
# the graph
# ---------------------------------------------------------------------------


def degrees(edges, n):
    d = dict.fromkeys(range(n), 0)
    for a, b, _w in edges:
        d[a] += 1
        d[b] += 1
    return d


def test_small_world_is_seeded_and_reproducible():
    a = social_graph(40, 57, ON)
    assert a == social_graph(40, 57, ON)
    assert a != social_graph(40, 58, ON), "a different seed must move the graph"


def test_edges_are_normalized_undirected_pairs_without_self_loops():
    edges = social_graph(40, 57, ON)
    assert all(a < b for a, b, _ in edges)
    assert len(edges) == len({(a, b) for a, b, _ in edges})
    assert all(0.4 <= w <= 0.9 for _, _, w in edges)


def test_mean_degree_matches_the_configured_degree():
    """PLAN 2.1: degree ~ 4. Rewiring moves edges around, it does not create or
    destroy them, so the MEAN is exact even though individuals vary."""
    n = 60
    edges = social_graph(n, 57, ON)
    d = degrees(edges, n)
    assert sum(d.values()) / n == pytest.approx(4.0, abs=1e-9)
    assert min(d.values()) >= 1  # nobody is stranded by the rewire


def test_degree_is_configurable_and_tiny_populations_are_refused_gracefully():
    assert sum(degrees(social_graph(50, 57, SocialConfig(True, degree=6)), 50).values()) == 300
    assert social_graph(2, 57, ON) == ()  # a ring needs three
    assert social_graph(40, 57, SocialConfig(enabled=True, degree=0)) == ()


def test_rewiring_actually_rewires():
    """p = 0 is the pure ring lattice; a high p must move edges off it."""
    ring = social_graph(40, 57, SocialConfig(True, rewire_p=0.0))
    assert all(min((b - a) % 40, (a - b) % 40) <= 2 for a, b, _ in ring)
    noisy = social_graph(40, 57, SocialConfig(True, rewire_p=0.9))
    assert any(min((b - a) % 40, (a - b) % 40) > 2 for a, b, _ in noisy)


# ---------------------------------------------------------------------------
# the config gate
# ---------------------------------------------------------------------------


def test_absent_or_disabled_social_is_no_social():
    assert parse_social(None) is None
    assert parse_social({}) is None
    assert parse_social({"enabled": False, "degree": 8}) is None
    cfg = parse_social({"enabled": True, "degree": 6})
    assert cfg is not None and cfg.degree == 6


def test_unknown_social_keys_are_refused():
    """A typo must never be swallowed into a run whose config_hash then claims
    it was honored (the parse_allocation / parse_calibration rule)."""
    with pytest.raises(ValueError, match="unknown keys"):
        parse_social({"enabled": True, "degre": 6})
    with pytest.raises(ValueError, match="rewire_p"):
        parse_social({"enabled": True, "rewire_p": 2.0})
    with pytest.raises(ValueError, match="weights"):
        parse_social({"enabled": True, "weight_min": 0.9, "weight_max": 0.4})


# ---------------------------------------------------------------------------
# the appraisal channel
# ---------------------------------------------------------------------------


def social_ctx(valence: float, peer_trust: float = 0.7):
    ctx = MockHydraMem(REPO / "fixtures").by_name("social-case")
    motifs = [replace(m, valence=valence, peer_trust=peer_trust)
              if m.type is MotifType.SOCIAL_PROOF else m for m in ctx.motifs]
    return replace(ctx, motifs=tuple(motifs))


def test_social_proof_is_reported_but_inert_at_the_default_weight():
    """DEFAULT_APPRAISAL_PARAMS.w_social is 0.0, so the motif is retrieved,
    surfaced on the Appraisal, and changes nothing — the pre-social behavior,
    bit for bit."""
    assert DEFAULT_APPRAISAL_PARAMS.w_social == 0.0
    ctx = social_ctx(0.9)
    bare = replace(ctx, motifs=tuple(m for m in ctx.motifs
                                     if m.type is not MotifType.SOCIAL_PROOF))
    with_social = appraise(ctx, NEUTRAL, STIM)
    without = appraise(bare, NEUTRAL, STIM)
    assert with_social.social_proof == 0.9 and without.social_proof is None
    assert with_social.credibility == without.credibility


def test_social_proof_moves_credibility_once_calibrated():
    params = AppraisalParams(w_social=0.4)
    good = appraise(social_ctx(1.0), NEUTRAL, STIM, params)
    neutral = appraise(social_ctx(0.5), NEUTRAL, STIM, params)
    bad = appraise(social_ctx(0.0), NEUTRAL, STIM, params)
    assert good.credibility > neutral.credibility > bad.credibility
    # valence 0.5 is "no signal": the term is symmetric around it
    assert neutral.credibility == appraise(social_ctx(0.5), NEUTRAL, STIM).credibility
    # the contribution is exactly w_social x (2v - 1) wherever it does not
    # clamp: valence 0.0 subtracts 0.4, and the social-case fixture's belief
    # leaves room for that (its base credibility is ~0.66)
    assert neutral.credibility - bad.credibility == pytest.approx(0.4, abs=1e-9)
    assert good.credibility == 1.0  # +0.4 from ~0.66 clamps at the dim ceiling


def test_the_most_trusted_peer_is_the_one_that_counts():
    ctx = social_ctx(0.2, peer_trust=0.4)
    loud = replace(ctx.motifs[-1], valence=0.9, peer_trust=0.85)
    ctx = replace(ctx, motifs=(*ctx.motifs, loud))
    assert appraise(ctx, NEUTRAL, STIM).social_proof == 0.9


def test_credibility_stays_bounded_at_extreme_weights():
    for valence in (0.0, 0.5, 1.0):
        a = appraise(social_ctx(valence), NEUTRAL, STIM, AppraisalParams(w_social=5.0))
        assert 0.0 <= a.credibility <= 1.0


# ---------------------------------------------------------------------------
# the metric
# ---------------------------------------------------------------------------


def test_social_lift_is_populated_only_when_the_layer_ran():
    """Two page decisions on the same shopper, one with a peer's purchase
    behind it and one without; the report must split them and must label the
    result correlational while w_social is 0."""
    mock = MockHydraMem(REPO / "fixtures")
    acc = ResultsAccumulator(arm="a", segment_by_offset={}, drift_concepts=[],
                             hero_product=None, w_social=0.0)
    acc.observe_decision(social_ctx(0.9), Action.BUY, "page", 0)
    acc.observe_decision(mock.by_name("twin-need-on"), Action.BROWSE, "page", 0)
    lift = metrics.social_lift(acc.by_shopper, BY_SHOPPER_FIELDS, acc.w_social)
    assert lift["decisions_on"] == 1 and lift["decisions_off"] == 1
    assert lift["p_buy_social_on"] == 1.0 and lift["p_buy_social_off"] == 0.0
    assert lift["causal"] is False and "correlation" in lift["note"]


def test_default_social_config_is_off():
    assert DEFAULT_SOCIAL.enabled is False
