"""Phase 6.2 on the live stack: re-run the committed golden and demand the
same MetricsReport back.

The DB-free twin (tests/test_golden_run.py) checks the committed artifacts;
this one checks that they are still what the engine produces. It runs in a
fake repo root (a tmp dir carrying an `engine` marker plus a `fixtures` dir
whose heavy subdirectories are symlinks) so find_repo_root anchors there and
the run lands in tmp — while the run_config's RELATIVE paths keep its
config_hash byte-identical to the committed manifest. Scratch block 100+.
"""

import hashlib
import json
from pathlib import Path

import pytest

from shopsim.contracts.ids import shopper_id as make_sid, shopper_offset
from shopsim.hydramem import cypher
from shopsim.hydramem.real import HydraMem
from shopsim.population.factory import (
    PopulationConfig, generate_population, load_segment_specs)
from shopsim.runner.config import RunConfig
from shopsim.runner.loop import SimRunner
from shopsim.runner.results import validate_results
from shopsim.runner.runstore import RunStore

pytestmark = pytest.mark.real

REPO = Path(__file__).resolve().parents[3]
GOLDEN = REPO / "fixtures" / "golden-run"
BLOCK_BASE = 100
N = 5

_CONCEPTS = list(range(5000, 5030))
_CATEGORIES = list(range(5500, 5510))
_STIMULI = [2000001, 2000002, 2000003, 2000004, 2000005, 4000001, 4000002]
_PRODUCTS = [3000001, 3000002, 3000003, 3000004, 3000005, 3000006, 3000007]
_BRANDS = [6001, 6002, 6003]


def wipe_block(client, run_index: int, n: int) -> None:
    """Every edge a golden run could have written for offsets [0, n) — so a
    repeated pytest session starts from the same empty block it did the first
    time. (Same helper shape as test_runner_real; duplicated rather than
    imported because tests/real is not a package.)"""
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
        for peer in range(n):
            client.run_stmt(cypher.delete_edge(
                "TRUSTS_PERSON", sid, make_sid(run_index, peer)))


@pytest.fixture(scope="module")
def fake_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("golden-root")
    (root / "engine").mkdir()                     # find_repo_root marker
    fixtures = root / "fixtures"
    fixtures.mkdir()
    for name in ("demo-brand", "perception-cache"):
        (fixtures / name).symlink_to(REPO / "fixtures" / name)
    dst = fixtures / "golden-run"
    dst.mkdir()                                   # a REAL dir: resolve() stays here
    for name in ("run_config.json", "goal_config.json"):
        (dst / name).write_bytes((GOLDEN / name).read_bytes())
    (root / "runs").mkdir()
    (root / "runs" / "registry.json").write_text(
        json.dumps({"next_run_index": BLOCK_BASE, "runs": []}))

    mem = HydraMem()
    for idx in range(BLOCK_BASE, BLOCK_BASE + 4):
        wipe_block(mem.client, idx, N)
    mem.close()
    return root


@pytest.fixture(scope="module")
def rerun(fake_root):
    cfg = RunConfig.load(fake_root / "fixtures" / "golden-run" / "run_config.json")
    assert cfg.root == fake_root, "the fake repo root did not anchor the run store"
    store = RunStore(cfg.root)
    run_index, run_dir = store.allocate(cfg, "golden")
    runner = SimRunner(cfg, "golden", run_index, run_dir, quiet=True)
    try:
        runner.prepare(seed_graph=True)
        results = runner.run()
    finally:
        runner.close()
    return run_dir, run_index, results


def norm(results: dict) -> str:
    """The run block is the one thing that legitimately differs between
    reproductions (Appendix A: shopper and belief ids are block-offset)."""
    r = json.loads(json.dumps(results))
    r["run_manifest"].pop("run_index", None)
    return hashlib.sha256(json.dumps(r, sort_keys=True).encode()).hexdigest()


def test_rerun_reproduces_the_committed_report(rerun):
    _run_dir, _idx, results = rerun
    committed = json.loads((GOLDEN / "results.json").read_text())
    assert validate_results(results) == []
    if norm(results) != norm(committed):  # name the first divergent key
        diffs = [k for k in committed if k != "run_manifest"
                 and committed[k] != results.get(k)]
        pytest.fail(f"golden drift in {diffs}: rerun the fixture only if the "
                    f"change is intended (fixtures/golden-run/README.md)")


def test_manifest_hashes_are_unchanged(rerun):
    """Relative paths in the config mean the fake root cannot move a hash:
    same evidence.py, same perception cache, same goal config, same catalog."""
    _run_dir, _idx, results = rerun
    committed = json.loads((GOLDEN / "results.json").read_text())["run_manifest"]
    live = results["run_manifest"]
    for key in ("config_hash", "evidence_hash", "perception_cache_hash",
                "goal_config_hash", "latent_quality_hash", "view_hash"):
        assert live[key] == committed[key], key


def test_post_hoc_report_matches_the_run_that_produced_it(rerun, fake_root):
    """`python -m shopsim.analytics report` recomputes from the snapshot plus a
    graph sweep: the checkpoint "one command from run directory -> full
    report" has to land on the same numbers the run wrote."""
    from shopsim.analytics.report import report_for_run

    run_dir, run_index, results = rerun
    cfg = RunConfig.load(fake_root / "fixtures" / "golden-run" / "run_config.json")
    _ap, _cp, stage_bases = cfg.calibration()
    shoppers = generate_population(PopulationConfig(
        seed=cfg.seed, population_size=cfg.population_size,
        segments=load_segment_specs(cfg.personas_path), run_index=0,
        stage_bases=stage_bases))
    seg = {shopper_offset(s.shopper_id): s.segment_id for s in shoppers}

    rebuilt, notes = report_for_run(run_dir, run_index=run_index,
                                    segment_by_offset=seg)
    assert not [n for n in notes if "skipped" in n or "unavailable" in n], notes
    assert norm(rebuilt) == norm(results)


def test_provenance_sweep_sees_the_real_graph(rerun):
    """The belief block is the only part of the report that reads HydraDB, so
    assert it against the store rather than against the fixture alone."""
    _run_dir, run_index, results = rerun
    mem = HydraMem(run_index=run_index)
    try:
        live = 0
        for off in range(N):
            now = 1_755_000_000 + 2 * 86_400
            live += len(mem.client.run_stmt(
                cypher.live_holds(make_sid(run_index, off), now)))
    finally:
        mem.close()
    assert results["provenance_coverage"]["beliefs"]["versions"] == live
    assert sum(r["count"] for r in results["belief_confidence_dist"]) == live
