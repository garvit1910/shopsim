"""The social layer on the live stack (P1, CONTRACT v3.8-draft).

One small run with `population.social` on, asserting the whole chain: seeded
TRUSTS_PERSON edges on the graph -> social_proof motifs in retrieval -> the
credibility channel active -> `social_lift` in the MetricsReport labelled
causal. The OFF half of the ablation is tests/real/test_golden_run_real.py,
which re-runs a social-free config and demands the pre-social fixture back.

Scratch block 104+; the shared fake-root pattern keeps runs out of the repo.
"""

import json
from pathlib import Path

import pytest

from shopsim.contracts.ids import shopper_id as make_sid
from shopsim.hydramem import cypher
from shopsim.hydramem.real import HydraMem
from shopsim.population.factory import social_graph
from shopsim.runner.config import RunConfig
from shopsim.runner.loop import SimRunner
from shopsim.runner.results import validate_results
from shopsim.runner.runstore import RunStore

pytestmark = pytest.mark.real

REPO = Path(__file__).resolve().parents[3]
GOLDEN = REPO / "fixtures" / "golden-run"
BLOCK_BASE = 104
N = 16
DEGREE = 4

from test_golden_run_real import wipe_block  # noqa: E402  (same-dir helper)


@pytest.fixture(scope="module")
def social_run(tmp_path_factory):
    root = tmp_path_factory.mktemp("social-root")
    (root / "engine").mkdir()
    fixtures = root / "fixtures"
    fixtures.mkdir()
    for name in ("demo-brand", "perception-cache"):
        (fixtures / name).symlink_to(REPO / "fixtures" / name)
    dst = fixtures / "golden-run"
    dst.mkdir()
    (dst / "goal_config.json").write_bytes((GOLDEN / "goal_config.json").read_bytes())

    cfg_raw = json.loads((GOLDEN / "run_config.json").read_text())
    cfg_raw["label"] = "social-real"
    cfg_raw["ticks"] = 4
    cfg_raw["population"] = {
        "size": N, "personas": "fixtures/demo-brand/personas.json",
        "social": {"enabled": True, "degree": DEGREE},
    }
    # the channel has to be switched ON to be causal — that is the whole point
    # of w_social defaulting to 0.0 (registry row 20)
    cfg_raw["calibration"] = {"appraisal": {"w_social": 0.5}}
    cfg_raw["exposure"]["schedule"] = [
        {"creative_id": 2000003, "start_tick": 0, "end_tick": 3, "reach_prob": 1.0},
    ]
    (dst / "run_config.json").write_text(json.dumps(cfg_raw))
    (root / "runs").mkdir()
    (root / "runs" / "registry.json").write_text(
        json.dumps({"next_run_index": BLOCK_BASE, "runs": []}))

    mem = HydraMem()
    for idx in range(BLOCK_BASE, BLOCK_BASE + 3):
        wipe_block(mem.client, idx, N)
    mem.close()

    cfg = RunConfig.load(dst / "run_config.json")
    store = RunStore(cfg.root)
    run_index, run_dir = store.allocate(cfg, "golden")
    runner = SimRunner(cfg, "golden", run_index, run_dir, quiet=True)
    try:
        runner.prepare(seed_graph=True)
        results = runner.run()
    finally:
        runner.close()
    return cfg, run_index, results


def test_trusts_person_matches_the_seeded_graph(social_run):
    """The graph on disk is the graph the pure factory drew — both directions,
    because retrieval only reads outgoing edges."""
    cfg, run_index, _results = social_run
    expected = social_graph(N, cfg.seed, cfg.social)
    assert len(expected) == N * DEGREE // 2

    mem = HydraMem(run_index=run_index)
    try:
        live = set()
        for off in range(N):
            sid = make_sid(run_index, off)
            for r in mem.client.run_stmt(cypher.all_edges("TRUSTS_PERSON", sid, ("w",))):
                live.add((off, r["dst"] % 100_000, round(r["w"], 4)))
    finally:
        mem.close()
    both_ways = {(a, b, w) for a, b, w in expected} | {(b, a, w) for a, b, w in expected}
    assert live == both_ways


def test_social_proof_reaches_decisions_and_the_report(social_run):
    _cfg, _run_index, results = social_run
    assert validate_results(results) == []
    assert "social_proof" in results["motif_stats"], \
        "no peer purchase was ever retrieved — the exhibit did not run"

    lift = results["social_lift"]
    assert lift is not None and lift["causal"] is True and lift["w_social"] == 0.5
    assert lift["decisions_on"] > 0
    assert lift["decisions_on"] + lift["decisions_off"] > 0
    assert "registry row 20" in lift["note"]


def test_manifest_records_the_social_config(social_run):
    """C3's optional social_config_hash: present exactly when a social layer
    exists, so every social-free manifest stays byte-identical."""
    _cfg, _run_index, results = social_run
    assert results["run_manifest"].get("social_config_hash")
