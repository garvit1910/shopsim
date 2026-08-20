"""Calibration arithmetic, profile round-tripping, and chart determinism."""

import json
from pathlib import Path

import pytest

from shopsim.eval import calibrate as K
from shopsim.eval import charts, contexts as C, oracle as O

REPO = C.repo_root()


# ---------------------------------------------------------------------------
# bands + loss
# ---------------------------------------------------------------------------


def test_every_target_band_carries_its_source():
    """A number without its citation is an opinion. market-research.md is the
    only place these are allowed to come from."""
    for name, (lo, hi, source) in K.TARGETS.items():
        assert 0.0 < lo < hi <= 1.0, name
        assert "market-research.md" in source, f"{name} cites nothing"


def test_loss_is_zero_inside_the_band_and_scales_outside_it():
    lo, hi, _ = K.TARGETS["p_click"]
    assert K._band_loss((lo + hi) / 2, lo, hi) == 0.0
    assert K._band_loss(lo, lo, hi) == 0.0
    assert K._band_loss(hi, lo, hi) == 0.0
    assert K._band_loss(lo / 2, lo, hi) == pytest.approx(0.5)
    assert K._band_loss(hi * 2, lo, hi) == pytest.approx(1.0)
    assert K._band_loss(None, lo, hi) == 1.0


def test_loss_is_relative_so_metrics_of_different_scale_count_equally():
    """CTR lives near 0.01 and bounce near 0.5. An absolute loss would let a
    1pp CTR miss dominate a 20pp bounce miss."""
    ctr_lo, _ctr_hi, _ = K.TARGETS["p_click"]
    b_lo, _b_hi, _ = K.TARGETS["bounce_rate"]
    half_ctr = K._band_loss(ctr_lo / 2, ctr_lo, K.TARGETS["p_click"][1])
    half_bounce = K._band_loss(b_lo / 2, b_lo, K.TARGETS["bounce_rate"][1])
    assert half_ctr == pytest.approx(half_bounce)


def test_in_band_agrees_with_loss():
    rates = {"p_click": 0.012, "bounce_rate": 0.70, "p_cart_given_browse": 0.15,
             "p_buy_given_cart": 0.26, "visit_to_purchase": 0.02}
    flags = K.in_band(rates)
    assert flags["p_click"] and not flags["bounce_rate"]
    total, per = K.loss(rates)
    assert per["bounce_rate"] > 0 and per["p_click"] == 0
    assert total == pytest.approx(sum(per.values()))


# ---------------------------------------------------------------------------
# profiles
# ---------------------------------------------------------------------------


def test_profile_block_round_trips_through_the_run_config_parser():
    """A fitted profile has to be loadable as a real `calibration` block, or the
    thing that was certified is not the thing that runs."""
    from shopsim.runner.config import parse_calibration

    base = C.Profile("x")
    tuned = K._with(base, ("stage_bases", "BUY"), 2.85)
    tuned = K._with(tuned, ("choice", "delta_wearout"), 0.9)
    block = K.profile_block(tuned)
    ap, cp, sb = parse_calibration(block)
    assert dict(sb)["BUY"] == pytest.approx(2.85)
    assert cp.delta_wearout == pytest.approx(0.9)
    assert ap == base.appraisal


def test_profile_block_omits_what_did_not_move():
    block = K.profile_block(C.Profile("untouched"))
    assert block == {}, "a profile identical to the defaults should say nothing"


def test_committed_reference_profile_is_loadable_and_pins_the_phase7_decisions():
    raw = json.loads((REPO / "eval" / "profiles" / "reference.json").read_text())
    block = raw["calibration"]
    from shopsim.runner.config import parse_calibration, parse_retrieval

    parse_calibration({k: v for k, v in block.items() if k != "retrieval"})
    params = parse_retrieval(block["retrieval"])
    assert params.pref_recency_half_life_s == 30 * 86_400
    assert params.violation_min_strength == 0.5


