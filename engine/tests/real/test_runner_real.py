"""Phase 3 integration on the live store: mini-run lifecycle, determinism,
branch, and crash->resume (the five Phase-3 checkpoint mechanisms at small
scale). Uses scratch run blocks 80+ , wiped before each session so repeated
pytest runs stay deterministic.
"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from shopsim.contracts.ids import shopper_id as make_sid
from shopsim.hydramem import cypher, schema
from shopsim.hydramem.real import HydraMem
from shopsim.runner import runstore
from shopsim.runner.config import RunConfig
from shopsim.runner.loop import SimRunner
from shopsim.runner.replay import branch
from shopsim.runner.results import validate_results
from shopsim.runner.rollback import load_records
from shopsim.runner.runstore import RunStore

pytestmark = pytest.mark.real

REPO = Path(__file__).resolve().parents[3]
ENGINE = REPO / "engine"
T0, DAY = 1_756_000_000, 86_400  # clear of the story graph and repo runs
BLOCK_BASE = 80
N = 6

_CONCEPTS = list(range(5000, 5030))
_CATEGORIES = list(range(5500, 5510))
_STIMULI = [2000001, 2000002, 2000003, 2000004, 2000005, 4000001, 4000002]
_PRODUCTS = [3000001, 3000002, 3000003, 3000004, 3000005, 3000006, 3000007]
_BRANDS = [6001, 6002, 6003]


def wipe_block(client, run_index: int, n: int) -> None:
    """Delete every edge a mini-run could have written for offsets [0, n)."""
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
    for idx in range(BLOCK_BASE, BLOCK_BASE + 12):
        wipe_block(mem.client, idx, N)
    # reset the hero product's price history to list price at our t0
    mem.client.run_stmt(cypher.supersede_edge("PRICED_AT", 3000001,
                                              schema.PRICEBOOK_ID, T0 - 1))
    mem.close()
    yield


@pytest.fixture(scope="module")
def root(tmp_path_factory):
    # ONE registry for the whole module: blocks allocate sequentially from
    # BLOCK_BASE and never collide across the tests in this session
    tmp_path = tmp_path_factory.mktemp("mini-run")
    mp = pytest.MonkeyPatch()
    mp.setattr(runstore, "FIRST_RUN_INDEX", BLOCK_BASE)
    goal_cfg = {
        "segments": [{"segment_id": 1001, "name": "eco_enthusiast"}],
        "arrival_rates_per_tick": {"1001": {"5504": 0.02}},
        "need_defaults": {
            "strength_range": [0.5, 0.9], "deadline_ticks_range": [4, 8],
            "budget_cap_by_category": {str(c): 90.0 for c in _CATEGORIES}},
        "waves": [],
        "scripted": [{"name": "mini_maya", "shopper_id": 1000002,
                      "category_id": 5504, "activate_tick": 1, "strength": 0.8,
                      "budget_cap": 90.0, "deadline_tick": 4}],
    }
    (tmp_path / "goal_config.json").write_text(json.dumps(goal_cfg))
    cfg = {
        "label": "mini", "seed": 57,
        "mind": {"decide": "scripted", "consolidate": "formula"},
        "ticks": 5, "t0": T0, "tick_seconds": DAY,
        "population": {"size": N,
                       "personas": str(REPO / "fixtures/demo-brand/personas.json")},
        "catalog_dir": str(REPO / "fixtures/demo-brand"),
        "perception_cache": str(REPO / "fixtures/perception-cache"),
        "exposure": {"frequency_cap_per_tick": 1, "frequency_cap_72h": 6,
                     "schedule": [{"creative_id": 2000003, "start_tick": 0,
                                   "end_tick": 4, "reach_prob": 1.0}]},
        "goals": {"config": str(tmp_path / "goal_config.json")},
        "fulfillment": {"lag_ticks": 2, "sat_noise_sd": 0.08},
        "promos": {"schedule": str(REPO / "fixtures/demo-brand/promo_schedule.json"),
                   "enabled": True},
        "arms": [{"name": "main"},
                 {"name": "off",
                  "goal_overrides": {"scripted_enabled": False},
                  "branch_from": "main", "divergence_tick": 3}],
    }
    (tmp_path / "run_config.json").write_text(json.dumps(cfg))
    yield tmp_path
    mp.undo()


def run_arm(root_dir, arm="main"):
    cfg = RunConfig.load(root_dir / "run_config.json")
    store = RunStore(cfg.root)
    run_index, run_dir = store.allocate(cfg, arm)
    runner = SimRunner(cfg, arm, run_index, run_dir, quiet=True)
    runner.prepare(seed_graph=True)
    results = runner.run()
    runner.close()
    return run_dir, results, run_index


def norm_log_hash(path):
    out = []
    for rec in load_records(path):
        rec = dict(rec)
        if "shopper_id" in rec:
            rec["shopper_id"] %= 100_000
        rec.pop("run", None)
        out.append(json.dumps(rec, sort_keys=True))
    return hashlib.sha256("\n".join(out).encode()).hexdigest()


def norm_results_hash(path):
    r = json.loads(Path(path).read_text())
    r["run_manifest"].pop("run_index")
    return hashlib.sha256(json.dumps(r, sort_keys=True).encode()).hexdigest()


def test_mini_run_lifecycle_and_determinism(root):
    run_dir, results, run_index = run_arm(root)
    assert validate_results(results) == []

    records = load_records(run_dir / "events.jsonl")
    types = {r["type"] for r in records}
    assert {"SAW", "CLICKED", "VISITED", "PRICE_SEEN", "BROWSED",
            "NEED_ACTIVATED", "TICK_COMPLETE"} <= types

    # the scripted mini-Maya (offset 2): need at tick 1 -> BUY -> satisfied
    sid = make_sid(run_index, 2)
    mine = [(r["type"], (r["t"] - T0) // DAY) for r in records
            if r.get("shopper_id") == sid]
    assert ("NEED_ACTIVATED", 1) in mine
    buy_tick = next(tk for typ, tk in mine if typ == "BOUGHT")
    assert ("NEED_SATISFIED", buy_tick) in mine
    assert ("EXPERIENCED", buy_tick + 2) in mine  # fulfillment across the lag

    # satisfied-with-cause on the live graph
    mem = HydraMem(run_index=run_index)
    hist = mem.client.run_stmt(cypher.edge_history(
        "NEEDS", sid, 5504, ("closed_cause_kind", "closed_cause_id", "valid_to")))
    mem.close()
    assert any(h["closed_cause_kind"] == "BOUGHT" and h["closed_cause_id"] == 3000001
               for h in hist)

    # drift populated with sane values (the rising-series exhibit needs the
    # 200-shopper fixture run where prior-holding segments exist; a 6-shopper
    # draw may contain only cold-start learners, whose first learned value IS
    # the evidence.py blend-from-zero target)
    drift = [d for d in results["preference_drift"] if d["concept"] == 5003]
    series = [[v for v in d["series"] if v is not None] for d in drift]
    assert drift and all(len(s) >= 2 and all(0.0 < v <= 1.0 for v in s)
                         for s in series)

    # same config, fresh block => identical normalized trajectory
    run_dir2, results2, _ = run_arm(root)
    assert norm_log_hash(run_dir / "events.jsonl") == norm_log_hash(run_dir2 / "events.jsonl")
    assert norm_results_hash(run_dir / "results.json") == norm_results_hash(run_dir2 / "results.json")


def test_branch_replays_prefix_and_diverges(root):
    run_dir, _, _ = run_arm(root)
    cfg = RunConfig.load(root / "run_config.json")
    store = RunStore(cfg.root)
    results_off = branch(cfg, "off", store, quiet=True)
    assert validate_results(results_off) == []
    assert results_off["goal_stats"]["decisions_from_tick"] == 3

    off_dir = Path(store.latest_for("mini", "off")["dir"])
    src = [r for r in load_records(run_dir / "events.jsonl")
           if (r["t"] - T0) // DAY < 3 and r["type"] != "TICK_COMPLETE"]
    rep = [r for r in load_records(off_dir / "events.jsonl")
           if (r["t"] - T0) // DAY < 3 and r["type"] != "TICK_COMPLETE"]

    def norm(rows):
        return [json.dumps({**{k: v for k, v in r.items() if k != "run"},
                            "shopper_id": r.get("shopper_id", 0) % 100_000},
                           sort_keys=True) for r in rows]

    assert norm(src) == norm(rep)


def test_crash_resume_matches_clean_run(root):
    clean_dir, _, _ = run_arm(root)

    env_cwd = str(ENGINE)
    cfg_path = str(root / "run_config.json")
    proc = subprocess.run(
        [sys.executable, "-m", "shopsim.runner", "run", "--config", cfg_path,
         "--quiet", "--crash-after", "consolidation:2"],
        cwd=env_cwd, capture_output=True, text=True)
    assert proc.returncode == 137, proc.stderr

    store = RunStore(root)
    crashed = store.rows()[-1]
    records = load_records(Path(crashed["dir"]) / "events.jsonl")
    assert max((r["tick"] for r in records if r["type"] == "TICK_COMPLETE"),
               default=-1) == 1  # tick 2 has no marker

    proc = subprocess.run(
        [sys.executable, "-m", "shopsim.runner", "resume", "--config", cfg_path,
         "--run", crashed["run_id"], "--quiet"],
        cwd=env_cwd, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr

    assert norm_log_hash(clean_dir / "events.jsonl") == \
        norm_log_hash(Path(crashed["dir"]) / "events.jsonl")
    assert norm_results_hash(clean_dir / "results.json") == \
        norm_results_hash(Path(crashed["dir"]) / "results.json")
