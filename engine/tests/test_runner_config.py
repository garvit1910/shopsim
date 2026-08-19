"""Phase 3: run_config loading, hashing, page resolution, validation."""

import json
from pathlib import Path

import pytest

from shopsim.minds.objective_view import ObjectiveView
from shopsim.runner.config import RunConfig

REPO = Path(__file__).resolve().parents[2]
CFG_PATH = REPO / "fixtures" / "run-configs" / "scripted-run-1.json"


@pytest.fixture(scope="module")
def cfg() -> RunConfig:
    return RunConfig.load(CFG_PATH)


@pytest.fixture(scope="module")
def view() -> ObjectiveView:
    return ObjectiveView.from_catalog(REPO / "fixtures" / "demo-brand")


def absolutized() -> dict:
    """The repo config with paths made absolute, loadable from a tmp dir."""
    raw = json.loads(CFG_PATH.read_text())
    raw["population"]["personas"] = str(REPO / raw["population"]["personas"])
    raw["catalog_dir"] = str(REPO / raw["catalog_dir"])
    raw["perception_cache"] = str(REPO / raw["perception_cache"])
    raw["goals"]["config"] = str(REPO / raw["goals"]["config"])
    raw["promos"]["schedule"] = str(REPO / raw["promos"]["schedule"])
    return raw


def test_loads_and_validates(cfg):
    assert cfg.label == "scripted-run-1"
    assert cfg.ticks == 14 and cfg.population_size == 200
    assert cfg.mind_decide == "scripted" and cfg.mind_consolidate == "formula"
    assert [a.name for a in cfg.arms] == ["need_on", "need_off"]
    assert cfg.arm("need_off").branch_from == "need_on"


def test_config_hash_is_canonical_and_arm_scoped(cfg, tmp_path):
    # same content, different key order => same hash
    raw = absolutized()
    p1 = tmp_path / "orig.json"
    p1.write_text(json.dumps(raw))
    p2 = tmp_path / "shuffled.json"
    p2.write_text(json.dumps(dict(reversed(list(raw.items())))))
    assert RunConfig.load(p1).config_hash("need_on") == \
        RunConfig.load(p2).config_hash("need_on")
    # arm name is part of the identity
    assert cfg.config_hash("need_on") != cfg.config_hash("need_off")


def test_goal_overrides_merge(cfg):
    on = cfg.goal_overrides(cfg.arm("need_on"))
    off = cfg.goal_overrides(cfg.arm("need_off"))
    assert on == {"scripted_enabled": True, "waves_enabled": True}
    assert off == {"scripted_enabled": False, "waves_enabled": False}


def test_page_resolution_default_and_gap(cfg, view):
    pages = cfg.resolve_pages(view)
    # both scheduled creatives offer 3000001 -> the consistent variant 4000001
    assert pages == {2000001: 4000001, 2000003: 4000001}

    # A creative whose products have no page resolves to nothing — its funnel
    # ends at CLICK (CONTRACT v3.3). Every stock creative's product HAS a page
    # since the Phase-5 fixture addition (4000003-4000005), so the gap is
    # exercised against a view stripped of page stimuli rather than by naming
    # a creative that happens to be uncovered today.
    from dataclasses import replace

    pageless = replace(view, stimuli={sid: f for sid, f in view.stimuli.items()
                                      if f.kind != "page"})
    assert cfg.resolve_pages(pageless) == {}


def test_every_stock_creative_can_convert(cfg, view):
    """Each demo creative must land somewhere: in a SHARED market an ad with
    no page still wins impressions on CTR while earning nothing, which reads
    as a broken market rather than a modelled one."""
    from shopsim.runner.config import ScheduleRow

    schedule = tuple(
        ScheduleRow(creative_id=cid, start_tick=0, end_tick=5, reach_prob=0.2)
        for cid in (2000001, 2000002, 2000003, 2000004, 2000005))
    pages = cfg.resolve_pages(view, schedule=schedule)
    assert set(pages) == {2000001, 2000002, 2000003, 2000004, 2000005}


def test_page_override_honored(view, tmp_path):
    raw = absolutized()
    raw["exposure"]["schedule"][1]["page_id"] = 4000002
    p = tmp_path / "c.json"
    p.write_text(json.dumps(raw))
    pages = RunConfig.load(p).resolve_pages(view)
    assert pages[2000003] == 4000002


@pytest.mark.parametrize("mutate, phrase", [
    (lambda r: r["arms"][1].update(branch_from="nope"), "unknown branch_from"),
    (lambda r: r["arms"][1].update(divergence_tick=99), "divergence_tick"),
    (lambda r: r["exposure"]["schedule"][0].update(reach_prob=1.5), "reach_prob"),
    (lambda r: r.update(ticks=0), "ticks"),
    (lambda r: r["mind"].update(decide="llm"), "mind"),
])
def test_validation_rejects(tmp_path, mutate, phrase):
    raw = absolutized()
    mutate(raw)
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match=phrase):
        RunConfig.load(p)
