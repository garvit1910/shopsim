"""Phase 4: cross-arm comparison reports (CONTRACT v3.4-draft) — cross-arm
deltas live in comparison.json, never in a single run's results.json."""

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
