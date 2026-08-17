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
    # a creative whose product has no page resolves to nothing (funnel ends at CLICK)
    raw = absolutized()
    raw["exposure"]["schedule"].append(
        {"creative_id": 2000005, "start_tick": 0, "end_tick": 3, "reach_prob": 0.1})
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "c.json"
        p.write_text(json.dumps(raw))
        cfg2 = RunConfig.load(p)
    assert 2000005 not in cfg2.resolve_pages(view)


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
