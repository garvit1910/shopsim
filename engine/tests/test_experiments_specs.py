"""Phase 4: experiment specs → run_config expansion (CONTRACT v3.4-draft).

Every builder's output must be an ordinary run_config that RunConfig.load
accepts unchanged — the experiments layer adds NO second config schema."""

import json
from pathlib import Path

import pytest

from shopsim.experiments.build import (
    build_run_config,
    materialize_calibration,
    zeroed_promos,
)
from shopsim.experiments.specs import load_pack, parse_spec
from shopsim.runner.config import RunConfig, parse_calibration

REPO = Path(__file__).resolve().parents[2]


def base_spec(stype: str, **extra) -> dict:
    return {
        "type": stype, "name": f"test-{stype.replace('_', '-')}",
        "seed": 91, "ticks": 6, "t0": 1_760_000_000,
        "population": {"size": 12,
                       "personas": str(REPO / "fixtures/demo-brand/personas.json")},
        "catalog": str(REPO / "fixtures/demo-brand"),
        "perception_cache": str(REPO / "fixtures/perception-cache"),
        "goal_config": str(REPO / "fixtures/demo-brand/goal_config.json"),
        **extra,
    }


def load_built(tmp_path, raw_cfg: dict) -> RunConfig:
    p = tmp_path / "run_config.json"
    p.write_text(json.dumps(raw_cfg))
    return RunConfig.load(p)


# -- ad_test ---------------------------------------------------------------


def test_ad_spec_one_arm_per_creative(tmp_path):
    spec = parse_spec(base_spec("ad_test", creatives=[
        {"creative_id": 2000001, "reach_prob": 0.4},
        {"creative_id": 2000003, "reach_prob": 0.4,
         "audience_segments": [1003, 1012]},
    ]))
    raw = build_run_config(spec, REPO)
    cfg = load_built(tmp_path, raw)

    assert [a.name for a in cfg.arms] == ["c2000001", "c2000003"]
    assert cfg.schedule == ()  # base schedule empty: creatives live per arm
    for arm in cfg.arms:
        rows = cfg.schedule_for(arm)
        assert len(rows) == 1
        assert f"c{rows[0].creative_id}" == arm.name
        assert rows[0].start_tick == 0 and rows[0].end_tick == 5  # spec ticks-1
    assert cfg.schedule_for(cfg.arm("c2000003"))[0].audience_segments == (1003, 1012)


def test_ad_spec_rejects_duplicates_and_empty():
    with pytest.raises(ValueError, match="at least one"):
        parse_spec(base_spec("ad_test", creatives=[]))
    with pytest.raises(ValueError, match="unique"):
        parse_spec(base_spec("ad_test", creatives=[
            {"creative_id": 2000001, "reach_prob": 0.4},
            {"creative_id": 2000001, "reach_prob": 0.5}]))


# -- ad_test shared market (v3.6-draft) -------------------------------------


def shared_spec(**market):
    return base_spec("ad_test", creatives=[
        {"creative_id": 2000001, "reach_prob": 0.2},
        {"creative_id": 2000003, "reach_prob": 0.2},
        {"creative_id": 2000004, "reach_prob": 0.2},
    ], market={"shared": True, **market})


def test_shared_market_builds_one_arm_with_every_creative(tmp_path):
    spec = parse_spec(shared_spec(allocation={"enabled": True}))
    cfg = load_built(tmp_path, build_run_config(spec, REPO))

    assert [a.name for a in cfg.arms] == ["market"]
    rows = cfg.schedule_for(cfg.arm("market"))
    assert [r.creative_id for r in rows] == [2000001, 2000003, 2000004]
    assert all(r.start_tick == 0 and r.end_tick == 5 for r in rows)
    assert cfg.allocation is not None and cfg.allocation.enabled


def test_shared_market_allocation_is_config_hash_covered(tmp_path):
    """The allocation block must ride in raw, or a resume could silently
    change how budget moves while the hash still matches."""
    dir_a, dir_b = tmp_path / "a", tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    a = load_built(dir_a, build_run_config(
        parse_spec(shared_spec(allocation={"enabled": True, "power": 2.0})), REPO))
    b = load_built(dir_b, build_run_config(
        parse_spec(shared_spec(allocation={"enabled": True, "power": 3.0})), REPO))
    assert a.config_hash("market") != b.config_hash("market")


def test_absent_market_key_is_the_untouched_per_creative_path(tmp_path):
    plain = base_spec("ad_test", creatives=[
        {"creative_id": 2000001, "reach_prob": 0.4},
        {"creative_id": 2000003, "reach_prob": 0.4}])
    cfg = load_built(tmp_path, build_run_config(parse_spec(plain), REPO))
    assert [a.name for a in cfg.arms] == ["c2000001", "c2000003"]
    assert cfg.allocation is None


