"""Phase-5 live data plane (CONTRACT v3.5-draft): the dashboard API surface.

Unit tests run without HydraDB (file-serving endpoints on temp/committed run
dirs; pure stage_probabilities math). The real-marked tests exercise the
graph-backed endpoints against the live store.
"""

import json
import os
import time
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from shopsim.contracts.types import Appraisal, ChoiceCoeffs, Scalars
from shopsim.minds.calibration import DEFAULT_CHOICE_PARAMS, DEFAULT_STAGE_BASES
from shopsim.minds.choice import (
    _buy_probability,
    _gate_probability,
    stage_probabilities,
)
from shopsim.runner.api import create_app
from shopsim.runner.results import ResultsAccumulator

REPO_ROOT = Path(__file__).resolve().parents[2]
REPO_RUNS = REPO_ROOT / "runs"
R010 = "r010-image-ads-demo-c2000003"


# ---------------------------------------------------------------------------
# events tail
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_app(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    return runs, TestClient(create_app(runs))


def test_events_byte_tailing(tmp_app):
    runs, client = tmp_app
    d = runs / "x"
    d.mkdir()
    log = d / "events.jsonl"
    full = b'{"type":"SAW","shopper_id":1,"t":0}\n{"type":"CLICKED","shopper_id":1,"t":0}\n'
    partial = b'{"type":"BOU'
    log.write_bytes(full + partial)

    r = client.get("/runs/x/events").json()
    assert [rec["type"] for rec in r["records"]] == ["SAW", "CLICKED"]
    assert r["next"] == len(full)          # the partial line is NOT consumed
    assert r["eof"] is False

    # the writer finishes the line and adds one more
    rest = b'GHT","shopper_id":1,"t":0}\n{"type":"TICK_COMPLETE","tick":0}\n'
    log.write_bytes(full + partial + rest)
    r2 = client.get(f"/runs/x/events?after={r['next']}").json()
    assert [rec["type"] for rec in r2["records"]] == ["BOUGHT", "TICK_COMPLETE"]
    assert r2["eof"] is True

    # a truncated log (resume rollback) restarts the reader at 0
    log.write_bytes(full)
    r3 = client.get(f"/runs/x/events?after={10_000}").json()
    assert [rec["type"] for rec in r3["records"]] == ["SAW", "CLICKED"]

    # limit caps complete lines and the cursor stays consistent
    r4 = client.get("/runs/x/events?limit=1").json()
    assert len(r4["records"]) == 1 and r4["eof"] is False
    r5 = client.get(f"/runs/x/events?after={r4['next']}").json()
    assert [rec["type"] for rec in r5["records"]] == ["CLICKED"]


def test_events_404(tmp_app):
    _runs, client = tmp_app
    assert client.get("/runs/nope/events").status_code == 404


# ---------------------------------------------------------------------------
# results-live (from the committed r010 snapshots)
# ---------------------------------------------------------------------------


def _clone_r010(runs: Path, *, with_final: bool) -> None:
    src = REPO_RUNS / R010
    d = runs / R010
    d.mkdir()
    names = ["manifest.json", "progress.json", "results_state_4.json",
             "results_state_5.json"]
    if with_final:
        names.append("results.json")
    for n in names:
        shutil.copy(src / n, d / n)


def test_results_live_equals_from_state(tmp_app):
    runs, client = tmp_app
    _clone_r010(runs, with_final=False)
    r = client.get(f"/runs/{R010}/results-live")
    assert r.status_code == 200
    body = r.json()
    snap = json.loads((REPO_RUNS / R010 / "results_state_5.json").read_text())
    manifest = json.loads((REPO_RUNS / R010 / "manifest.json").read_text())
    expected = ResultsAccumulator.from_state(
        snap["state"], segment_by_offset={}, drift_concepts=[],
        hero_product=None).results(manifest)
    assert body["tick"] == snap["tick"]
    assert body["results"] == json.loads(json.dumps(expected))
    # pre-v3.5 snapshot -> empty belief_avg, never a KeyError
    assert body["live_extras"] == {"belief_avg": {}}


def test_results_live_survives_snapshot_deletion(tmp_app):
    runs, client = tmp_app
    _clone_r010(runs, with_final=False)
    # simulate the loop's keep-last-2 deletion race: newest gone mid-glob
    (runs / R010 / "results_state_5.json").unlink()
    r = client.get(f"/runs/{R010}/results-live")
    assert r.status_code == 200
    assert r.json()["tick"] == 4


def test_results_live_serves_final_when_present(tmp_app):
    runs, client = tmp_app
    _clone_r010(runs, with_final=True)
    body = client.get(f"/runs/{R010}/results-live").json()
    final = json.loads((REPO_RUNS / R010 / "results.json").read_text())
    assert body["results"] == final
    assert body["status"] == "complete"


# ---------------------------------------------------------------------------
# config + population (read-only against the committed repo runs)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def repo_client():
    return TestClient(create_app(REPO_RUNS))


def test_config_effective_matches_runconfig(repo_client):
    from shopsim.runner.config import RunConfig
    body = repo_client.get(f"/runs/{R010}/config")
    assert body.status_code == 200
    eff = body.json()["effective"]
    cfg = RunConfig.load(REPO_RUNS / "experiments" / "image-ads-demo" / "run_config.json")
    arm = cfg.arm("c2000003")
    assert eff["label"] == cfg.label and eff["seed"] == cfg.seed
    assert eff["ticks"] == cfg.ticks and eff["arms"] == [a.name for a in cfg.arms]
    sched = cfg.schedule_for(arm)
    assert [r["creative_id"] for r in eff["schedule"]] == [r.creative_id for r in sched]
    assert eff["goal_overrides"] == cfg.goal_overrides(arm)
    assert isinstance(eff["goal_waves"], list)


def test_population_matches_factory_and_leaks_nothing(repo_client):
    from shopsim.contracts.ids import shopper_offset
    from shopsim.population.factory import (
        PopulationConfig, generate_population, load_segment_specs)
    from shopsim.runner.config import RunConfig
    body = repo_client.get(f"/runs/{R010}/population")
    assert body.status_code == 200
    payload = body.json()

    cfg = RunConfig.load(REPO_RUNS / "experiments" / "image-ads-demo" / "run_config.json")
    row = json.loads((REPO_RUNS / "registry.json").read_text())
    run_index = next(r["run_index"] for r in row["runs"] if r["run_id"] == R010)
    _ap, _cp, sb = cfg.calibration()
    expected = generate_population(PopulationConfig(
        seed=cfg.seed, population_size=cfg.population_size,
        segments=load_segment_specs(cfg.personas_path),
        run_index=run_index, stage_bases=sb))
    assert len(payload["shoppers"]) == len(expected)
    for got, exp in zip(payload["shoppers"], expected):
        assert got["shopper_id"] == exp.shopper_id
        assert got["segment_id"] == exp.segment_id
        assert got["offset"] == shopper_offset(exp.shopper_id)
        # Law 12/15: identity + segment ONLY
        assert set(got) == {"offset", "shopper_id", "segment_id"}


# ---------------------------------------------------------------------------
# experiments launch guardrails
# ---------------------------------------------------------------------------

MINIMAL_SPEC = {
    "type": "ad_test", "name": "api-test-spec", "seed": 1, "ticks": 2, "t0": 0,
    "population": {"size": 5},
    "creatives": [{"creative_id": 2000001, "reach_prob": 0.3}],
}


class _DummyProc:
    pid = 424242
    def poll(self):
        return 0


def _no_spawn(monkeypatch):
    """Launches under test must never actually run the engine CLI."""
    from shopsim.runner import api as api_mod
    monkeypatch.setattr(api_mod.subprocess, "Popen", lambda *a, **k: _DummyProc())


def test_launch_invalid_spec_422(tmp_app):
    _runs, client = tmp_app
    r = client.post("/experiments", json={"type": "nope"})
    assert r.status_code == 422


def test_launch_409_while_orchestrator_live(tmp_app, monkeypatch):
    from shopsim.runner import api as api_mod
    runs, client = tmp_app
    busy = runs / "experiments" / "already-running"
    busy.mkdir(parents=True)
    (busy / "orchestrator.pid").write_text("12345")
    monkeypatch.setattr(api_mod, "_pid_is_live_orchestrator", lambda pid: True)
    r = client.post("/experiments", json=MINIMAL_SPEC)
    assert r.status_code == 409
    assert "already-running" in r.json()["detail"]


def test_launch_heals_dead_or_zombie_pidfile(tmp_app, monkeypatch):
    """The every-launch-409 bug: a pidfile pointing at an exited/zombie
    orchestrator must never block. The current pytest process is alive but is
    NOT the experiments CLI, so the hardened check treats it as dead."""
    runs, client = tmp_app
    stale = runs / "experiments" / "finished-earlier"
    stale.mkdir(parents=True)
    (stale / "orchestrator.pid").write_text(str(os.getpid()))
    _no_spawn(monkeypatch)
    r = client.post("/experiments", json=MINIMAL_SPEC)
    assert r.status_code == 202, r.json()
    assert (runs / "experiments" / MINIMAL_SPEC["name"] / "spec.json").exists()


def test_launch_heals_stale_running_row(tmp_app, monkeypatch):
    import time
    runs, client = tmp_app
    run_dir = runs / "r099-old-crashed-main"
    run_dir.mkdir()
    (run_dir / "progress.json").write_text(json.dumps(
        {"tick": 3, "ticks": 14, "status": "running",
         "updated_at": time.time() - 3600}))
    (runs / "registry.json").write_text(json.dumps({
        "next_run_index": 100,
        "runs": [{"run_id": "r099-old-crashed-main", "run_index": 99,
                  "label": "old-crashed", "arm": "main", "kind": "run",
                  "seed": 1, "config_hash": "x", "dir": str(run_dir),
                  "status": "running"}],
    }))
    _no_spawn(monkeypatch)
    r = client.post("/experiments", json=MINIMAL_SPEC)
    assert r.status_code == 202, r.json()
    reg = json.loads((runs / "registry.json").read_text())
    assert reg["runs"][0]["status"] == "stale"  # auto-healed, never wedges again


def test_launch_fresh_running_row_blocks_and_force_overrides(tmp_app, monkeypatch):
    import time
    runs, client = tmp_app
    run_dir = runs / "r100-live-main"
    run_dir.mkdir()
    (run_dir / "progress.json").write_text(json.dumps(
        {"tick": 3, "ticks": 14, "status": "running",
         "updated_at": time.time() - 5}))
    (runs / "registry.json").write_text(json.dumps({
        "next_run_index": 101,
        "runs": [{"run_id": "r100-live-main", "run_index": 100,
                  "label": "live", "arm": "main", "kind": "run",
                  "seed": 1, "config_hash": "x", "dir": str(run_dir),
                  "status": "running"}],
    }))
    _no_spawn(monkeypatch)
    r = client.post("/experiments", json=MINIMAL_SPEC)
    assert r.status_code == 409
    assert "force=1" in r.json()["detail"]
    r2 = client.post("/experiments?force=1", json=MINIMAL_SPEC)
    assert r2.status_code == 202, r2.json()


def test_ingest_refuses_without_key(tmp_app, monkeypatch):
    """Clearing the env var is no longer enough to simulate "no key": the
    endpoint now resolves <repo>/.env.local the way the CLI does, so the
    absence has to be faked at the resolver. The refusal names both places
    it looked."""
    _runs, client = tmp_app
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("shopsim.perception.perceive.resolve_api_key", lambda: None)
    r = client.post("/experiments/ingest-ads",
                    json={"name": "x", "spec": {"ads": [{}]}})
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "OPENAI_API_KEY" in detail and ".env.local" in detail


# ---------------------------------------------------------------------------
# stage_probabilities: pure + identical to the gate math decide() draws on
# ---------------------------------------------------------------------------


def _appraisal() -> Appraisal:
    return Appraisal(relevance=0.7, credibility=0.55, brand_message_fatigue=0.2,
                     offer_attractiveness=0.4, expectation_alignment=0.9)


def _scalars(active_need=None) -> Scalars:
    return Scalars(shopper_id=1000042, aware_of_brand=True, adstock=0.5,
                   exposures_72h=2, last_seen_t=None,
                   reference_price={3000001: 39.0}, current_price_gap=-0.1,
                   budget_left=120.0, cart=(), trust_belief=None,
                   quality_belief=None, active_need=active_need, habit=None)


def _coeffs() -> ChoiceCoeffs:
    return ChoiceCoeffs(impulsivity=1.0, price_sensitivity=0.5, budget=120.0,
                        stage_bases=DEFAULT_STAGE_BASES)


def test_stage_probabilities_matches_gate_math():
    a, s, c = _appraisal(), _scalars(), _coeffs()
    creative = stage_probabilities(a, s, c, kind="creative")
    assert set(creative) == {"CLICK"}
    assert creative["CLICK"] == _gate_probability("CLICK", a, s, c, DEFAULT_CHOICE_PARAMS)
    page = stage_probabilities(a, s, c, kind="page")
    assert set(page) == {"BROWSE", "CART", "BUY"}
    assert page["BROWSE"] == _gate_probability("BROWSE", a, s, c, DEFAULT_CHOICE_PARAMS)
    assert page["CART"] == _gate_probability("CART", a, s, c, DEFAULT_CHOICE_PARAMS)
    assert page["BUY"] == _buy_probability(a, s, c, DEFAULT_CHOICE_PARAMS)
    # pure: same inputs, same outputs
    assert stage_probabilities(a, s, c, kind="page") == page
    with pytest.raises(ValueError):
        stage_probabilities(a, s, c, kind="banner")


def test_stage_probabilities_budget_guard():
    a, c = _appraisal(), _coeffs()
    s = Scalars(shopper_id=1, aware_of_brand=True, adstock=0.0, exposures_72h=0,
                last_seen_t=None, reference_price={3000001: 200.0},
                current_price_gap=0.0, budget_left=50.0, cart=(),
                trust_belief=None, quality_belief=None, active_need=None,
                habit=None)
    assert stage_probabilities(a, s, c, kind="page")["BUY"] == 0.0  # hard block


# ---------------------------------------------------------------------------
# real-store: graph-backed endpoints (SHOPSIM_HYDRAMEM=real + live HydraDB)
# ---------------------------------------------------------------------------

pytestmark_real = pytest.mark.real


@pytest.mark.real
def test_worldview_endpoint_real(repo_client):
    r = repo_client.get(f"/runs/{R010}/shoppers/1/worldview")
    if r.status_code == 503:
        pytest.skip("HydraDB not reachable or r010 block wiped")
    assert r.status_code == 200
    wv = r.json()
    assert set(wv) >= {"beliefs", "preferences", "active_needs", "expects"}


@pytest.mark.real
def test_decision_preview_deterministic_real(repo_client):
    url = f"/runs/{R010}/shoppers/1/decision-preview/2000003"
    r1 = repo_client.get(url)
    if r1.status_code == 503:
        pytest.skip("HydraDB not reachable or r010 block wiped")
    assert r1.status_code == 200, r1.json()
    r2 = repo_client.get(url)
    assert r1.json() == r2.json()  # pure math, no rng, byte-identical
    body = r1.json()
    assert body["stimulus"]["kind"] == "creative"
    assert set(body["probabilities"]) == {"CLICK"}
    assert 0.0 <= body["probabilities"]["CLICK"] <= 1.0
    assert set(body["appraisal"]) >= {"relevance", "credibility",
                                      "brand_message_fatigue",
                                      "offer_attractiveness",
                                      "expectation_alignment"}


# ---------------------------------------------------------------------------
# ads-manifest + ad image (v3.6-draft): what Studio polls to learn the
# creative ids and paths a launch spec must carry
# ---------------------------------------------------------------------------


def _fx(runs: Path, name: str) -> Path:
    d = runs.parent / "fixtures" / "experiments" / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def test_ads_manifest_none_before_any_upload(tmp_app):
    runs, client = tmp_app
    body = client.get("/experiments/nothing-here/ads-manifest").json()
    assert body == {"status": "none", "manifest": None}


def test_ads_manifest_reports_ingesting_while_uploads_exist(tmp_app):
    runs, client = tmp_app
    up = _fx(runs, "shoes") / "uploads"
    up.mkdir()
    (up / "ingest.log").write_text("perceiving ad 1/2\n")
    body = client.get("/experiments/shoes/ads-manifest").json()
    assert body["status"] == "ingesting"
    assert body["manifest"] is None
    assert "perceiving" in body["log_tail"]


def test_ads_manifest_ready_returns_repo_relative_paths(tmp_app):
    """The manifest stores absolute paths; a spec's catalog/perception_cache
    resolve against the repo root, so the endpoint must relativize them."""
    runs, client = tmp_app
    fx = _fx(runs, "shoes")
    (fx / "uploads").mkdir()
    (fx / "ads-manifest.json").write_text(json.dumps({
        "experiment": "shoes",
        "catalog": str(fx / "catalog"),
        "perception_cache": str(fx / "perception-cache"),
        "ingested": [{"creative_id": 2000006, "name": "Ad A", "image": "images/a.png"}],
        "perception_calls": 1,
        "all_creative_ids": [2000001, 2000006],
    }))
    body = client.get("/experiments/shoes/ads-manifest").json()
    assert body["status"] == "ready"
    assert body["catalog"] == "fixtures/experiments/shoes/catalog"
    assert body["perception_cache"] == "fixtures/experiments/shoes/perception-cache"
    assert not Path(body["catalog"]).is_absolute()
    assert body["manifest"]["all_creative_ids"] == [2000001, 2000006]


def test_ad_image_round_trips(tmp_app):
    runs, client = tmp_app
    cat = _fx(runs, "shoes") / "catalog"
    (cat / "images").mkdir(parents=True)
    blob = b"\x89PNG\r\n\x1a\n" + b"fake-bytes"
    (cat / "images" / "a.png").write_bytes(blob)
    (cat / "creatives.json").write_text(json.dumps([
        {"creative_id": 2000006, "name": "Ad A", "image": "images/a.png"},
        {"creative_id": 2000001, "name": "Text ad"},
    ]))

    r = client.get("/experiments/shoes/ads/2000006/image")
    assert r.status_code == 200
    assert r.content == blob

    assert client.get("/experiments/shoes/ads/2000001/image").status_code == 404  # text-only
    assert client.get("/experiments/shoes/ads/9999999/image").status_code == 404  # no row
    assert client.get("/experiments/nope/ads/2000006/image").status_code == 404   # no catalog


def test_ad_image_refuses_path_escape(tmp_app):
    """A creatives.json row must not be able to name a file outside the
    experiment's own catalog."""
    runs, client = tmp_app
    fx = _fx(runs, "shoes")
    cat = fx / "catalog"
    cat.mkdir(parents=True)
    (runs.parent / "secret.txt").write_text("nope")
    (cat / "creatives.json").write_text(json.dumps([
        {"creative_id": 2000006, "name": "Escape", "image": "../../../secret.txt"},
    ]))
    assert client.get("/experiments/shoes/ads/2000006/image").status_code == 404


def test_experiment_name_stays_one_path_segment(tmp_app):
    runs, client = tmp_app
    r = client.get("/experiments/..%2F..%2Fetc/ads-manifest")
    assert r.status_code in (404, 422)


def test_ad_image_reads_the_real_ingest_shape(tmp_app):
    """ingest.py writes {"comment":…, "creatives":[…]}, not a bare list.
    Iterating the dict yields string keys, which used to 500 the endpoint on
    every real catalog while the list-shaped fixture above stayed green."""
    runs, client = tmp_app
    cat = _fx(runs, "shoes") / "catalog"
    (cat / "images").mkdir(parents=True)
    blob = b"\x89PNG\r\n\x1a\n" + b"real-ingest-shape"
    (cat / "images" / "a.png").write_bytes(blob)
    (cat / "creatives.json").write_text(json.dumps({
        "comment": "generated by shopsim.experiments ingest-ads",
        "creatives": [
            {"creative_id": 2000006, "brand_id": 6001, "name": "Ad A",
             "image": "images/a.png", "claims": [], "offers": []},
        ],
    }))

    r = client.get("/experiments/shoes/ads/2000006/image")
    assert r.status_code == 200, r.text
    assert r.content == blob



# ---------------------------------------------------------------------------
# creative cards (v3.7-draft): the ads as ads, not as {id: name}
# ---------------------------------------------------------------------------

NISOLO = REPO_ROOT / "fixtures" / "nisolo"


def test_catalogs_lists_the_committed_brands(repo_client):
    rows = repo_client.get("/catalogs").json()
    by_key = {r["key"]: r for r in rows}
    assert "nisolo" in by_key and "demo-brand" in by_key
    nis = by_key["nisolo"]
    assert nis["n_creatives"] == 5
    # the companion config paths ride along so the client never hardcodes them
    assert nis["personas"].endswith("nisolo/personas.json")
    assert nis["goal_config"].endswith("nisolo/goal_config.json")


def test_catalog_creatives_carry_copy_and_perceived_claims(repo_client):
    body = repo_client.get("/catalogs/nisolo/creatives").json()
    cards = {c["creative_id"]: c for c in body["creatives"]}
    assert len(cards) == 5

    sale = cards[2000103]
    assert sale["headline"].startswith("Up to 40% off")
    assert sale["body"]                      # the copy a human reads
    assert sale["brand_name"] == "Nisolo" or sale["brand_id"] == 6100
    assert sale["image_url"] == "/catalogs/nisolo/creatives/2000103/image"

    # the exhibit: authored 0.0, perceived ~40% off the image
    assert sale["offers"][0]["claimed_pct"] == 0.0
    assert sale["perceived"]["from_image"] is True
    assert sale["perceived"]["prompt_version"] == "p1-img1"
    got = {d["product_id"]: d["claimed_pct"] for d in sale["perceived"]["claimed_discounts"]}
    assert got.get(3000101, 0.0) >= 0.35

    # the offer resolves to a real product with a real price and a landing page
    offer = sale["offers"][0]
    assert offer["name"] and offer["list_price"] > 0 and offer["page_ids"]

    # the tiered ad carries its "not modelled" caveat to the UI
    assert "NOT FULLY MODELLED" in (cards[2000104]["note"] or "")


def test_catalog_creative_image_round_trips(repo_client):
    r = repo_client.get("/catalogs/nisolo/creatives/2000103/image")
    assert r.status_code == 200
    assert r.content == (NISOLO / "images" / "nisolo-discount.jpg").read_bytes()


def test_catalog_endpoints_reject_unknown_keys(repo_client):
    assert repo_client.get("/catalogs/nope/creatives").status_code == 404
    # not a path parameter: a traversal attempt is simply an unknown key
    assert repo_client.get("/catalogs/..%2F..%2Fetc/creatives").status_code == 404


def test_run_creatives_reads_the_runs_own_catalog(tmp_app):
    """A run's cards come from ITS catalog_dir, so a committed brand and an
    ingested experiment catalog resolve through one endpoint."""
    runs, client = tmp_app
    exp = runs / "experiments" / "nis"
    exp.mkdir(parents=True)
    (runs / "registry.json").write_text(json.dumps({"next_run_index": 11, "runs": [
        {"run_id": "r010-nis-market", "run_index": 10, "label": "nis", "arm": "market",
         "kind": "ad_test", "seed": 1, "config_hash": "x", "status": "complete",
         "dir": str(runs / "r010-nis-market")}]}))
    (exp / "run_config.json").write_text(json.dumps({
        "label": "nis", "seed": 1, "ticks": 2, "t0": 0,
        "population": {"size": 4, "personas": str(NISOLO / "personas.json")},
        "catalog_dir": str(NISOLO), "perception_cache": str(NISOLO / "perception-cache"),
        "goals": {"config": str(NISOLO / "goal_config.json")},
        "exposure": {"schedule": [{"creative_id": 2000103, "start_tick": 0,
                                   "end_tick": 1, "reach_prob": 0.5}]},
        "arms": [{"name": "market"}],
    }))
    body = client.get("/runs/r010-nis-market/creatives").json()
    ids = {c["creative_id"] for c in body["creatives"]}
    assert 2000103 in ids
    sale = next(c for c in body["creatives"] if c["creative_id"] == 2000103)
    assert sale["image_url"] == "/runs/r010-nis-market/creatives/2000103/image"
    assert client.get(sale["image_url"]).status_code == 200


# ---------------------------------------------------------------------------
# launch serialization (the guard that keeps Law 8's single writer single)
# ---------------------------------------------------------------------------


def _registry(runs: Path, rows: list[dict]) -> None:
    (runs / "registry.json").write_text(json.dumps({"runs": rows}))


VALID_SPEC = {"name": "probe", "type": "ad_test", "seed": 1, "ticks": 4,
              "t0": 1800000000, "population": {"size": 10},
              "creatives": [{"creative_id": 2000001, "reach_prob": 0.3}]}


def _row(runs: Path, run_id: str, status: str, **kw) -> dict:
    d = runs / run_id
    d.mkdir(exist_ok=True)
    return {"run_id": run_id, "run_index": int(run_id[1:4]), "dir": str(d),
            "label": kw.get("label", "demo"), "arm": kw.get("arm", "a"),
            "status": status, "kind": "run", "seed": 1, "config_hash": "x"}


def test_engine_busy_is_free_when_nothing_is_running(tmp_app):
    runs, client = tmp_app
    _registry(runs, [_row(runs, "r001-demo-a", "complete")])
    body = client.get("/engine/busy").json()
    assert body == {"busy": False, "blocker": None}


def test_a_running_row_with_a_live_writer_blocks_and_names_the_process(tmp_app, monkeypatch):
    """The bug this encodes: a `shopsim.eval` run held the engine, and the
    refusal could only say "looks live" because the pid check matched
    `shopsim.experiments` alone."""
    runs, client = tmp_app
    row = _row(runs, "r002-f12-fatigue-rotation", "running", label="f12-fatigue", arm="rotation")
    _registry(runs, [row])
    (runs / "r002-f12-fatigue-rotation" / "progress.json").write_text(
        json.dumps({"status": "running", "tick": 11, "ticks": 16,
                    "updated_at": time.time()}))
    monkeypatch.setattr("shopsim.runner.api._any_live_writer",
                        lambda: {"pid": 4242, "command": "python -m shopsim.eval scenarios"})

    blocker = client.get("/engine/busy").json()["blocker"]
    assert blocker["stale"] is False
    assert blocker["run_id"] == "r002-f12-fatigue-rotation"
    assert blocker["pid"] == 4242 and "shopsim.eval" in blocker["command"]
    assert (blocker["tick"], blocker["ticks"]) == (11, 16)

    r = client.post("/experiments", json=VALID_SPEC)
    assert r.status_code == 409
    assert r.headers["X-Busy-Stale"] == "0"


def test_a_slow_tick_is_not_mistaken_for_a_dead_run(tmp_app, monkeypatch):
    """The regression that matters. Per-tick cost grows with the store: a
    500-shopper scenario measured ~265 s/tick on 2026-08-20. Under the old
    300 s timer this row would have been healed to 'stale' and a SECOND writer
    admitted into a registry whose read-modify-write is not concurrent-safe."""
    runs, client = tmp_app
    row = _row(runs, "r003-demo-a", "running")
    _registry(runs, [row])
    (runs / "r003-demo-a" / "progress.json").write_text(
        json.dumps({"status": "running", "tick": 3, "ticks": 60,
                    "updated_at": time.time() - 420}))   # quiet for 7 minutes
    monkeypatch.setattr("shopsim.runner.api._any_live_writer",
                        lambda: {"pid": 7, "command": "python -m shopsim.experiments run"})

    blocker = client.get("/engine/busy").json()["blocker"]
    assert blocker is not None and blocker["stale"] is False
    assert blocker["quiet_s"] >= 300, "the point of the test is a quiet gap past the old window"
    assert json.loads((runs / "registry.json").read_text())["runs"][0]["status"] == "running", \
        "a live run must never be healed to stale"


def test_a_crashed_run_is_forceable_and_says_so(tmp_app, monkeypatch):
    """No writer process, so the row is a leftover — this is the one case
    where force is safe, and the only case where the UI offers it."""
    runs, client = tmp_app
    _registry(runs, [_row(runs, "r004-demo-a", "running")])
    (runs / "r004-demo-a" / "progress.json").write_text(
        json.dumps({"status": "running", "tick": 2, "ticks": 10,
                    "updated_at": time.time() - 60}))
    monkeypatch.setattr("shopsim.runner.api._any_live_writer", lambda: None)

    blocker = client.get("/engine/busy").json()["blocker"]
    assert blocker["stale"] is True and blocker["pid"] is None
    r = client.post("/experiments", json=VALID_SPEC)
    assert r.status_code == 409 and r.headers["X-Busy-Stale"] == "1"


def test_serve_is_a_reader_and_never_counts_as_a_writer():
    """`runner serve` IS the API process. If it matched, the API would report
    itself as the thing blocking every launch."""
    from shopsim.runner import api as api_mod

    def fake_ps(cmd, **kw):
        class R:
            stdout = "  42 S    python -m shopsim.runner serve --config x.json\n"
        return R()

    import subprocess as sp
    real = sp.run
    try:
        sp.run = fake_ps
        assert api_mod._any_live_writer() is None
    finally:
        sp.run = real
