"""Phase 4: cross-arm comparison reports (CONTRACT v3.4-draft) — cross-arm
deltas live in comparison.json, never in a single run's results.json."""

import pytest

from shopsim.experiments.compare import build_comparison


def results_stub(arm: str, *, funnel_seg, by_creative=None, by_page=None,
                 ref_traj=None, goal_stats=None) -> dict:
    return {
        "funnel": {arm: funnel_seg},
        "funnel_by_creative": by_creative or {},
        "funnel_by_page": by_page or {},
        "reference_price_trajectory": ref_traj or [],
        "goal_stats": goal_stats or {"p_buy_need_on": None, "p_buy_need_off": None},
    }


def test_ad_comparison_table():
    raw = {"experiment": {"type": "ad_test", "name": "ads", "spec": {
        "creatives": [{"creative_id": 2000001}, {"creative_id": 2000006}]}}}
    results = {
        "c2000001": results_stub(
            "c2000001", funnel_seg={"1001": {"BOUGHT": 2}},
            by_creative={"2000001": {
                "SAW": 40, "CLICKED": 4, "BROWSED": 3, "BOUNCED": 0,
                "CARTED": 2, "BOUGHT": 2}}),
        "c2000006": results_stub(
            "c2000006", funnel_seg={"1001": {"BOUGHT": 0}},
            by_creative={"2000006": {
                "SAW": 40, "CLICKED": 1, "BROWSED": 1, "BOUNCED": 0,
                "CARTED": 0, "BOUGHT": 0}}),
    }
    cmp = build_comparison(raw, results)
    table = cmp["ad_test"]["creatives"]
    assert [row["creative"] for row in table] == [2000001, 2000006]
    assert table[0]["ctr"] == 0.1
    assert table[0]["BOUGHT"] == 2
    assert table[1]["ctr"] == 0.025
    # merged funnel keyed by every arm
    assert set(cmp["funnel"]) == {"c2000001", "c2000006"}


def test_page_ab_comparison_bounce_delta():
    raw = {"experiment": {"type": "page_ab", "name": "ab", "spec": {
        "page_ids": [4000001, 4000002]}}}
    results = {"ab": results_stub(
        "ab", funnel_seg={},
        by_page={
            "4000001": {"VISITED": 18, "BROWSED": 15, "BOUNCED": 2,
                        "bounce_rate": 0.1},
            "4000002": {"VISITED": 12, "BROWSED": 8, "BOUNCED": 8,
                        "bounce_rate": 0.4},
        })}
    cmp = build_comparison(raw, results)
    section = cmp["page_ab"]
    # variant B (spec order, the violating page) minus variant A: positive
    assert section["bounce_delta"] == 0.3
    assert section["pages"]["4000002"]["BOUNCED"] == 8


def test_pricing_comparison_ref_price_drift():
    raw = {"experiment": {"type": "pricing", "name": "promo", "spec": {}}}
    traj = [
        {"tick": 0, "current_price": 39.0, "mean_reference_price": None},
        {"tick": 3, "current_price": 33.15, "mean_reference_price": 38.2},
        {"tick": 13, "current_price": 31.2, "mean_reference_price": 35.4},
    ]
    results = {
        "promo_off": results_stub("promo_off",
                                  funnel_seg={"1001": {"BOUGHT": 3}},
                                  ref_traj=[{"tick": 0, "current_price": 39.0,
                                             "mean_reference_price": 39.0}]),
        "promo_on": results_stub("promo_on",
                                 funnel_seg={"1001": {"BOUGHT": 5}},
                                 ref_traj=traj),
    }
    cmp = build_comparison(raw, results)
    on = cmp["pricing"]["arms"]["promo_on"]
    assert on["first_mean_reference_price"] == 38.2
    assert on["last_mean_reference_price"] == 35.4
    assert on["reference_price_drift"] == -2.8  # downward: the F4 exhibit
    assert on["bought_total"] == 5
    assert cmp["pricing"]["arms"]["promo_off"]["reference_price_drift"] is None


def test_scenario_comparison_goal_stats():
    raw = {"experiment": {"type": "scenario", "name": "wave", "spec": {}}}
    results = {
        "wave_on": results_stub("wave_on", funnel_seg={"1008": {"BOUGHT": 7}},
                                goal_stats={"p_buy_need_on": 0.5,
                                            "p_buy_need_off": 0.1}),
        "wave_off": results_stub("wave_off", funnel_seg={"1008": {"BOUGHT": 2}},
                                 goal_stats={"p_buy_need_on": None,
                                             "p_buy_need_off": 0.1}),
    }
    cmp = build_comparison(raw, results)
    assert cmp["scenario"]["arms"]["wave_on"]["bought_total"] == 7
    assert cmp["scenario"]["arms"]["wave_off"]["bought_total"] == 2
    assert cmp["experiment"]["arms"] == ["wave_off", "wave_on"]


# -- ladder vs control (v3.7-draft) -----------------------------------------


