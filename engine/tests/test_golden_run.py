"""Phase 6.2 — the golden run, checked WITHOUT a database.

PLAN.md: "tiny golden run (5 shoppers, 3 ticks, one full evidence chain) with
hand-checked numbers asserted in tests". `fixtures/golden-run/` is that run,
frozen; this module re-derives what it can from the committed event log and
accumulator snapshot and pins the rest as literals. Every literal carries the
reasoning that produces it, so a future change to the engine fails here with
an explanation attached rather than a bare number mismatch.

The live-stack twin is tests/real/test_golden_run_real.py, which re-runs the
same config and asserts the report comes back identical.
"""

import json
from collections import Counter
from pathlib import Path

import pytest

from shopsim.analytics import metrics
from shopsim.contracts.ids import shopper_offset
from shopsim.population.factory import (
    PopulationConfig, generate_population, load_segment_specs)
from shopsim.runner.config import RunConfig
from shopsim.runner.results import BY_SHOPPER_FIELDS, ResultsAccumulator, validate_results

REPO = Path(__file__).resolve().parents[2]
GOLDEN = REPO / "fixtures" / "golden-run"
NEED_OFFSET = 1  # the one scripted need in the run (goal_config: shopper 1000001)


@pytest.fixture(scope="module")
def results() -> dict:
    return json.loads((GOLDEN / "results.json").read_text())


@pytest.fixture(scope="module")
def records() -> list[dict]:
    return [json.loads(ln) for ln in
            (GOLDEN / "events.jsonl").read_text().splitlines() if ln.strip()]


@pytest.fixture(scope="module")
def state() -> dict:
    return json.loads((GOLDEN / "results_state_2.json").read_text())["state"]


@pytest.fixture(scope="module")
def accumulator(state) -> ResultsAccumulator:
    cfg = RunConfig.load(GOLDEN / "run_config.json")
    _ap, _cp, stage_bases = cfg.calibration()
    shoppers = generate_population(PopulationConfig(
        seed=cfg.seed, population_size=cfg.population_size,
        segments=load_segment_specs(cfg.personas_path), run_index=0,
        stage_bases=stage_bases))
    return ResultsAccumulator.from_state(
        state, drift_concepts=[], hero_product=None,
        segment_by_offset={shopper_offset(s.shopper_id): s.segment_id for s in shoppers})


# ---------------------------------------------------------------------------
# the report is a valid, complete MetricsReport
# ---------------------------------------------------------------------------


def test_golden_report_is_c3_valid(results):
    assert validate_results(results) == []


def test_every_phase6_key_is_populated(results):
    """The Phase-6 checkpoint: "MetricsReport validates against C3.v3; drift +
    goal + confidence metrics populated"."""
    assert results["ci"], "bootstrap intervals missing"
    assert results["belief_confidence_dist"], "confidence distribution missing"
    assert results["belief_drift"], "belief drift missing"
    assert results["provenance_coverage"] is not None
    assert results["fatigue_split"]["brand_msg"], "fatigue channels missing"
    assert results["violations"]["bounce_delta"] is not None
    assert results["repeat_ltv_by_arm"]
    # social is opt-in and this run does not enable it — null, not zero
    assert results["social_lift"] is None


def test_manifest_carries_the_law13_hashes(results):
    m = results["run_manifest"]
    for key in ("evidence_hash", "perception_cache_hash", "goal_config_hash",
                "latent_quality_hash", "config_hash", "view_hash"):
        assert m.get(key), f"manifest missing {key}"
    assert m["seed"] == 58 and m["ticks"] == 3


# ---------------------------------------------------------------------------
# the funnel, re-derived from the log rather than trusted
# ---------------------------------------------------------------------------


