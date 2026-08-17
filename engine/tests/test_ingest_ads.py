"""Phase 4: ad ingestion — materialized per-experiment catalog + frozen
perception cache (CONTRACT v3.4-draft). Demo-brand and the shared cache stay
pristine; the engine runs offline after ingest."""

import json
from pathlib import Path

import pytest

from shopsim.experiments.ingest import ingest_ads
from shopsim.minds.objective_view import ObjectiveView
from shopsim.perception.cache import perceived_maps
from shopsim.perception.perceive import perceive_catalog

REPO = Path(__file__).resolve().parents[2]
DEMO = REPO / "fixtures" / "demo-brand"
BASE_CACHE = REPO / "fixtures" / "perception-cache"

PNG = b"\x89PNG\r\n\x1a\n" + b"spring-hero-image-bytes"

OUTPUT = {"claims": [{"concept": "STYLE", "strength": 0.8},
                     {"concept": "DISCOUNT", "strength": 0.6}],
          "claimed_discounts": [{"product_id": 3000001, "claimed_pct": 0.2}]}


def counting_stub():
    calls = []

    def stub(descriptor, model, **kw):
        calls.append((descriptor["creative_id"], "image_bytes" in kw))
        return OUTPUT

    return stub, calls


def write_spec(tmp_path, ads) -> Path:
    (tmp_path / "ad1.png").write_bytes(PNG)
    spec = {"name": "test-ads", "ads": ads}
    p = tmp_path / "ads.json"
    p.write_text(json.dumps(spec))
    return p


def default_ads():
    return [
        {"image": "ad1.png", "brand_id": 6001, "offer_product_ids": [3000001],
         "headline": "Spring drop", "name": "Spring Hero"},
        {"brand_id": 6001, "offer_product_ids": [3000002], "name": "Trail Text",
         "headline": "Hit the trail", "body": "Grippy. Tough. Ready."},
    ]


def run_ingest(tmp_path, ads=None, call=None):
    spec = write_spec(tmp_path, ads or default_ads())
    return ingest_ads(spec, root=tmp_path, source_catalog=DEMO,
                      base_cache=BASE_CACHE, call=call)


def test_ingest_materializes_and_assigns_ids(tmp_path):
    stub, calls = counting_stub()
    exp_dir = run_ingest(tmp_path, call=stub)

    catalog = exp_dir / "catalog"
    assert (catalog / "catalog.csv").exists()
    assert (catalog / "latent_quality.csv").exists()
    assert (catalog / "page_variants.json").exists()

    doc = json.loads((catalog / "creatives.json").read_text())
    by_id = {r["creative_id"]: r for r in doc["creatives"]}
    # ids continue above the hand-assigned 2000001-2000005 (never IdAllocator)
    assert set(by_id) == {2000001, 2000002, 2000003, 2000004, 2000005,
                          2000006, 2000007}
    img_row = by_id[2000006]
    assert img_row["image"].startswith("images/")
    assert (catalog / img_row["image"]).read_bytes() == PNG
    assert img_row["claims"] == []  # perception decides, never the uploader
    assert by_id[2000007]["body"] == "Grippy. Tough. Ready."

    # one perception call per new ad; the image ad got its bytes
    assert calls == [(2000006, True), (2000007, False)]
    # base cache copied byte-identical + 2 new entries
    cache_files = sorted(p.name for p in (exp_dir / "perception-cache").glob("*.json"))
    assert len(cache_files) == 7

    manifest = json.loads((exp_dir / "ads-manifest.json").read_text())
    assert [a["creative_id"] for a in manifest["ingested"]] == [2000006, 2000007]

    # demo-brand and the shared cache are untouched
    assert len(json.loads((DEMO / "creatives.json").read_text())["creatives"]) == 5
    assert len(list(BASE_CACHE.glob("*.json"))) == 5


def test_reingest_is_idempotent(tmp_path):
    stub, calls = counting_stub()
    run_ingest(tmp_path, call=stub)
    assert len(calls) == 2

    stub2, calls2 = counting_stub()
    exp_dir = run_ingest(tmp_path, call=stub2)
    assert calls2 == []  # nothing new: no ids minted, no LLM calls
    doc = json.loads((exp_dir / "catalog" / "creatives.json").read_text())
    assert len(doc["creatives"]) == 7


def test_engine_runs_offline_after_ingest(tmp_path):
    stub, _ = counting_stub()
    exp_dir = run_ingest(tmp_path, call=stub)

    def no_llm(*a, **k):
        raise RuntimeError("engine must be offline")

    perceived, calls = perceive_catalog(
        exp_dir / "catalog", cache_dir=exp_dir / "perception-cache", call=no_llm)
    assert calls == 0  # the runner's prepare() guard will hold
    # and the perceived claims flow into the ObjectiveView the minds see
    claims, offers = perceived_maps(perceived)
    view = ObjectiveView.from_catalog(exp_dir / "catalog", claims, offers)
    facts = view.facts(2000006)
    assert facts is not None and facts.kind == "creative"
    assert facts.claims  # STYLE/DISCOUNT from the frozen cache entry
    assert facts.max_claimed_pct == pytest.approx(0.2)


def test_missing_key_fails_loudly_at_ingest(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("shopsim.perception.perceive._load_env_key", lambda: None)
    with pytest.raises(ValueError, match="OPENAI_API_KEY.*2000006"):
        run_ingest(tmp_path, call=None)


def test_ingest_rejects_unknown_products_and_keys(tmp_path):
    stub, _ = counting_stub()
    with pytest.raises(ValueError, match="offer_product_ids"):
        run_ingest(tmp_path, ads=[
            {"brand_id": 6001, "offer_product_ids": [999], "name": "bad"}],
            call=stub)
    with pytest.raises(ValueError, match="unknown keys"):
        run_ingest(tmp_path, ads=[
            {"brand_id": 6001, "offer_product_ids": [3000001],
             "claims": [{"concept_id": 5003, "strength": 1.0}]}],
            call=stub)