def _ladder_raw(levels):
    return {"experiment": {"type": "pricing", "name": "ladder", "spec": {
        "discount_levels": levels,
        "promo": {"product_promos": [{"product_id": 3000101, "cycles": [
            {"cycle": 1, "start_tick": 2, "end_tick": 5, "discount_pct": 0.0}]}]},
    }}}


def _arm_results(arm, *, revenue, bought, by_creative):
    return {
        "funnel": {arm: {"1001": {"BOUGHT": bought}}},
        "funnel_by_creative": {str(cid): {"SAW": v["saw"], "CLICKED": v["clicked"],
                                          "BROWSED": 0, "CARTED": 0, "BOUGHT": v["bought"]}
                               for cid, v in by_creative.items()},
        "revenue": {"total": revenue,
                    "by_creative": {str(cid): v["revenue"] for cid, v in by_creative.items()}},
        "reference_price_trajectory": [],
        "goal_stats": {},
    }


def test_ladder_reports_every_depth_against_the_control():
    """The launcher always sends a 0% arm, so each depth can be read as a
    change from running the same ads at full price."""
    raw = _ladder_raw([0.0, 0.2, 0.4])
    results = {
        "d0": _arm_results("d0", revenue=400.0, bought=4, by_creative={
            2000103: {"saw": 100, "clicked": 10, "bought": 2, "revenue": 218.0},
            2000105: {"saw": 100, "clicked": 8, "bought": 2, "revenue": 182.0}}),
        "d20": _arm_results("d20", revenue=560.0, bought=6, by_creative={
            2000103: {"saw": 100, "clicked": 14, "bought": 4, "revenue": 380.0},
            2000105: {"saw": 100, "clicked": 8, "bought": 2, "revenue": 180.0}}),
        "d40": _arm_results("d40", revenue=300.0, bought=5, by_creative={
            2000103: {"saw": 100, "clicked": 16, "bought": 4, "revenue": 260.0},
            2000105: {"saw": 100, "clicked": 7, "bought": 1, "revenue": 40.0}}),
    }
    section = build_comparison(raw, results)["pricing"]

    assert section["control_level"] == 0.0
    assert [r["level"] for r in section["ladder"]] == [0.0, 0.2, 0.4]
    # 20% earns the most; 40% discounts past the point of paying for itself
    assert section["best_level"] == 0.2

    d20 = next(r for r in section["ladder"] if r["level"] == 0.2)
    assert d20["vs_control"]["control_arm"] == "d0"
    assert d20["vs_control"]["revenue_delta"] == 160.0
    assert d20["vs_control"]["revenue_lift_pct"] == 40.0
    assert d20["vs_control"]["bought_delta"] == 2

    # per-ad: the sale creative gained, the lifestyle one was flat
    by_ad = d20["vs_control"]["by_creative"]
    assert by_ad["2000103"]["revenue_delta"] == 162.0
    assert by_ad["2000103"]["bought_delta"] == 2
    assert by_ad["2000105"]["revenue_delta"] == -2.0
    assert by_ad["2000103"]["ctr_delta"] == pytest.approx(0.04)

    # the control compares against itself: all zeros, never None
    control = next(r for r in section["ladder"] if r["level"] == 0.0)
    assert control["vs_control"]["revenue_delta"] == 0.0


def test_ladder_without_a_control_still_reports_depths():
    """A hand-written spec may omit 0%. The section must degrade rather than
    crash — it simply has nothing to compare against."""
    raw = _ladder_raw([0.2, 0.4])
    results = {
        "d20": _arm_results("d20", revenue=100.0, bought=1, by_creative={
            2000103: {"saw": 10, "clicked": 2, "bought": 1, "revenue": 100.0}}),
        "d40": _arm_results("d40", revenue=90.0, bought=1, by_creative={
            2000103: {"saw": 10, "clicked": 3, "bought": 1, "revenue": 90.0}}),
    }
    section = build_comparison(raw, results)["pricing"]
    assert section["control_level"] is None
    assert section["best_level"] == 0.2
    assert all("vs_control" not in r for r in section["ladder"])


def test_ladder_rows_carry_per_creative_funnels():
    raw = _ladder_raw([0.0, 0.3])
    results = {
        "d0": _arm_results("d0", revenue=50.0, bought=1, by_creative={
            2000103: {"saw": 40, "clicked": 4, "bought": 1, "revenue": 50.0}}),
        "d30": _arm_results("d30", revenue=80.0, bought=2, by_creative={
            2000103: {"saw": 40, "clicked": 6, "bought": 2, "revenue": 80.0}}),
    }
    section = build_comparison(raw, results)["pricing"]
    rung = next(r for r in section["ladder"] if r["level"] == 0.3)
    row = rung["creatives"][0]
    assert row["creative"] == 2000103
    assert (row["SAW"], row["CLICKED"], row["BOUGHT"]) == (40, 6, 2)
    assert row["ctr"] == pytest.approx(0.15)
    assert row["revenue"] == 80.0
