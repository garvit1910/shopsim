"""Phase 4 integration on the live store: the four PLAN.md checkpoints at
mini scale — all three experiment types through the CLI/orchestrator, the
violation-arm bounce delta, the promo reference-price drift, and the
objective-truthfulness reconstructions (PRICED_AT + NEEDS).

Scratch blocks 92+ via a pre-seeded registry in a fake repo root (a tmp dir
carrying fixtures/ + engine/ marker dirs, so find_repo_root anchors there —
this also covers the CLI subprocess, which a monkeypatch would not reach).
T0 windows 1_758… / 1_759… keep as-of price reads clear of the fixture runs
(1_755…) and the Phase-3 real tests (1_756…).
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from shopsim.contracts.ids import shopper_id as make_sid, shopper_offset
from shopsim.hydramem import cypher, schema
from shopsim.hydramem.real import HydraMem
from shopsim.population.factory import (
    PopulationConfig,
    generate_population,
    load_segment_specs,
)
from shopsim.experiments.orchestrate import run_experiment
from shopsim.runner.config import RunConfig
from shopsim.runner.rollback import load_records
from shopsim.runner.runstore import RunStore
from shopsim.runner.steps import GoalConfig, GoalState, PromoSchedule, goal_step

pytestmark = pytest.mark.real

REPO = Path(__file__).resolve().parents[3]
ENGINE = REPO / "engine"
T0, DAY = 1_758_000_000, 86_400
T0_PRICING = 1_759_000_000  # own as-of window: PRICED_AT is global state
BLOCK_BASE = 92
N = 12
WAVE_N = 48  # the wave test's larger draw (see test_needs_wave_reconstruction)

_CONCEPTS = list(range(5000, 5030))
_CATEGORIES = list(range(5500, 5510))
_STIMULI = [2000001, 2000002, 2000003, 2000004, 2000005, 4000001, 4000002]
_PRODUCTS = [3000001, 3000002, 3000003, 3000004, 3000005, 3000006, 3000007]
_BRANDS = [6001, 6002, 6003]

# 4.4 in action: a test-tuned calibration block that densifies the funnel at
# mini scale (population CTR ~50% instead of the researched 0.5-2%), so the
# violation/promo exhibits are measurable with 12 shoppers. It rides in the
# generated run_config -> config_hash pins it (Law 13).
DENSE_FUNNEL = {"stage_bases": {"CLICK": 2.0}}


def wipe_block(client, run_index: int, n: int) -> None:
    for off in range(n):
        sid = make_sid(run_index, off)
        for rel, dsts in (
            ("SAW", _STIMULI), ("CLICKED", _STIMULI),
            ("VISITED", _STIMULI), ("BROWSED", _STIMULI), ("BOUNCED", _STIMULI),
            ("CARTED", _PRODUCTS), ("ABANDONED", _PRODUCTS), ("BOUGHT", _PRODUCTS),
            ("PRICE_SEEN", _PRODUCTS), ("EXPERIENCED", _PRODUCTS),
            ("PREFERS", _CONCEPTS), ("EXPECTS", _CONCEPTS),
            ("REFERENCE_PRICE", _PRODUCTS), ("NEEDS", _CATEGORIES),
            ("HABIT", _BRANDS),
        ):
            client.run_stmt(cypher.delete_edges_batch(rel, [(sid, d) for d in dsts]))
        for row in client.run_stmt(cypher.holds_history(sid)):
            bid = row["dst"]
            for d in client.run_stmt(cypher.all_edges("DERIVED_FROM", bid)):
                client.run_stmt(cypher.delete_edge("DERIVED_FROM", bid, d["dst"]))
            client.run_stmt(cypher.delete_edge("ABOUT", bid, row["about_id"]))
            client.run_stmt(cypher.delete_edge("THAT", bid, row["that_id"]))
            client.run_stmt(cypher.delete_edge("HOLDS", sid, bid))


@pytest.fixture(scope="module", autouse=True)
def clean_blocks():
    mem = HydraMem()
    for idx in range(BLOCK_BASE, BLOCK_BASE + 14):
        wipe_block(mem.client, idx, WAVE_N)
    # close any live PRICED_AT before both windows: prepare()'s catalog MERGE
    # and the self-healing promo hook rebuild from list price
    for t in (T0 - 1, T0_PRICING - 1):
        mem.client.run_stmt(cypher.supersede_edge(
            "PRICED_AT", 3000001, schema.PRICEBOOK_ID, t))
    mem.close()
    yield


@pytest.fixture(scope="module")
def root(tmp_path_factory):
    """Fake repo root: fixtures/ + engine/ markers anchor find_repo_root, and
    the pre-seeded registry starts every allocation at BLOCK_BASE — including
    the CLI subprocess."""
    fake = tmp_path_factory.mktemp("exp-real")
    (fake / "fixtures").mkdir()
    (fake / "engine").mkdir()
    (fake / "runs").mkdir()
    (fake / "runs" / "registry.json").write_text(
        json.dumps({"next_run_index": BLOCK_BASE, "runs": []}))
    (fake / "specs").mkdir()
    return fake


def base_spec(stype, name, *, seed=57, ticks=6, t0=T0, size=N, **extra):
    return {
        "type": stype, "name": name, "seed": seed, "ticks": ticks, "t0": t0,
        "population": {"size": size,
                       "personas": str(REPO / "fixtures/demo-brand/personas.json")},
        "catalog": str(REPO / "fixtures/demo-brand"),
        "perception_cache": str(REPO / "fixtures/perception-cache"),
        "goal_config": str(REPO / "fixtures/demo-brand/goal_config.json"),
        **extra,
    }


def run_spec(root, spec: dict) -> Path:
    p = root / "specs" / f"{spec['name']}.json"
    p.write_text(json.dumps(spec))
    return run_experiment(p, quiet=True)


def arm_results(root, label: str) -> dict[str, dict]:
    cfg = RunConfig.load(root / "runs" / "experiments" / label / "run_config.json")
    store = RunStore(cfg.root)
    return {a.name: json.loads(
        (Path(store.latest_for(label, a.name)["dir"]) / "results.json").read_text())
        for a in cfg.arms}


def segments_of(seed: int, size: int) -> dict[int, int]:
    specs = load_segment_specs(REPO / "fixtures/demo-brand/personas.json")
    shoppers = generate_population(PopulationConfig(
        seed=seed, population_size=size, segments=specs))
    return {shopper_offset(s.shopper_id): s.segment_id for s in shoppers}


# -- 4.1: ad experiment (paired arms + audience containment) ----------------


def test_ad_experiment_mini(root):
    seg = segments_of(57, N)
    target_segment = seg[0]  # deterministic: offset 0's segment
    spec = base_spec(
        "ad_test", "ads-mini", calibration=DENSE_FUNNEL,
        creatives=[
            {"creative_id": 2000001, "reach_prob": 1.0},
            {"creative_id": 2000003, "reach_prob": 1.0,
             "audience_segments": [target_segment]},
        ])
    exp_dir = run_spec(root, spec)
    results = arm_results(root, "ads-mini")

    # both creative arms produced per-creative funnels
    for arm, cid in (("c2000001", "2000001"), ("c2000003", "2000003")):
        row = results[arm]["funnel_by_creative"][cid]
        assert row["SAW"] > 0

    # audience containment: every SAW of the targeted arm belongs to shoppers
    # of the target segment (exposure filter, CONTRACT v3.4-draft)
    cfg = RunConfig.load(root / "runs" / "experiments" / "ads-mini" / "run_config.json")
    store = RunStore(cfg.root)
    targeted_dir = Path(store.latest_for("ads-mini", "c2000003")["dir"])
    saw_offsets = {shopper_offset(r["shopper_id"])
                   for r in load_records(targeted_dir / "events.jsonl")
                   if r["type"] == "SAW"}
    assert saw_offsets and all(seg[o] == target_segment for o in saw_offsets)

    # paired design: both arms drew identical populations (same seed), and the
    # open arm reached everyone at reach 1.0
    open_dir = Path(store.latest_for("ads-mini", "c2000001")["dir"])
    open_saw = {shopper_offset(r["shopper_id"])
                for r in load_records(open_dir / "events.jsonl")
                if r["type"] == "SAW"}
    assert open_saw == set(range(N))

    comparison = json.loads((exp_dir / "comparison.json").read_text())
    assert [r["creative"] for r in comparison["ad_test"]["creatives"]] == \
        [2000001, 2000003]


# -- 4.3: page A/B — the violation arm bounces more (checkpoint 2) ----------


def test_page_ab_violation_bounce(root):
    spec = base_spec(
        "page_ab", "pageab-mini", ticks=8, size=2 * N,
        calibration=DENSE_FUNNEL,
        creative_id=2000003, page_ids=[4000001, 4000002], reach_prob=1.0)
    exp_dir = run_spec(root, spec)
    results = arm_results(root, "pageab-mini")["ab"]

    by_page = results["funnel_by_page"]
    consistent, violating = by_page["4000001"], by_page["4000002"]
    # the seeded 50/50 split put shoppers on both variants
    assert consistent["VISITED"] + consistent["BOUNCED"] > 0
    assert violating["VISITED"] + violating["BOUNCED"] > 0
    # checkpoint 2: the violating page (hides the DISCOUNT concept 2000003
    # claims) bounces measurably more than the consistent page
    assert violating["bounce_rate"] > consistent["bounce_rate"]

    comparison = json.loads((exp_dir / "comparison.json").read_text())
    assert comparison["page_ab"]["bounce_delta"] > 0

    # violation motif was live in the decisions
    assert results["violations"]["count"] > 0


# -- 4.2: pricing — ref-price drift + PRICED_AT truth (checkpoints 3, 4a) ---


def test_pricing_promo_mini(root):
    spec = base_spec(
        "pricing", "promo-mini", ticks=15, t0=T0_PRICING,
        calibration=DENSE_FUNNEL,
        promo={"schedule": str(REPO / "fixtures/demo-brand/promo_schedule.json")},
        exposure={"schedule": [{"creative_id": 2000003, "start_tick": 0,
                                "end_tick": 14, "reach_prob": 1.0}]})
    run_spec(root, spec)
    results = arm_results(root, "promo-mini")

    # the off arm's shelf stayed at list price every tick
    off_traj = results["promo_off"]["reference_price_trajectory"]
    assert [r["current_price"] for r in off_traj] == [39.0] * 15

    # the on arm's shelf carries all three cycles (15/15/20% off 39.0)
    on_traj = results["promo_on"]["reference_price_trajectory"]
    price_at = {r["tick"]: r["current_price"] for r in on_traj}
    promo = PromoSchedule.load(REPO / "fixtures/demo-brand/promo_schedule.json")
    for tick in range(15):
        expected = round(39.0 * (1.0 - promo.discount_at(3000001, tick)), 2)
        assert price_at[tick] == expected, f"tick {tick}"

    # checkpoint 3: downward reference-price drift across the cycles
    means = [r["mean_reference_price"] for r in on_traj
             if r["mean_reference_price"] is not None]
    assert len(means) >= 5
    assert means[-1] < means[0]
    assert means[-1] < 39.0

    # checkpoint 4a: PRICED_AT history reconstructs the schedule EXACTLY —
    # as-of reads at every tick timestamp reproduce the configured price
    mem = HydraMem()
    rows = mem.client.run_stmt(cypher.edge_history(
        "PRICED_AT", 3000001, schema.PRICEBOOK_ID, ("price", "t", "valid_to")))
    mem.close()
    for tick in range(15):
        now = T0_PRICING + tick * DAY
        live = [r for r in rows if r["t"] <= now < r["valid_to"]]
        current = max(live, key=lambda r: r["t"])["price"]
        expected = round(39.0 * (1.0 - promo.discount_at(3000001, tick)), 2)
        assert current == expected, f"tick {tick}: {current} != {expected}"


# -- 4.5: need-wave scenario — NEEDS truth (checkpoint 4b) ------------------


def test_needs_wave_reconstruction(root):
    # 48 shoppers: enough draws for the x4 window multiplier to be visible
    # above the base arrival rate (goal-step cost only — exposure stays thin)
    spec = base_spec(
        "scenario", "wave-mini", ticks=10, seed=91, size=WAVE_N,
        scenario_packs=["marathon-season"],
        exposure={"schedule": [{"creative_id": 2000001, "start_tick": 0,
                                "end_tick": 9, "reach_prob": 0.2}]})
    run_spec(root, spec)
    cfg = RunConfig.load(root / "runs" / "experiments" / "wave-mini" / "run_config.json")
    store = RunStore(cfg.root)

    def logged_needs(arm):
        d = Path(store.latest_for("wave-mini", arm)["dir"])
        return {(shopper_offset(r["shopper_id"]), r["subject"], r["t"],
                 r["strength"], r["source"])
                for r in load_records(d / "events.jsonl")
                if r["type"] == "NEED_ACTIVATED"}

    # offline recomputation of the configured wave: the pure goal_step
    # sequence with the same seed MUST reproduce the run's arrivals exactly
    goal_cfg = GoalConfig.load(REPO / "fixtures/demo-brand/goal_config.json")
    seg = segments_of(91, WAVE_N)

    def recompute(overrides):
        state, out = GoalState(), set()
        for tick in range(10):
            events, _ = goal_step(
                seed=91, tick=tick, now=T0 + tick * DAY, t0=T0,
                tick_seconds=DAY, run=0, goal_cfg=goal_cfg,
                overrides=overrides, state=state, segment_by_offset=seg,
                sid_of=lambda o: make_sid(0, o))
            out |= {(shopper_offset(e.shopper_id), e.subject, e.t,
                     e.prop("strength"), e.prop("source"))
                    for e in events if e.type.value == "NEED_ACTIVATED"}
        return out

    on_logged, off_logged = logged_needs("wave_on"), logged_needs("wave_off")
    assert on_logged == recompute({"scripted_enabled": True, "waves_enabled": True})
    assert off_logged == recompute({"scripted_enabled": True, "waves_enabled": False})

    # the wave is visible: extra 5504 arrivals ONLY inside ticks 6-9
    window = range(T0 + 6 * DAY, T0 + 10 * DAY)
    on_in = {e for e in on_logged if e[1] == 5504 and e[2] in window}
    off_in = {e for e in off_logged if e[1] == 5504 and e[2] in window}
    assert len(on_in) > len(off_in)
    assert {e for e in on_logged if e[2] not in window} == \
        {e for e in off_logged if e[2] not in window}

    # checkpoint 4b: the GRAPH's NEEDS history carries the same set — the
    # objective layer stays truthful to the configured wave
    for arm, expected in (("wave_on", on_logged), ("wave_off", off_logged)):
        run_index = store.latest_for("wave-mini", arm)["run_index"]
        mem = HydraMem(run_index=run_index)
        got = set()
        for off in range(WAVE_N):
            sid = make_sid(run_index, off)
            for cat in _CATEGORIES:
                for r in mem.client.run_stmt(cypher.all_edges(
                        "NEEDS", sid, ("strength", "t", "source"))):
                    got.add((off, r["dst"], r["t"], r["strength"], r["source"]))
        mem.close()
        assert got == expected, arm


# -- checkpoint 1: the CLI runs all three experiment types ------------------


def test_experiments_cli_end_to_end(root):
    """The 'mini-driver' checkpoint, amended: the experiments CLI against the
    real store. The three type-specific tests above already ran ad/pricing/
    page_ab through the orchestrator; this proves the subprocess surface."""
    spec = base_spec("ad_test", "cli-mini", ticks=3, size=6,
                     mind={"decide": "scripted", "consolidate": "formula"},
                     creatives=[{"creative_id": 2000003, "reach_prob": 1.0}])
    spec_path = root / "specs" / "cli-mini.json"
    spec_path.write_text(json.dumps(spec))

    proc = subprocess.run(
        [sys.executable, "-m", "shopsim.experiments", "run",
         "--spec", str(spec_path)],
        cwd=str(ENGINE), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    exp_dir = root / "runs" / "experiments" / "cli-mini"
    assert (exp_dir / "comparison.json").exists()

    proc = subprocess.run(
        [sys.executable, "-m", "shopsim.experiments", "compare",
         "--dir", str(exp_dir)],
        cwd=str(ENGINE), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    comparison = json.loads((exp_dir / "comparison.json").read_text())
    assert comparison["experiment"]["type"] == "ad_test"
    assert comparison["ad_test"]["creatives"][0]["SAW"] > 0


# -- orchestrated branch arms ----------------------------------------------


def test_experiment_branch_arm(root):
    spec = base_spec(
        "scenario", "branch-mini", ticks=8, seed=77,
        scenario_packs=["marathon-season"],
        exposure={"schedule": [{"creative_id": 2000001, "start_tick": 0,
                                "end_tick": 7, "reach_prob": 0.5}]},
        mind={"decide": "scripted", "consolidate": "formula"},
        arms=[{"name": "wave_on"},
              {"name": "wave_off", "goal_overrides": {"waves_enabled": False},
               "branch_from": "wave_on", "divergence_tick": 5}])
    run_spec(root, spec)
    results = arm_results(root, "branch-mini")
    assert results["wave_off"]["goal_stats"]["decisions_from_tick"] == 5

    cfg = RunConfig.load(root / "runs" / "experiments" / "branch-mini" / "run_config.json")
    store = RunStore(cfg.root)

    def prefix(arm):
        d = Path(store.latest_for("branch-mini", arm)["dir"])
        rows = [r for r in load_records(d / "events.jsonl")
                if (r["t"] - T0) // DAY < 5 and r["type"] != "TICK_COMPLETE"]
        return [json.dumps({**{k: v for k, v in r.items() if k != "run"},
                            "shopper_id": r.get("shopper_id", 0) % 100_000},
                           sort_keys=True) for r in rows]

    assert prefix("wave_on") == prefix("wave_off")
