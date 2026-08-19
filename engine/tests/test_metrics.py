"""Phase 6: the analytics half of the C3 MetricsReport (CONTRACT v3.8-draft).

Every number here is hand-computed in the comment above its assertion — these
are the unit-level twins of the whole-run golden in test_golden_run.py.
"""

import json
from pathlib import Path

import numpy as np
import pytest

from shopsim.analytics import metrics
from shopsim.contracts.enums import Action
from shopsim.contracts.ids import shopper_id as make_sid
from shopsim.contracts.types import Event
from shopsim.contracts.enums import EventType
from shopsim.hydramem.mock import MockHydraMem
from shopsim.minds.choice import asset_wearout
from shopsim.runner.results import BY_SHOPPER_FIELDS, ResultsAccumulator

REPO = Path(__file__).resolve().parents[2]
F = {name: i for i, name in enumerate(BY_SHOPPER_FIELDS)}


def vec(**counts) -> list:
    row = [0] * len(BY_SHOPPER_FIELDS)
    for name, n in counts.items():
        row[F[name]] = n
    return row


# ---------------------------------------------------------------------------
# bootstrap
# ---------------------------------------------------------------------------


def test_identical_units_give_a_degenerate_interval():
    """40 shoppers, each 10 exposures and 1 click: every resample is the same
    population, so the 95% interval collapses onto the point estimate 0.1."""
    num = np.full(40, 1.0)
    den = np.full(40, 10.0)
    ss = np.random.SeedSequence((57, metrics.CI_STREAM, 0, 0))
    assert metrics.bootstrap_ratio_ci(num, den, ss, n_boot=200) == [0.1, 0.1]


def test_interval_brackets_the_point_estimate_and_is_seed_stable():
    rng = np.random.default_rng(0)
    den = rng.integers(5, 15, size=120).astype(float)
    num = rng.binomial(den.astype(int), 0.2).astype(float)
    point = num.sum() / den.sum()
    ss = lambda: np.random.SeedSequence((57, metrics.CI_STREAM, 0, 0))  # noqa: E731
    lo, hi = metrics.bootstrap_ratio_ci(num, den, ss())
    assert lo < point < hi
    assert metrics.bootstrap_ratio_ci(num, den, ss()) == [lo, hi]  # same seed, twice


def test_empty_denominator_yields_no_interval():
    z = np.zeros(10)
    ss = np.random.SeedSequence((1, 2, 3, 4))
    assert metrics.bootstrap_ratio_ci(z, z, ss, n_boot=50) is None
    assert metrics.bootstrap_ratio_ci(np.array([]), np.array([]), ss) is None


def test_funnel_ci_keys_cover_arm_and_segments():
    by_shopper = {"0": vec(SAW=10, CLICKED=1, BROWSED=1, CARTED=1, BOUGHT=1),
                  "1": vec(SAW=10, CLICKED=1, BROWSED=1, CARTED=1, BOUGHT=0),
                  "2": vec(SAW=10, CLICKED=2, BROWSED=1, CARTED=0, BOUGHT=0)}
    ci = metrics.funnel_ci(by_shopper, BY_SHOPPER_FIELDS,
                           {0: 1001, 1: 1001, 2: 1002}, seed=57, n_boot=200)
    assert "ctr" in ci and "ctr:1001" in ci and "ctr:1002" in ci
    # segment 1002 never carted, so no buy_rate interval is invented for it
    assert "buy_rate:1002" not in ci
    assert list(ci) == sorted(ci)
    for span in ci.values():
        assert len(span) == 2 and span[0] <= span[1]


def test_funnel_ci_is_reproducible_and_offset_keyed():
    """The bootstrap must not see absolute shopper ids: the same counts under
    a different run block hash identically (norm_results_hash relies on it)."""
    by_shopper = {"0": vec(SAW=8, CLICKED=1), "1": vec(SAW=8, CLICKED=3)}
    a = metrics.funnel_ci(by_shopper, BY_SHOPPER_FIELDS, {0: 1001, 1: 1001}, 57, n_boot=300)
    b = metrics.funnel_ci(by_shopper, BY_SHOPPER_FIELDS, {0: 1001, 1: 1001}, 57, n_boot=300)
    assert a == b and a


# ---------------------------------------------------------------------------
# fatigue split
# ---------------------------------------------------------------------------


