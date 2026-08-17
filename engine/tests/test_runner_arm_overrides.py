"""Phase 4: per-arm exposure/promo overrides, page splits, calibration block,
and the fixture-invariance guarantee (CONTRACT v3.4-draft).

The golden test at the bottom is the byte-identity gate: the committed
scripted-run-1 fixture's config_hash must never move under Phase-4 config
changes.
"""

import json
from pathlib import Path

import pytest

from shopsim.minds.calibration import (
    DEFAULT_APPRAISAL_PARAMS,
    DEFAULT_CHOICE_PARAMS,
    DEFAULT_STAGE_BASES,
)
from shopsim.minds.objective_view import ObjectiveView
from shopsim.runner.config import RunConfig

REPO = Path(__file__).resolve().parents[2]
CFG_PATH = REPO / "fixtures" / "run-configs" / "scripted-run-1.json"


def absolutized() -> dict:
    raw = json.loads(CFG_PATH.read_text())
    raw["population"]["personas"] = str(REPO / raw["population"]["personas"])
    raw["catalog_dir"] = str(REPO / raw["catalog_dir"])
    raw["perception_cache"] = str(REPO / raw["perception_cache"])
    raw["goals"]["config"] = str(REPO / raw["goals"]["config"])
    raw["promos"]["schedule"] = str(REPO / raw["promos"]["schedule"])
    return raw


def load(tmp_path, raw) -> RunConfig:
    p = tmp_path / "c.json"
    p.write_text(json.dumps(raw))
    return RunConfig.load(p)


@pytest.fixture(scope="module")
def view() -> ObjectiveView:
    return ObjectiveView.from_catalog(REPO / "fixtures" / "demo-brand")


# -- schedule_for -----------------------------------------------------------


def test_schedule_for_no_overrides_returns_shared_object(tmp_path):
    cfg = load(tmp_path, absolutized())
    for arm in cfg.arms:
        assert cfg.schedule_for(arm) is cfg.schedule


def test_schedule_for_replace_and_add(tmp_path):
    raw = absolutized()
    raw["arms"].append({
        "name": "solo",
        "exposure_overrides": {"schedule": [
            {"creative_id": 2000002, "start_tick": 0, "end_tick": 3,
             "reach_prob": 0.5}]},
    })
    raw["arms"].append({
        "name": "extra",
        "exposure_overrides": {"add": [
            {"creative_id": 2000002, "start_tick": 0, "end_tick": 3,
             "reach_prob": 0.5}]},
    })
    cfg = load(tmp_path, raw)
    solo = cfg.schedule_for(cfg.arm("solo"))
    assert [r.creative_id for r in solo] == [2000002]
    extra = cfg.schedule_for(cfg.arm("extra"))
    # appended row re-sorted into (creative_id, start_tick) order
    assert [r.creative_id for r in extra] == [2000001, 2000002, 2000003]
    # the base schedule is untouched
    assert [r.creative_id for r in cfg.schedule] == [2000001, 2000003]


def test_schedule_for_parses_new_row_fields(tmp_path):
    raw = absolutized()
    raw["arms"].append({
        "name": "targeted",
        "exposure_overrides": {"schedule": [
            {"creative_id": 2000003, "start_tick": 0, "end_tick": 5,
             "reach_prob": 0.4, "audience_segments": [1003, 1012],
             "page_ids": [4000001, 4000002]}]},
    })
    cfg = load(tmp_path, raw)
    row = cfg.schedule_for(cfg.arm("targeted"))[0]
    assert row.audience_segments == (1003, 1012)
    assert row.page_ids == (4000001, 4000002)


# -- promos_for -------------------------------------------------------------


def test_promos_for_default_and_overrides(tmp_path):
    raw = absolutized()
    raw["arms"].append({"name": "off", "promo_overrides": {"enabled": False}})
    raw["arms"].append({"name": "zeroed", "promo_overrides": {"schedule_inline": {
        "product_promos": [{"product_id": 3000001, "cycles": [
            {"cycle": 1, "start_tick": 3, "end_tick": 5, "discount_pct": 0.0}]}]}}})
    cfg = load(tmp_path, raw)

    enabled, path, inline = cfg.promos_for(cfg.arm("need_on"))
    assert enabled and path == cfg.promo_path and inline is None
    enabled, _, _ = cfg.promos_for(cfg.arm("off"))
    assert not enabled
    enabled, path, inline = cfg.promos_for(cfg.arm("zeroed"))
    assert enabled and path is None
    assert inline["product_promos"][0]["product_id"] == 3000001


# -- page splits + resolution -----------------------------------------------


def test_page_splits_and_resolution_exclusion(tmp_path, view):
    raw = absolutized()
    raw["exposure"]["schedule"][1]["page_ids"] = [4000001, 4000002]
    cfg = load(tmp_path, raw)
    assert cfg.page_splits() == {2000003: (4000001, 4000002)}
    pages = cfg.resolve_pages(view)
    # the split row resolves through the seeded draw, never the static map
    assert 2000003 not in pages
    assert pages[2000001] == 4000001


