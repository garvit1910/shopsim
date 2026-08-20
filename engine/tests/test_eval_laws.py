"""F1-F12 — the laws, and proof that each one can actually fail.

A face-validity suite whose assertions cannot go red is decoration. Every law
here gets both a passing case and a deliberately broken one.
"""

import json
from pathlib import Path

import pytest

from shopsim.eval import contexts as C
from shopsim.eval import laws as L

REPO = C.repo_root()


@pytest.fixture(scope="module")
def world():
    return C.population(7, 250), C.catalog_view(), C.Profile("default")


# ---------------------------------------------------------------------------
# analytic tier
# ---------------------------------------------------------------------------


def test_every_analytic_law_holds_on_the_default_profile(world):
    pop, view, profile = world
    for fn in (L.analytic_f1_frequency_response, L.analytic_f2_cold_gate,
               L.analytic_f3_discount_ordering, L.analytic_f6_abstention):
        r = fn(pop, view, profile)
        assert r.passed, f"{r.id} failed: {r.numbers}"
        assert r.threshold, f"{r.id} states no threshold"
    for fn in (L.analytic_f8_evidence_hierarchy, L.analytic_f10_confidence_differential):
        r = fn()
        assert r.passed and r.threshold


def test_f1_needs_a_real_peak_and_a_real_decline(world):
    """Kill the wearout term and F1 must go red — otherwise the law is only
    detecting that adstock saturates."""
    from dataclasses import replace

    pop, view, profile = world
    flat = replace(profile, choice=replace(profile.choice, delta_wearout=0.0))
    r = L.analytic_f1_frequency_response(pop, view, flat)
    assert not r.passed, "with no wearout there is nothing to wear out"


def test_f2_fails_if_the_cold_gate_stops_gating(world):
    from dataclasses import replace

    pop, view, profile = world
    ungated = replace(profile, appraisal=replace(
        profile.appraisal, cold_credibility_factor=1.0, cold_offer_factor=1.0,
        no_belief_credibility=0.9))
    r = L.analytic_f2_cold_gate(pop, view, ungated)
    assert not r.passed


def test_f8_matches_the_frozen_evidence_table_exactly():
    """Hand-checked against evidence.py with ONE event, w0 = 0.4, E0 = 2.0.
    CLICK carries pref_weight 0.10, so w' = (2.0*0.4 + 0.10*1.0)/(2.0 + 0.10)
    = 0.9/2.1 = 0.428571, i.e. delta_w = 0.028571."""
    from shopsim.contracts import evidence

    r = L.analytic_f8_evidence_hierarchy(w0=0.4, e0=2.0, count=1)
    expected = {}
    for name, et in (("CLICKED", evidence.EventType.CLICKED),
                     ("BROWSED", evidence.EventType.BROWSED),
                     ("CARTED", evidence.EventType.CARTED),
                     ("BOUGHT", evidence.EventType.BOUGHT)):
        wt = evidence.EVIDENCE_TABLE[et].pref_weight
        w, _e = evidence.blend(0.4, 2.0, evidence.PREF_TARGET, wt)
        expected[name] = round(w - 0.4, 6)
    assert r.numbers["delta_w"] == expected
    assert r.numbers["delta_w"]["CLICKED"] == pytest.approx(0.028571, abs=1e-6)
    assert r.numbers["delta_w"]["BOUGHT"] == pytest.approx(0.2, abs=1e-6)


def test_f10_is_a_property_of_the_one_formula_not_an_extra_mechanism():
    r = L.analytic_f10_confidence_differential()
    assert r.passed and r.numbers["ratio"] > 1.0
    # a belief with the SAME evidence on both sides cannot move differently
    same = L.analytic_f10_confidence_differential(low_e=4.0, high_e=4.0)
    assert not same.passed


# ---------------------------------------------------------------------------
# audit tier — F7a
# ---------------------------------------------------------------------------


def _golden():
    return json.loads((REPO / "fixtures" / "golden-run" / "results.json").read_text())


def test_f7a_holds_on_the_committed_golden_run():
    r = L.audit_f7a_no_learning_from_exposure({"golden-run": _golden()})
    assert r.passed and r.never_drop
    assert set(r.numbers["pooled_cause_kinds"]) <= L.LEARNED_CAUSES
    assert r.numbers["learned_versions"] > 0


def test_f7a_goes_red_the_moment_exposure_teaches_taste():
    """The failure this audit exists to catch: one confused updater putting
    preference learning back on the SAW channel."""
    poisoned = json.loads(json.dumps(_golden()))
    poisoned["provenance_coverage"]["prefers"]["cause_kinds"]["SAW"] = 1
    r = L.audit_f7a_no_learning_from_exposure({"poisoned": poisoned})
    assert not r.passed
    assert r.numbers["forbidden_causes_seen"] == {"SAW": 1}


def test_f7a_reports_runs_it_could_not_audit_rather_than_passing_them():
    r = L.audit_f7a_no_learning_from_exposure({"no-provenance": {"funnel": {}}})
    assert not r.passed, "auditing nothing is not a pass"
    assert r.numbers["runs_without_provenance"] == ["no-provenance"]


# ---------------------------------------------------------------------------
# scenario tier — driven by synthetic payloads so the arithmetic is testable
# without a database
# ---------------------------------------------------------------------------


def _funnel(saw, clicked, bought, arm="a"):
    return {"funnel": {arm: {"1001": {"SAW": saw, "CLICKED": clicked,
                                      "BOUGHT": bought}}},
            "goal_stats": {"p_buy_need_on": 0.05, "p_buy_need_off": 0.01}}


