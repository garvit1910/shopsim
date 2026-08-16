"""Phase-1 checkpoint: the scripted story graph returns exactly the expected
hits for all four P0 motifs — including a designed miss per motif — and a
null trust belief for an unknown brand (abstention, structurally)."""

import pytest

from shopsim.contracts.enums import MotifType
from shopsim.hydramem import story

pytestmark = pytest.mark.real


def types(ctx):
    return {m.type for m in ctx.motifs}


# -- preference_fit ----------------------------------------------------------


def test_preference_fit_hit(mock):
    ctx = mock.get_decision_context(story.TWIN_OFF, story.STIM_AD)
    hit = [m for m in ctx.motifs if m.type == MotifType.PREFERENCE_FIT]
    assert len(hit) == 1
    m = hit[0]
    assert m.strength == pytest.approx(0.61)
    assert m.evidence == pytest.approx(2.85)
    assert m.path == (story.TWIN_OFF, "PREFERS", story.ECO, "CLAIMS", story.STIM_AD)


def test_preference_fit_miss_disjoint_concepts(mock):
    # MISSES prefers STYLE only; the stimulus claims eco/lightweight/discount
    ctx = mock.get_decision_context(story.MISSES, story.STIM_AD)
    assert MotifType.PREFERENCE_FIT not in types(ctx)


# -- goal_fit ----------------------------------------------------------------


def test_goal_fit_hit_with_urgency_and_need(mock):
    ctx = mock.get_decision_context(story.TWIN_ON, story.STIM_AD)
    hit = [m for m in ctx.motifs if m.type == MotifType.GOAL_FIT]
    assert len(hit) == 1
    m = hit[0]
    need = ctx.scalars.active_need
    assert need is not None and need.category == story.RUNNING
    assert m.strength == need.strength == pytest.approx(0.8)
    assert m.urgency == need.urgency
    assert 0.0 < need.urgency <= 1.0
    assert m.path == (story.TWIN_ON, "NEEDS", story.RUNNING, "IN_CATEGORY",
                      story.PRODUCT, "OFFERS", story.STIM_AD)


def test_goal_fit_miss_wrong_category(mock):
    # MISSES needs CASUAL shoes; the stimulus offers a RUNNING shoe
    ctx = mock.get_decision_context(story.MISSES, story.STIM_AD)
    assert MotifType.GOAL_FIT not in types(ctx)
    assert ctx.scalars.active_need is None  # need exists but is not relevant here


# -- brand_semantic_fatigue --------------------------------------------------


def test_fatigue_hit_same_brand_same_story(mock):
    ctx = mock.get_decision_context(story.FATIGUE, story.STIM_AD)
    hit = [m for m in ctx.motifs if m.type == MotifType.BRAND_SEMANTIC_FATIGUE]
    assert len(hit) == 1
    m = hit[0]
    assert m.brand == story.SHOECO
    assert 0.0 < m.strength <= 1.0 and 0.0 < m.recency <= 1.0
    # path: most recent same-story creative, through the shared concept
    assert m.path[1] == "SAW" and m.path[3] == "CLAIMS" and m.path[-1] == story.STIM_AD


def test_fatigue_miss_rival_saw_shares_no_concept(mock):
    # twins saw ONE same-brand eco ad -> fatigue exists but is mild; the rival
    # SAWs on the fatigue shopper share no concept, so they contribute nothing:
    # strength must equal what the same-brand SAWs alone produce.
    ctx_twin = mock.get_decision_context(story.TWIN_OFF, story.STIM_AD)
    twin_fatigue = [m for m in ctx_twin.motifs
                    if m.type == MotifType.BRAND_SEMANTIC_FATIGUE]
    assert len(twin_fatigue) == 1  # one SAW of the same story -> present, mild
    # and no concept_saturation anywhere: rival ads share no claimed concept
    assert MotifType.CONCEPT_SATURATION not in types(
        mock.get_decision_context(story.FATIGUE, story.STIM_AD))


# -- expectation_violation ---------------------------------------------------


def test_violation_hit_on_the_hiding_page(mock):
    mem = mock.mem
    ctx = mem.get_decision_context(story.VIOLATION, story.PAGE_VIOLATING)
    hit = [m for m in ctx.motifs if m.type == MotifType.EXPECTATION_VIOLATION]
    assert len(hit) == 1
    m = hit[0]
    assert m.strength == pytest.approx(0.9)
    assert m.path == (story.VIOLATION, "EXPECTS", story.DISCOUNT,
                      "NOT_SHOWN_BY", story.PAGE_VIOLATING)


def test_violation_miss_on_the_consistent_page(mock):
    ctx = mock.mem.get_decision_context(story.VIOLATION, story.PAGE_OK)
    assert MotifType.EXPECTATION_VIOLATION not in types(ctx)


# -- social_proof (P1) -------------------------------------------------------


def test_social_proof_hit(mock):
    ctx = mock.get_decision_context(story.SOCIAL, story.STIM_AD)
    hit = [m for m in ctx.motifs if m.type == MotifType.SOCIAL_PROOF]
    assert len(hit) == 1
    m = hit[0]
    assert m.peer_trust == pytest.approx(0.7)
    assert m.experience == pytest.approx(0.9)
    assert m.path == (story.SOCIAL, "TRUSTS_PERSON", story.PEER, "BOUGHT", story.PRODUCT)


def test_social_proof_miss_no_trusted_peers(mock):
    ctx = mock.get_decision_context(story.TWIN_OFF, story.STIM_AD)
    assert MotifType.SOCIAL_PROOF not in types(ctx)


# -- abstention --------------------------------------------------------------


def test_unknown_brand_abstains_structurally(mock):
    ctx = mock.get_decision_context(story.UNKNOWN, story.UNKNOWN_AD)
    s = ctx.scalars
    assert s.trust_belief is None
    assert s.quality_belief is None
    assert s.active_need is None
    assert s.aware_of_brand is False
    assert s.adstock == 0.0
    assert s.last_seen_t is None
    assert ctx.motifs == ()


# -- belief confidence pair --------------------------------------------------


def test_belief_pair_same_value_different_confidence(mock):
    low = mock.get_decision_context(story.BELIEF_LOW, story.STIM_AD).scalars.trust_belief
    high = mock.get_decision_context(story.BELIEF_HIGH, story.STIM_AD).scalars.trust_belief
    assert low.value == high.value == pytest.approx(0.60)
    assert low.confidence == pytest.approx(0.52, abs=0.005)
    assert high.confidence == pytest.approx(0.90, abs=0.005)