def test_resolve_pages_accepts_arm_schedule(tmp_path, view):
    raw = absolutized()
    raw["arms"].append({
        "name": "solo",
        "exposure_overrides": {"schedule": [
            {"creative_id": 2000003, "start_tick": 0, "end_tick": 5,
             "reach_prob": 0.4, "page_id": 4000002}]},
    })
    cfg = load(tmp_path, raw)
    rows = cfg.schedule_for(cfg.arm("solo"))
    assert cfg.resolve_pages(view, schedule=rows) == {2000003: 4000002}


# -- calibration block ------------------------------------------------------


def test_calibration_absent_returns_default_objects(tmp_path):
    cfg = load(tmp_path, absolutized())
    ap, cp, sb = cfg.calibration()
    assert ap is DEFAULT_APPRAISAL_PARAMS
    assert cp is DEFAULT_CHOICE_PARAMS
    assert sb is DEFAULT_STAGE_BASES


def test_calibration_overrides_land(tmp_path):
    raw = absolutized()
    raw["calibration"] = {
        "appraisal": {"offer_norm": 0.25},
        "choice": {"loss_aversion": 1.5,
                   "wearout_free_exposures": 3,
                   "stage_weights": {"BROWSE": {"expectation_alignment": 2.0}}},
        "stage_bases": {"CLICK": 5.0},
    }
    cfg = load(tmp_path, raw)
    ap, cp, sb = cfg.calibration()
    assert ap.offer_norm == 0.25
    assert ap.w_pref == DEFAULT_APPRAISAL_PARAMS.w_pref  # untouched fields keep defaults
    assert cp.loss_aversion == 1.5
    assert cp.wearout_free_exposures == 3
    assert cp.weights("BROWSE")["expectation_alignment"] == 2.0
    assert cp.weights("BROWSE")["relevance"] == DEFAULT_CHOICE_PARAMS.weights("BROWSE")["relevance"]
    assert cp.weights("CLICK") == DEFAULT_CHOICE_PARAMS.weights("CLICK")
    assert dict(sb)["CLICK"] == 5.0
    assert dict(sb)["BUY"] == dict(DEFAULT_STAGE_BASES)["BUY"]


@pytest.mark.parametrize("block, phrase", [
    ({"apraisal": {}}, "unknown keys"),
    ({"appraisal": {"offer_nrm": 0.2}}, "AppraisalParams"),
    ({"choice": {"stage_weights": {"CLICKZ": {}}}}, "stage_weights stages"),
    ({"choice": {"stage_weights": {"CLICK": {"charm": 1.0}}}}, "dims"),
    ({"stage_bases": {"SNIFF": 1.0}}, "stage_bases stages"),
])
def test_calibration_rejects_unknown_keys(tmp_path, block, phrase):
    raw = absolutized()
    raw["calibration"] = block
    with pytest.raises(ValueError, match=phrase):
        load(tmp_path, raw)


# -- validation of the new fields -------------------------------------------


@pytest.mark.parametrize("mutate, phrase", [
    (lambda r: r["arms"][0].update(exposure_overrides={"nope": []}),
     "unknown exposure_overrides"),
    (lambda r: r["arms"][0].update(exposure_overrides={
        "schedule": [], "add": []}), "both"),
    (lambda r: r["arms"][0].update(promo_overrides={"path": "x"}),
     "unknown promo_overrides"),
    (lambda r: (r["promos"].update(schedule=None, enabled=False),
                r["arms"][0].update(promo_overrides={"enabled": True})),
     "no schedule source"),
    (lambda r: r["exposure"]["schedule"][0].update(page_ids=[4000001]),
     "page_ids needs"),
    (lambda r: r["exposure"]["schedule"][0].update(page_ids=[4000001, 4000001]),
     "duplicate page_ids"),
    (lambda r: r["exposure"]["schedule"][0].update(audience_segments=[]),
     "empty audience_segments"),
    (lambda r: r["arms"][0].update(exposure_overrides={"schedule": [
        {"creative_id": 2000001, "start_tick": 4, "end_tick": 2,
         "reach_prob": 0.1}]}), "start_tick > end_tick"),
])
def test_validation_rejects_new_fields(tmp_path, mutate, phrase):
    raw = absolutized()
    mutate(raw)
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match=phrase):
        RunConfig.load(p)


# -- the byte-identity gate -------------------------------------------------


def test_fixture_config_hash_unchanged():
    """The committed fixture manifests pin the config_hash — Phase-4 config
    parsing must not move it (resume/branch of committed runs stays legal)."""
    cfg = RunConfig.load(CFG_PATH)
    for arm in ("need_on", "need_off"):
        manifest = json.loads(
            (REPO / "fixtures" / "scripted-run-1" / arm / "manifest.json").read_text())
        assert cfg.config_hash(arm) == manifest["config_hash"], arm