def test_f9_requires_buy_to_move_more_than_ctr():
    on = _funnel(10_000, 200, 40, "need_on")
    off = _funnel(10_000, 180, 10, "need_off")
    r = L.scenario_f9_maya_law(on, off, arm_on="need_on", arm_off="need_off")
    assert r.passed and r.never_drop
    assert r.numbers["buy_uplift_x"] > r.numbers["ctr_uplift_x"]

    # a goal that is merely a generic attention multiplier must FAIL: that is
    # the whole distinction the law draws.
    flat_on = _funnel(10_000, 400, 20, "need_on")
    flat_off = _funnel(10_000, 200, 10, "need_off")
    r2 = L.scenario_f9_maya_law(flat_on, flat_off, arm_on="need_on", arm_off="need_off")
    assert not r2.passed


def test_f5_reads_phase6s_own_bounce_delta():
    ok = {"funnel_by_page": {"4000001": {"bounce_rate": 0.46, "VISITED": 54, "BOUNCED": 46},
                             "4000002": {"bounce_rate": 0.62, "VISITED": 38, "BOUNCED": 62}},
          "violations": {"count": 120, "bounce_delta": 0.16}}
    assert L.scenario_f5_violation_bounce(ok, page_a=4000001, page_b=4000002).passed

    inverted = json.loads(json.dumps(ok))
    inverted["violations"]["bounce_delta"] = -0.05
    assert not L.scenario_f5_violation_bounce(inverted, page_a=4000001, page_b=4000002).passed

    unseen = json.loads(json.dumps(ok))
    unseen["violations"]["count"] = 0
    assert not L.scenario_f5_violation_bounce(unseen, page_a=4000001, page_b=4000002).passed


def _ctr_days(first, second, n=12):
    rows = []
    for t in range(n):
        ctr = first if t < n // 2 else second
        rows.append({"tick": t, "exposures": 1000, "clicks": int(1000 * ctr), "ctr": ctr})
    return {"ctr_by_day": rows, "fatigue_split": {"brand_msg": [
        {"tick": t, "n": 1000, "mean": 0.5} for t in range(n)]}}


def test_f12_compares_decay_not_level():
    rep = _ctr_days(0.020, 0.008)   # -60%
    rot = _ctr_days(0.010, 0.009)   # -10%
    assert L.scenario_f12_fatigue_separation(rep, rot).passed
    # identical decay, different LEVELS, must not pass
    assert not L.scenario_f12_fatigue_separation(_ctr_days(0.02, 0.01),
                                                 _ctr_days(0.01, 0.005)).passed


def test_f7b_requires_zero_clicks_and_flat_preferences():
    flat = {"funnel": {"a": {"1001": {"SAW": 5000, "CLICKED": 0}}},
            "preference_drift": [{"concept": 5003, "segment": 1001,
                                  "series": [0.5, 0.5, 0.5]}],
            "motif_stats": {}}
    assert L.scenario_f7b_heavy_exposure(flat).passed

    drifted = json.loads(json.dumps(flat))
    drifted["preference_drift"][0]["series"] = [0.5, 0.62, 0.71]
    assert not L.scenario_f7b_heavy_exposure(drifted).passed

    clicked = json.loads(json.dumps(flat))
    clicked["funnel"]["a"]["1001"]["CLICKED"] = 3
    assert not L.scenario_f7b_heavy_exposure(clicked).passed


def test_f4_measures_share_against_matched_full_price_windows():
    cycles = [(1, 3, 5, 0.15), (2, 8, 10, 0.15), (3, 12, 14, 0.20)]
    results = {"reference_price_trajectory": [{"mean_reference_price": 35.0}]}
    # cycle 1: 2 in-window vs 6 outside; cycle 3: 9 in-window vs 1 outside
    buys = {0: 2, 1: 2, 2: 2, 3: 1, 4: 1, 5: 0,
            6: 1, 7: 1, 8: 2, 9: 2, 10: 2, 11: 1,
            12: 3, 13: 3, 14: 3, 15: 0, 16: 0, 17: 1}
    r = L.scenario_f4_promo_addiction(results, cycles, buys=buys)
    assert r.numbers["promo_share_gain_pp"] > 15
    assert r.passed

    flat = {t: 2 for t in range(18)}
    assert not L.scenario_f4_promo_addiction(results, cycles, buys=flat).passed


def test_f11_needs_trust_to_diverge_in_the_right_direction():
    def payload(trust, repeat):
        return {"belief_drift": [{"aspect": "trust", "about": 6001, "segment": "all",
                                  "series": [0.5, trust], "confidence_series": []}],
                "repeat_ltv_by_arm": [{"arm": "q", "buyers": 20, "buys": 24,
                                       "repeat_rate": repeat, "revenue_per_buyer": 42.0}]}
    assert L.scenario_f11_experience_loop(payload(0.78, 0.25), payload(0.41, 0.05)).passed
    # same latent quality on both sides => no divergence => no law
    assert not L.scenario_f11_experience_loop(payload(0.6, 0.2), payload(0.6, 0.2)).passed


def test_buys_by_tick_reads_the_golden_event_log():
    buys = L.buys_by_tick(REPO / "fixtures" / "golden-run" / "events.jsonl")
    assert buys == {1: 1}, "the golden run's single purchase lands on tick 1"