def test_funnel_totals_match_the_event_log(results, records):
    """results.json must be a faithful summary of events.jsonl, not a parallel
    account of it."""
    from_log = Counter(r["type"] for r in records if r.get("type"))
    totals: Counter = Counter()
    for segments in results["funnel"].values():
        for counts in segments.values():
            totals.update(counts)
    for etype, n in totals.items():
        if n:
            assert from_log[etype] == n, etype


def test_hand_checked_funnel(results):
    """5 shoppers x 3 days, one creative live per day, reach 1.0:

      SAW       5 x 3 = 15
      CLICKED   day 1 only offset 1 (its need makes the stand-in click) = 1;
                days 2-3 all five (adstock from one prior exposure is
                2^-0.5 = 0.707, over the stand-in's 0.6 threshold) = 10 -> 11
      BROWSED   every click reaches a page and the stand-in never bounces = 11
      CARTED    the one BUY expands to CARTED + BOUGHT = 1
      BOUGHT    offset 1, day 2 — day 1 it had no reference price yet, so the
                BUY gate could not fire = 1
      EXPERIENCED  that purchase, delivered at lag 1 = 1
      BOUNCED   the stand-in has no bounce branch = 0
    """
    totals: Counter = Counter()
    for segments in results["funnel"].values():
        for counts in segments.values():
            totals.update(counts)
    assert totals["SAW"] == 15
    assert totals["CLICKED"] == 11
    assert totals["BROWSED"] == 11
    assert totals["CARTED"] == 1
    assert totals["BOUGHT"] == 1
    assert totals["EXPERIENCED"] == 1
    assert totals["BOUNCED"] == 0