def test_shared_market_validation():
    with pytest.raises(ValueError, match="at least 2 creatives"):
        parse_spec(base_spec("ad_test",
                             creatives=[{"creative_id": 2000001, "reach_prob": 0.4}],
                             market={"shared": True}))
    with pytest.raises(ValueError, match="unknown keys"):
        parse_spec(shared_spec(allocaton={"enabled": True}))
    with pytest.raises(ValueError, match="allocation: unknown keys"):
        parse_spec(shared_spec(allocation={"enabled": True, "powr": 2.0}))
    with pytest.raises(ValueError, match="needs market.shared"):
        parse_spec(base_spec("ad_test", creatives=[
            {"creative_id": 2000001, "reach_prob": 0.4},
            {"creative_id": 2000003, "reach_prob": 0.4}],
            market={"allocation": {"enabled": True}}))
    with pytest.raises(ValueError, match="floor_share"):
        parse_spec(shared_spec(allocation={"enabled": True, "floor_share": 0.4}))


# -- pricing ---------------------------------------------------------------


def pricing_raw():
    return base_spec(
        "pricing",
        promo={"schedule": "fixtures/demo-brand/promo_schedule.json"},
        exposure={"schedule": [
            {"creative_id": 2000003, "start_tick": 0, "end_tick": 5,
             "reach_prob": 0.5}]})


def test_pricing_spec_zeroed_off_arm_first(tmp_path):
    spec = parse_spec(pricing_raw())
    raw = build_run_config(spec, REPO)
    cfg = load_built(tmp_path, raw)

    # declared order = execution order: shelf-aligning arm first
    assert [a.name for a in cfg.arms] == ["promo_off", "promo_on"]
    enabled, path, inline = cfg.promos_for(cfg.arm("promo_off"))
    assert enabled and path is None
    for p in inline["product_promos"]:
        assert all(c["discount_pct"] == 0.0 for c in p["cycles"])
    # same products, same windows as the real schedule
    real = json.loads((REPO / "fixtures/demo-brand/promo_schedule.json").read_text())
    assert [p["product_id"] for p in inline["product_promos"]] == \
        [p["product_id"] for p in real["product_promos"]]

    enabled, path, inline = cfg.promos_for(cfg.arm("promo_on"))
    assert enabled and inline["product_promos"] == real["product_promos"]


def test_zeroed_promos_preserves_windows():
    real = json.loads((REPO / "fixtures/demo-brand/promo_schedule.json").read_text())
    z = zeroed_promos(real["product_promos"])
    for zp, rp in zip(z["product_promos"], real["product_promos"]):
        for zc, rc in zip(zp["cycles"], rp["cycles"]):
            assert (zc["start_tick"], zc["end_tick"]) == (rc["start_tick"], rc["end_tick"])
            assert zc["discount_pct"] == 0.0


def test_pricing_spec_requires_funnel_and_one_source():
    bad = pricing_raw()
    bad["exposure"] = {"schedule": []}
    with pytest.raises(ValueError, match="exposure"):
        parse_spec(bad)
    bad = pricing_raw()
    bad["promo"] = {}
    with pytest.raises(ValueError, match="exactly one"):
        parse_spec(bad)


# -- page_ab ---------------------------------------------------------------


def test_page_ab_spec_single_split_row(tmp_path):
    spec = parse_spec(base_spec(
        "page_ab", creative_id=2000003, page_ids=[4000001, 4000002],
        reach_prob=0.35))
    raw = build_run_config(spec, REPO)
    cfg = load_built(tmp_path, raw)

    assert [a.name for a in cfg.arms] == ["ab"]
    row = cfg.schedule[0]
    assert row.creative_id == 2000003
    assert row.page_ids == (4000001, 4000002)
    assert cfg.page_splits() == {2000003: (4000001, 4000002)}


def test_page_ab_spec_rejects_bad_split_and_pages():
    with pytest.raises(ValueError, match="0.5"):
        parse_spec(base_spec("page_ab", creative_id=2000003,
                             page_ids=[4000001, 4000002], split=[0.7, 0.3]))
    with pytest.raises(ValueError, match="two distinct"):
        parse_spec(base_spec("page_ab", creative_id=2000003,
                             page_ids=[4000001]))


# -- scenario + packs -------------------------------------------------------


def test_scenario_spec_pack_arm_pair(tmp_path):
    spec = parse_spec(base_spec(
        "scenario", scenario_packs=["marathon-season"],
        exposure={"schedule": [
            {"creative_id": 2000001, "start_tick": 0, "end_tick": 5,
             "reach_prob": 0.3}]}))
    raw = build_run_config(spec, REPO)
    cfg = load_built(tmp_path, raw)
    assert [a.name for a in cfg.arms] == ["wave_on", "wave_off"]
    assert cfg.goal_overrides(cfg.arm("wave_on"))["waves_enabled"] is True
    assert cfg.goal_overrides(cfg.arm("wave_off"))["waves_enabled"] is False


def test_scenario_pack_overrides_merge_under_spec(tmp_path):
    spec_raw = base_spec(
        "scenario", scenario_packs=["marathon-season"],
        exposure={"schedule": []},
        goals={"overrides": {"wave_scale": 0.5}})
    raw = build_run_config(parse_spec(spec_raw), REPO)
    # spec-explicit overrides win over pack contents
    assert raw["goals"]["overrides"]["wave_scale"] == 0.5


