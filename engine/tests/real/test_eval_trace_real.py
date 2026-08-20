"""--trace-decisions must be observationally inert (Law 13).

The trace exists to make calibration cheap. If switching it on changed what a
run produced — by consuming an rng draw, by reordering a write, by anything —
then every profile fitted against a traced run would have been fitted against a
different simulator than the one that ships. This is the test that says it did
not.

Runs the committed golden config twice on the live store, once traced and once
not, and hashes both reports under the run-block normalisation that
fixtures/golden-run/README.md defines (run_index is the one key that
legitimately differs between reproductions).
"""

import hashlib
import json
from pathlib import Path

import pytest

from shopsim.eval.trace import TRACE_FILENAME
from shopsim.runner.config import RunConfig
from shopsim.runner.loop import SimRunner
from shopsim.runner.runstore import RunStore

pytestmark = pytest.mark.real

REPO = Path(__file__).resolve().parents[3]
GOLDEN = REPO / "fixtures" / "golden-run"


def _norm_hash(results: dict) -> str:
    r = json.loads(json.dumps(results))
    r["run_manifest"].pop("run_index", None)
    return hashlib.sha256(
        json.dumps(r, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _run(tmp_root: Path, *, trace: bool):
    cfg = RunConfig.load(GOLDEN / "run_config.json")
    store = RunStore(cfg.root)
    arm = cfg.arms[0].name
    run_index, run_dir = store.allocate(cfg, arm)
    runner = SimRunner(cfg, arm, run_index, run_dir, quiet=True, trace_decisions=trace)
    try:
        runner.prepare(seed_graph=True)
        store.set_status(run_dir.name, "running")
        results = runner.run()
        store.set_status(run_dir.name, "complete")
    finally:
        runner.close()
    return run_dir, results


@pytest.fixture(scope="module")
def pair(tmp_path_factory):
    root = tmp_path_factory.mktemp("trace-neutrality")
    return _run(root, trace=True), _run(root, trace=False)


def test_tracing_does_not_change_the_run(pair):
    (_traced_dir, traced), (_plain_dir, plain) = pair
    assert _norm_hash(traced) == _norm_hash(plain), (
        "--trace-decisions changed results.json — the trace is not inert, and "
        "any calibration fitted on a traced run is suspect")


def test_both_reproduce_the_committed_golden(pair):
    """Same seed, same hashes, same numbers — including through the Phase-7
    calibration changes, which is what makes the regenerated fixture load-
    bearing rather than decorative."""
    committed = json.loads((GOLDEN / "results.json").read_text())
    for _dir, results in pair:
        assert _norm_hash(results) == _norm_hash(committed)


def test_the_trace_file_exists_only_when_asked_for(pair):
    (traced_dir, _t), (plain_dir, _p) = pair
    assert (traced_dir / TRACE_FILENAME).exists()
    assert not (plain_dir / TRACE_FILENAME).exists(), \
        "a run without --trace-decisions must leave no trace file at all"


def test_the_trace_covers_every_decision_the_run_made(pair):
    """One row per decision, both phases, and the header records the profile the
    run actually used — without which a replay cannot rebase correctly."""
    from shopsim.eval import trace as T

    (traced_dir, results), _plain = pair
    header, rows = T.load(traced_dir / TRACE_FILENAME)
    assert set(header["stage_bases"]) == {"CLICK", "BROWSE", "CART", "BUY"}

    totals = {}
    for segments in results["funnel"].values():
        for counts in segments.values():
            for k, v in counts.items():
                totals[k] = totals.get(k, 0) + v
    creative = [r for r in rows if T.field(r, "kind") == "creative"]
    assert len(creative) == totals["SAW"], \
        "every impression is one creative-phase decision"
    clicked = [r for r in creative if T.field(r, "action") == "CLICK"]
    assert len(clicked) == totals["CLICKED"]