def test_the_full_evidence_chain_is_present_in_order(records):
    """One shopper, one story: exposure -> click -> page -> cart -> purchase ->
    the need closing with its cause -> the delivery coming back as experience.
    This is the chain PLAN 6.2 asks the golden to contain."""
    mine = [(r["type"], r["t"]) for r in records
            if r.get("shopper_id", 0) % 100_000 == NEED_OFFSET]
    order = [t for t, _ in mine]
    for etype in ("NEED_ACTIVATED", "SAW", "CLICKED", "VISITED", "PRICE_SEEN",
                  "BROWSED", "CARTED", "BOUGHT", "NEED_SATISFIED", "EXPERIENCED"):
        assert etype in order, etype
    assert order.index("BOUGHT") < order.index("EXPERIENCED")
    assert order.index("CARTED") < order.index("BOUGHT")

    t0 = min(t for _, t in mine)
    day = {t: (t - t0) // 86_400 for _, t in mine}
    at = {etype: day[t] for etype, t in mine}
    assert at["NEED_ACTIVATED"] == 0
    assert at["BOUGHT"] == 1          # day 2: the reference price exists now
    assert at["NEED_SATISFIED"] == 1  # satisfied by that purchase
    assert at["EXPERIENCED"] == 2     # fulfillment lag 1

    satisfied = next(r for r in records if r["type"] == "NEED_SATISFIED"
                     and r["shopper_id"] % 100_000 == NEED_OFFSET)
    assert satisfied["cause_kind"] == "BOUGHT" and satisfied["cause_id"] == 3000001


# ---------------------------------------------------------------------------
# the Phase-6 metrics recompute from the committed state
# ---------------------------------------------------------------------------


def test_ci_recomputes_from_the_committed_snapshot(results, accumulator):
    """The bootstrap is seeded from the run seed alone, so it reproduces off
    the snapshot without the graph, the log, or the original process."""
    ci = metrics.funnel_ci(accumulator.by_shopper, BY_SHOPPER_FIELDS,
                           accumulator.segment_by_offset, seed=58)
    assert ci == results["ci"]


def test_ci_brackets_the_point_estimates(results):
    """11 clicks on 15 exposures = 0.7333, inside its own interval; the buy
    rate is 1/1 so both ends sit on 1.0."""
    assert results["ci"]["ctr"][0] <= 11 / 15 <= results["ci"]["ctr"][1]
    assert results["ci"]["ctr"] == [0.66667, 0.86667]
    assert results["ci"]["buy_rate"] == [1.0, 1.0]
    assert results["ci"]["p_buy_need_on"] == [0.5, 0.5]
    assert results["ci"]["p_buy_need_off"] == [0.0, 0.0]


def test_fatigue_split_recomputes_and_reads_as_expected(results, accumulator):
    rows = metrics.fatigue_rows(accumulator.fatigue)
    assert rows == results["fatigue_split"]

    brand = results["fatigue_split"]["brand_msg"]
    # days 1-2 run creative 2000003 alone, and brand_semantic_fatigue needs a
    # DIFFERENT same-brand creative in the SAW window -> nothing to be tired of
    assert [r["mean"] for r in brand[:2]] == [0.0, 0.0]
    # day 3 switches to 2000001, which shares ECO_FRIENDLY and the brand with
    # the two exposures already behind it -> the channel lights up
    assert brand[2]["mean"] == pytest.approx(0.47455, abs=1e-5)
    assert brand[2]["n"] == 5

    # asset wearout cannot move in a 3-tick run: exposures_72h peaks at 2 at
    # the moment of the day-3 decision, and wearout is free below 3.
    assert [r["mean"] for r in results["fatigue_split"]["asset"]] == [0.0, 0.0, 0.0]
    # concept saturation needs a RIVAL brand's creative; only 6001 flies here
    assert [r["mean"] for r in results["fatigue_split"]["concept"]] == [0.0, 0.0, 0.0]


def test_fatigue_channel_agrees_with_motif_stats(results):
    """Two independent accumulators, one number: the motif's mean strength over
    the whole run must equal the day-3 channel mean, because day 3 is the only
    day the motif appears and all five decisions carried it."""
    assert (results["motif_stats"]["brand_semantic_fatigue"]["mean_strength"]
            == results["fatigue_split"]["brand_msg"][2]["mean"])
    assert (results["motif_stats"]["brand_semantic_fatigue"]["prevalence_by_outcome"]
            == {"CLICK": 5})


def test_fatigue_ctr_columns_account_for_every_click(results):
    """Per tick, high + low decisions = all decisions, and their clicks sum to
    that tick's clicks: 1 on day 1 (the need shopper) then 5 and 5."""
    per_tick = []
    for row in results["fatigue_split"]["asset"]:
        hi = (row["high_ctr"] or 0) * row["high_n"]
        lo = (row["low_ctr"] or 0) * row["low_n"]
        assert row["high_n"] + row["low_n"] == row["n"] == 5
        per_tick.append(round(hi + lo))
    assert per_tick == [1, 5, 5] and sum(per_tick) == 11


def test_repeat_ltv_recomputes(results, accumulator):
    rows = metrics.repeat_ltv(accumulator.by_shopper, BY_SHOPPER_FIELDS,
                              accumulator.revenue_by_shopper, "golden")
    assert rows == results["repeat_ltv_by_arm"]
    assert rows[0]["buyers"] == 1 and rows[0]["revenue_per_buyer"] == 39.0
    assert rows[0]["repeat_rate"] == 0.0  # one purchase, no repeat


def test_bounce_delta_is_a_within_run_number(results, accumulator):
    """Both seeded variants got visits (2 shoppers on 4000002, 3 on 4000001 for
    creative 2000003), and the stand-in never bounces, so the honest answer is
    exactly zero — not None, which would mean "no A/B here"."""
    pages = results["funnel_by_page"]
    assert set(pages) == {"4000001", "4000002"}
    assert all(p["bounce_rate"] == 0.0 for p in pages.values())
    assert results["violations"]["bounce_delta"] == 0.0
    assert metrics.bounce_delta(pages, accumulator.page_pairs) == 0.0


# ---------------------------------------------------------------------------
# beliefs, provenance, and the goal claim
# ---------------------------------------------------------------------------


def test_provenance_is_complete_and_never_cites_exposure(results):
    """Law 14 / F7 as a metric: every learned preference version carries a
    behavioral receipt, and SAW is never one of them. The same-tick fold rule
    stamps a version with its DEEPEST cause, which is why BROWSED dominates and
    CLICKED does not appear on its own."""
    pc = results["provenance_coverage"]
    assert pc["coverage"] == 1.0 and pc["belief_scope"] == "live"
    assert pc["prefers"]["with_cause"] == pc["prefers"]["learned_versions"] == 29
    assert pc["prefers"]["versions"] == 47  # 18 priors + 29 learned versions
    assert pc["beliefs"]["with_provenance"] == pc["beliefs"]["versions"] == 5
    kinds = pc["prefers"]["cause_kinds"]
    assert kinds == {"BOUGHT": 1, "BROWSED": 25, "EXPERIENCED": 3}
    assert "SAW" not in kinds and "none" not in kinds


def test_belief_confidence_distribution_covers_every_live_belief(results):
    dist = results["belief_confidence_dist"]
    assert {r["aspect"] for r in dist} == {"trust"}
    assert sum(r["count"] for r in dist) == 5  # one trust belief per shopper
    # four shoppers sit in [0.6, 0.7) on one browse-and-click day; the buyer,
    # who also took a delivery, is the lone occupant of [0.9, 1.0)
    filled = {(r["bin_lo"], r["count"]) for r in dist if r["count"]}
    assert filled == {(0.6, 4), (0.9, 1)}


def test_belief_drift_series_rise_with_evidence(results):
    pop = [r for r in results["belief_drift"] if r["segment"] == "all"]
    assert len(pop) == 1
    row = pop[0]
    assert row["aspect"] == "trust" and row["about"] == 6001
    assert len(row["series"]) == 3 and len(row["confidence_series"]) == 3
    assert row["series"] == [0.6, 0.60333, 0.61482]
    # confidence is monotone: evidence only accumulates
    assert row["confidence_series"] == sorted(row["confidence_series"])


def test_goal_lift_is_the_demo_claim(results):
    """The one shopper with a need converted on one of its two page decisions;
    the four without a need converted on none of their nine. This is F9 in
    miniature — and the CI on both is degenerate because the counts are tiny,
    which is exactly what an honest interval should say."""
    gs = results["goal_stats"]
    assert gs["p_buy_need_on"] == 0.5 and gs["p_buy_need_off"] == 0.0
    assert gs["decisions_need_on"] == 2 and gs["decisions_need_off"] == 9
    assert gs["time_to_satisfaction"] == [1]


def test_shelf_never_moves_and_the_reference_price_learns_it(results):
    """The demo promo schedule's first window opens at tick 3, past the end of
    this run, so the hero stays at list. Reference prices converge on 39.00 as
    shoppers see the price."""
    traj = results["reference_price_trajectory"]
    assert [r["current_price"] for r in traj] == [39.0, 39.0, 39.0]
    assert [r["mean_reference_price"] for r in traj] == [39.0, 39.0, 39.0]
    assert [r["n_holders"] for r in traj] == [1, 5, 5]


def test_first_learned_version_of_an_unheld_concept_saturates(results):
    """A pinned OBSERVATION, not an endorsement.

    evidence.blend() starts an unheld concept at (w=0, E=0), so the first
    behavioral event sets w = PREF_TARGET = 1.0 outright: with no prior
    evidence, the observation is all the evidence there is. Shoppers who DID
    hold a prior (E0 = 2) blend normally. The effect predates Phase 6 and lives
    in evidence.py, which is frozen by hash (Law 13) — it is pinned here so
    that if anyone ever changes the cold-start rule, this fails loudly and on
    purpose rather than silently reshaping every drift chart.
    """
    saturated = [row for row in results["preference_drift"]
                 if all(v in (None, 1.0) for v in row["series"])]
    assert saturated, "expected cold-start concepts pinned at 1.0"