def test_p1_pack_stubs_refuse_with_reason():
    for name, phrase in (("overpromise", "latent_quality"),
                         ("social-on-off", "P1")):
        with pytest.raises(ValueError, match=phrase):
            load_pack(REPO, name)
    with pytest.raises(ValueError, match="unknown scenario pack"):
        load_pack(REPO, "no-such-pack")


# -- calibration materialization -------------------------------------------


def test_calibration_materialized_fully_and_fixed_point():
    partial = {"appraisal": {"offer_norm": 0.25}}
    block = materialize_calibration(partial)
    # fully explicit: every param present
    assert block["appraisal"]["offer_norm"] == 0.25
    assert "w_pref" in block["appraisal"]
    assert "loss_aversion" in block["choice"]
    assert set(block["choice"]["stage_weights"]) == {"CLICK", "BROWSE", "CART", "BUY"}
    assert set(block["stage_bases"]) == {"CLICK", "BROWSE", "CART", "BUY"}
    # parsing the materialized block reproduces the same params (fixed point)
    assert parse_calibration(block) == parse_calibration(partial)
    assert materialize_calibration(block) == block


def test_every_builder_embeds_calibration_and_spec(tmp_path):
    specs = [
        parse_spec(base_spec("ad_test", creatives=[
            {"creative_id": 2000001, "reach_prob": 0.4}])),
        parse_spec(pricing_raw()),
        parse_spec(base_spec("page_ab", creative_id=2000003,
                             page_ids=[4000001, 4000002])),
        parse_spec(base_spec("scenario", scenario_packs=["marathon-season"])),
    ]
    for spec in specs:
        raw = build_run_config(spec, REPO)
        assert raw["experiment"]["type"] == spec.type
        assert raw["experiment"]["spec"] == spec.raw
        assert raw["calibration"] == materialize_calibration(spec.calibration)
        cfg = load_built(tmp_path, raw)  # RunConfig.load validates
        assert cfg.label == spec.name


# -- pricing discount ladder (v3.6-draft) -----------------------------------


def ladder_spec(levels, **extra):
    return base_spec(
        "pricing",
        promo={"product_promos": [
            {"product_id": 3000001,
             "cycles": [{"cycle": 1, "start_tick": 1, "end_tick": 2, "discount_pct": 0.15},
                        {"cycle": 2, "start_tick": 4, "end_tick": 5, "discount_pct": 0.2}]}]},
        exposure={"schedule": [{"creative_id": 2000003, "start_tick": 0,
                                "end_tick": 5, "reach_prob": 0.5}]},
        discount_levels=levels, **extra)


def test_ladder_builds_one_arm_per_level_ascending(tmp_path):
    spec = parse_spec(ladder_spec([0.3, 0.0, 0.1]))
    cfg = load_built(tmp_path, build_run_config(spec, REPO))

    assert [a.name for a in cfg.arms] == ["d0", "d10", "d30"]
    for arm, want in zip(cfg.arms, (0.0, 0.1, 0.3)):
        enabled, path, inline = cfg.promos_for(arm)
        pcts = {c["discount_pct"] for p in inline["product_promos"] for c in p["cycles"]}
        assert pcts == {want}, f"{arm.name} should force every cycle to {want}"
        # every arm still RUNS the hook — PRICED_AT is shared objective state
        assert enabled and path is None


def test_ladder_keeps_the_cycle_windows_intact(tmp_path):
    spec = parse_spec(ladder_spec([0.0, 0.25]))
    cfg = load_built(tmp_path, build_run_config(spec, REPO))
    _, _, inline = cfg.promos_for(cfg.arm("d25"))
    cycles = inline["product_promos"][0]["cycles"]
    assert [(c["start_tick"], c["end_tick"]) for c in cycles] == [(1, 2), (4, 5)]


def test_absent_discount_levels_is_the_untouched_two_arm_path(tmp_path):
    plain = base_spec(
        "pricing",
        promo={"product_promos": [
            {"product_id": 3000001,
             "cycles": [{"cycle": 1, "start_tick": 1, "end_tick": 2, "discount_pct": 0.15}]}]},
        exposure={"schedule": [{"creative_id": 2000003, "start_tick": 0,
                                "end_tick": 5, "reach_prob": 0.5}]})
    cfg = load_built(tmp_path, build_run_config(parse_spec(plain), REPO))
    assert [a.name for a in cfg.arms] == ["promo_off", "promo_on"]


def test_ladder_validation():
    with pytest.raises(ValueError, match="at least 2 levels"):
        parse_spec(ladder_spec([0.2]))
    with pytest.raises(ValueError, match="distinct"):
        parse_spec(ladder_spec([0.1, 0.1]))
    with pytest.raises(ValueError, match=r"\[0, 0.9\]"):
        parse_spec(ladder_spec([0.0, 0.95]))


def test_zeroed_promos_is_the_zero_rung_of_the_ladder():
    from shopsim.experiments.build import leveled_promos
    promos = [{"product_id": 3000001,
               "cycles": [{"cycle": 1, "start_tick": 1, "end_tick": 2, "discount_pct": 0.15}]}]
    assert zeroed_promos(promos) == leveled_promos(promos, 0.0)