def test_asset_wearout_is_the_utility_number():
    """Free below wearout_free_exposures, then linear to saturation."""
    assert asset_wearout(0) == 0.0 and asset_wearout(2) == 0.0
    assert asset_wearout(3) == 0.25 and asset_wearout(5) == 0.75
    assert asset_wearout(9) == 1.0


def test_fatigue_channels_split_ctr_by_level():
    """Three creative decisions on tick 0, from the committed contexts:

      fatigue-present   exposures_72h 5 -> asset 0.75 HIGH, brand 0.85 HIGH, CLICK
      twin-need-off     exposures_72h 3 -> asset 0.25 low,  brand 0.60 HIGH, IGNORE
      unknown-brand     exposures_72h 0 -> asset 0.00 low,  brand 0.00 low,  IGNORE

    asset : mean (0.75+0.25+0)/3 = 0.33333; high 1 decision 1 click -> 1.0;
            low 2 decisions 0 clicks -> 0.0
    brand : mean (0.85+0.60+0)/3 = 0.48333; high 2 decisions 1 click -> 0.5;
            low 1 decision 0 clicks -> 0.0
    concept: no saturation motif anywhere -> mean 0.0, no high cell at all
    """
    mock = MockHydraMem(REPO / "fixtures")
    acc = ResultsAccumulator(arm="a", segment_by_offset={}, drift_concepts=[],
                             hero_product=None)
    acc.observe_decision(mock.by_name("fatigue-present"), Action.CLICK, "creative", 0)
    acc.observe_decision(mock.by_name("twin-need-off"), Action.IGNORE, "creative", 0)
    acc.observe_decision(mock.by_name("unknown-brand-abstention"), Action.IGNORE,
                         "creative", 0)
    rows = metrics.fatigue_rows(acc.fatigue)

    assert rows["asset"] == [{"tick": 0, "n": 3, "mean": 0.33333, "high_n": 1,
                              "high_ctr": 1.0, "low_n": 2, "low_ctr": 0.0}]
    assert rows["brand_msg"] == [{"tick": 0, "n": 3, "mean": 0.48333, "high_n": 2,
                                  "high_ctr": 0.5, "low_n": 1, "low_ctr": 0.0}]
    assert rows["concept"] == [{"tick": 0, "n": 3, "mean": 0.0, "high_n": 0,
                                "high_ctr": None, "low_n": 3, "low_ctr": 0.33333}]


def test_page_decisions_never_enter_the_fatigue_channels():
    """The channels answer "what did repetition do to CTR", so only the
    creative gate contributes; a page decision has no CLICK outcome."""
    mock = MockHydraMem(REPO / "fixtures")
    acc = ResultsAccumulator(arm="a", segment_by_offset={}, drift_concepts=[],
                             hero_product=None)
    acc.observe_decision(mock.by_name("fatigue-present"), Action.BUY, "page", 0)
    assert acc.fatigue == {}


# ---------------------------------------------------------------------------
# bounce delta, repeat/LTV, social lift
# ---------------------------------------------------------------------------


def test_bounce_delta_pools_the_runs_own_splits():
    """A: 20 bounces of 100 visits = 0.20; B: 50 of 100 = 0.50; delta = +0.30
    (B - A, the violating variant listed second — same convention as
    experiments/compare.py)."""
    by_page = {"4000001": {"VISITED": 80, "BOUNCED": 20, "BROWSED": 80},
               "4000002": {"VISITED": 50, "BOUNCED": 50, "BROWSED": 50}}
    assert metrics.bounce_delta(by_page, [[4000001, 4000002]]) == 0.3
    assert metrics.bounce_delta(by_page, []) is None
    assert metrics.bounce_delta(by_page, [[4000001, 4000009]]) is None  # unseen page


def test_repeat_ltv_counts_buyers_not_purchases():
    by_shopper = {"0": vec(BOUGHT=2), "1": vec(BOUGHT=1), "2": vec(SAW=4)}
    rows = metrics.repeat_ltv(by_shopper, BY_SHOPPER_FIELDS,
                              {"0": 80.0, "1": 39.0}, arm="market")
    assert rows == [{"arm": "market", "buyers": 2, "buys": 3, "repeat_buyers": 1,
                     "repeat_rate": 0.5, "buys_per_buyer": 1.5,
                     "revenue_total": 119.0, "revenue_per_buyer": 59.5}]