def test_retrieval_block_refuses_a_typo():
    from shopsim.runner.config import parse_retrieval

    with pytest.raises(ValueError, match="unknown keys"):
        parse_retrieval({"pref_recency_halflife_s": 10})


def test_run_config_hash_covers_the_retrieval_block():
    """If retrieval params were not hashed, a replay could legally retrieve
    differently than the original run."""
    from shopsim.runner.config import RunConfig

    cfg = RunConfig.load(REPO / "eval" / "configs" / "reference.json")
    before = cfg.config_hash("reference")
    cfg.raw["calibration"] = {"retrieval": {"violation_min_strength": 0.9}}
    assert cfg.config_hash("reference") != before


# ---------------------------------------------------------------------------
# rank agreement
# ---------------------------------------------------------------------------


def test_spearman_matches_hand_computed_cases():
    assert O.spearman([1, 2, 3, 4], [1, 2, 3, 4]) == pytest.approx(1.0)
    assert O.spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    assert O.spearman([1, 1, 1, 1], [1, 2, 3, 4]) is None  # zero variance
    assert O.spearman([1, 2], [2, 1]) is None  # too few points


def test_average_ranks_handle_ties():
    assert O._ranks([10, 20, 20, 30]) == [1.0, 2.5, 2.5, 4.0]


def test_preference_fit_reproduces_retrievals_single_strongest_rule():
    """reads.py keeps ONE hit, ranked by (prior weight x claim strength), and
    reports that hit's weight. Getting this wrong made every creative look
    identical to the mind — which is what the rank study caught."""
    pop = C.population(7, 40)
    view = C.catalog_view()
    stim = view.facts(2000003)  # LIGHTWEIGHT .8, ECO_FRIENDLY .8, DISCOUNT .9
    hits = 0
    for sh in pop:
        got = C.preference_fit_for(sh, stim)
        if got is None:
            continue
        hits += 1
        concept, w = got
        priors = dict(sh.priors)
        assert concept in priors and concept in stim.claims
        best = max((priors[c] * s, c) for c, s in stim.claims.items() if c in priors)
        assert concept == best[1]
        assert w == pytest.approx(priors[concept])
    assert hits, "this catalog should match at least one prior in the population"


def test_rank_agreement_discriminates_between_creatives():
    study = O.rank_agreement(seeds=(11, 23), size=150)
    sims = study["per_seed"][0]["sim"]
    assert len(set(sims)) == len(sims), \
        "identical sim scores mean the creative's claims are not reaching the mind"
    assert study["caveat"], "the construct-validity limit must be stated"


# ---------------------------------------------------------------------------
# charts
# ---------------------------------------------------------------------------


def test_charts_are_deterministic_and_well_formed():
    def build():
        c = charts.Chart("t", subtitle="s", x_label="x", y_label="y")
        pts = [(i, 0.01 + 0.003 * (i % 4)) for i in range(1, 10)]
        c.axes([p[0] for p in pts], [p[1] for p in pts])
        c.band(0.005, 0.02, "band")
        c.line(pts, label="series")
        c.note("note")
        return c.render()

    a, b = build(), build()
    assert a == b, "SVG output must be byte-identical for identical input"
    assert a.startswith("<svg") and a.rstrip().endswith("</svg>")
    assert "nan" not in a.lower() and "None" not in a


def test_axis_labels_never_leak_float_noise():
    assert charts._fmt(0.1) == "0.1"
    assert charts._fmt(0.30000000000000004) == "0.3"
    assert charts._fmt(0) == "0"
    assert charts._fmt(1500) == "1500"


def test_chart_escapes_text_it_did_not_write():
    c = charts.Chart("<script>x</script>")
    c.axes([0, 1], [0, 1])
    assert "<script>" not in c.render()


def test_degenerate_series_do_not_crash_the_axis():
    c = charts.Chart("flat")
    c.axes([1, 1], [0.5, 0.5])
    out = c.render()
    assert out.startswith("<svg")