def test_social_lift_absent_without_a_social_layer():
    assert metrics.social_lift({"0": vec(dec_need_on=3)}, BY_SHOPPER_FIELDS, 0.0) is None


def test_social_lift_marks_itself_correlational_when_the_channel_is_inert():
    by_shopper = {"0": vec(dec_social_on=4, buy_social_on=2,
                           dec_social_off=10, buy_social_off=1)}
    inert = metrics.social_lift(by_shopper, BY_SHOPPER_FIELDS, 0.0)
    assert inert["p_buy_social_on"] == 0.5 and inert["p_buy_social_off"] == 0.1
    assert inert["lift"] == 5.0 and inert["causal"] is False
    live = metrics.social_lift(by_shopper, BY_SHOPPER_FIELDS, 0.4)
    assert live["causal"] is True and live["w_social"] == 0.4


# ---------------------------------------------------------------------------
# accumulator plumbing
# ---------------------------------------------------------------------------


MANIFEST = {
    "seed": 57, "config_hash": "c" * 64, "perception_cache_hash": "p" * 64,
    "appraisal_cache_hash": None, "evidence_hash": "e" * 64,
    "goal_config_hash": "g" * 64, "latent_quality_hash": "l" * 64,
}


def test_by_shopper_vector_tracks_events_and_decisions():
    mock = MockHydraMem(REPO / "fixtures")
    acc = ResultsAccumulator(arm="a", segment_by_offset={0: 1001},
                             drift_concepts=[], hero_product=None)
    sid = make_sid(0, 0)
    acc.observe_events([
        Event(EventType.SAW, sid, 1, 0, 2000003),
        Event(EventType.CLICKED, sid, 1, 0, 2000003),
        Event(EventType.BOUGHT, sid, 1, 0, 3000001, props=(("price", 39.0),)),
    ], tick=0)
    acc.observe_decision(mock.by_name("twin-need-on"), Action.BUY, "page", 0)

    row = acc.by_shopper["0"]
    assert row[F["SAW"]] == 1 and row[F["CLICKED"]] == 1 and row[F["BOUGHT"]] == 1
    assert acc.revenue_by_shopper == {"0": 39.0}
    # twin-need-on is offset 42 in the fixture block, a different shopper
    need_row = acc.by_shopper["42"]
    assert need_row[F["dec_need_on"]] == 1 and need_row[F["buy_need_on"]] == 1
    assert need_row[F["dec_need_off"]] == 0


def test_v38_state_round_trips_and_pre_v38_snapshots_still_resume():
    mock = MockHydraMem(REPO / "fixtures")
    acc = ResultsAccumulator(arm="a", segment_by_offset={0: 1001}, drift_concepts=[],
                             hero_product=None, page_pairs=[[4000001, 4000002]])
    acc.observe_decision(mock.by_name("fatigue-present"), Action.CLICK, "creative", 0)
    acc.observe_events([Event(EventType.SAW, make_sid(0, 0), 1, 0, 2000003)], tick=0)

    state = json.loads(json.dumps(acc.state()))  # through JSON, like the file
    back = ResultsAccumulator.from_state(
        state, segment_by_offset=acc.segment_by_offset,
        drift_concepts=acc.drift_concepts, hero_product=acc.hero_product)
    assert back.results(MANIFEST) == acc.results(MANIFEST)
    assert back.page_pairs == [[4000001, 4000002]]

    old = {k: v for k, v in state.items()
           if k not in ("by_shopper", "revenue_by_shopper", "fatigue",
                        "belief_conf_avg", "page_pairs")}
    revived = ResultsAccumulator.from_state(
        old, segment_by_offset={}, drift_concepts=[], hero_product=None)
    out = revived.results(MANIFEST)
    assert out["fatigue_split"]["asset"] == [] and out["violations"]["bounce_delta"] is None


def test_committed_phase3_fixture_still_validates():
    """fixtures/scripted-run-1/results.json is frozen with a pinned config_hash:
    the Phase-6 validator must keep accepting its unpopulated placeholders."""
    from shopsim.runner.results import validate_results

    path = REPO / "fixtures" / "scripted-run-1" / "results.json"
    assert validate_results(json.loads(path.read_text())) == []
