"""Image/text ad ingestion (4.1, CONTRACT v3.4-draft).

    upload ads → materialized per-experiment catalog → perception ONCE, live
    → frozen per-experiment cache → the engine runs offline forever after.

Materialized layout (demo-brand and the SHARED perception cache stay
pristine — their manifest hashes never move):

    fixtures/experiments/<name>/
        catalog/              full demo-brand copy + images/ + extended
                              creatives.json (ids max+1 — never IdAllocator,
                              which restarts at 2000001 and collides)
        perception-cache/     committed base entries copied byte-identical
                              + one new frozen entry per ingested ad

Ingest is idempotent: re-running adds nothing, calls nothing. Any uncached
ad with no LLM key fails loudly HERE — never at run time (the runner's
prepare() asserts zero perception calls).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

from ..perception import perceive
from .specs import _module_repo_root

_AD_KEYS = {"image", "brand_id", "offer_product_ids", "headline", "body", "name"}


def _ad_signature(row: dict, catalog_dir: Path) -> str:
    """Identity for idempotent re-ingest: image ads by image bytes, text ads
    by their canonical prose + offers."""
    if row.get("image"):
        return "img:" + hashlib.sha256(
            (catalog_dir / row["image"]).read_bytes()).hexdigest()
    blob = json.dumps({
        "brand_id": row["brand_id"], "name": row.get("name", ""),
        "headline": row.get("headline", ""), "body": row.get("body", ""),
        "offers": sorted(o["product_id"] for o in row["offers"]),
    }, separators=(",", ":"), sort_keys=True)
    return "txt:" + hashlib.sha256(blob.encode()).hexdigest()


def _spec_signature(ad: dict, image_bytes: bytes | None) -> str:
    if image_bytes is not None:
        return "img:" + hashlib.sha256(image_bytes).hexdigest()
    blob = json.dumps({
        "brand_id": ad["brand_id"], "name": ad.get("name", ""),
        "headline": ad.get("headline", ""), "body": ad.get("body", ""),
        "offers": sorted(int(p) for p in ad["offer_product_ids"]),
    }, separators=(",", ":"), sort_keys=True)
    return "txt:" + hashlib.sha256(blob.encode()).hexdigest()


def _catalog_products(catalog_dir: Path) -> set[int]:
    import csv
    with open(catalog_dir / "catalog.csv", newline="") as fh:
        return {int(r["product_id"]) for r in csv.DictReader(fh)}


def _missing_perceptions(catalog_dir: Path, cache_dir: Path, model: str) -> list[int]:
    """Creative ids whose descriptor has no frozen cache entry — a pure
    cache probe, zero LLM calls."""
    missing: list[int] = []

    def probe(descriptor, _model, **_kw):
        missing.append(descriptor["creative_id"])
        return {"claims": [], "claimed_discounts": []}  # discarded below

    tmp = Path(cache_dir).with_name(Path(cache_dir).name + ".probe")
    try:
        # probe against a scratch cache dir so the fake outputs never land
        # in the real cache
        shutil.copytree(cache_dir, tmp, dirs_exist_ok=True)
        perceive.perceive_catalog(catalog_dir, cache_dir=tmp, model=model, call=probe)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return missing


def ingest_ads(
    spec_path: Path | str,
    *,
    name: str | None = None,
    root: Path | str | None = None,
    source_catalog: Path | str | None = None,
    base_cache: Path | str | None = None,
    model: str = perceive.DEFAULT_MODEL,
    call=None,
) -> Path:
    """Returns the experiment dir. `call` is the usual perception injection
    seam (tests); None = the live OpenAI client."""
    spec_path = Path(spec_path)
    spec = json.loads(spec_path.read_text())
    name = name or spec.get("name")
    if not name:
        raise ValueError("ingest needs an experiment name (--name or spec name)")
    ads = spec.get("ads", ())
    if not ads:
        raise ValueError("ingest spec has no ads[]")

    root = Path(root) if root is not None else _module_repo_root()
    if root is None:
        raise ValueError("cannot locate the repo root (fixtures/ + engine/)")
    source_catalog = Path(source_catalog) if source_catalog else root / "fixtures" / "demo-brand"
    base_cache = Path(base_cache) if base_cache else root / "fixtures" / "perception-cache"

    exp_dir = root / "fixtures" / "experiments" / name
    catalog_dir = exp_dir / "catalog"
    cache_dir = exp_dir / "perception-cache"
    images_dir = catalog_dir / "images"
    for d in (catalog_dir, cache_dir, images_dir):
        d.mkdir(parents=True, exist_ok=True)

    # 1. materialize the catalog (never overwrite an existing materialized
    # creatives.json — ids must stay stable across re-ingests)
    for src in sorted(source_catalog.iterdir()):
        if src.is_dir():
            continue
        dst = catalog_dir / src.name
        if not dst.exists():
            shutil.copy(src, dst)

    # 2. copy the committed base cache entries byte-identical (same keys)
    for src in sorted(base_cache.glob("*.json")):
        dst = cache_dir / src.name
        if not dst.exists():
            shutil.copy(src, dst)

    # 3. append new creative rows, ids above the existing max
    creatives_path = catalog_dir / "creatives.json"
    doc = json.loads(creatives_path.read_text())
    rows = doc["creatives"]
    known_products = _catalog_products(catalog_dir)
    existing_sigs = {_ad_signature(r, catalog_dir) for r in rows}
    next_id = max(r["creative_id"] for r in rows) + 1
    assigned: list[dict] = []
    for ad in ads:
        bad = set(ad) - _AD_KEYS
        if bad:
            raise ValueError(f"ad has unknown keys {sorted(bad)}")
        offers = [int(p) for p in ad.get("offer_product_ids", ())]
        if not offers or not set(offers) <= known_products:
            raise ValueError(f"ad {ad.get('name', '?')!r}: offer_product_ids must "
                             f"be non-empty and within the catalog ({sorted(known_products)})")
        image_bytes = None
        image_rel = None
        if ad.get("image"):
            src_img = Path(ad["image"])
            if not src_img.is_absolute():
                src_img = spec_path.parent / src_img
            image_bytes = src_img.read_bytes()
            perceive._image_mime(image_bytes)  # fail on unsupported formats now
            digest = hashlib.sha256(image_bytes).hexdigest()
            image_rel = f"images/{digest[:16]}{src_img.suffix.lower()}"
            if not (catalog_dir / image_rel).exists():
                (catalog_dir / image_rel).write_bytes(image_bytes)
        if _spec_signature(ad, image_bytes) in existing_sigs:
            continue  # idempotent re-ingest
        row = {
            "creative_id": next_id,
            "brand_id": int(ad["brand_id"]),
            "name": ad.get("name", f"Uploaded ad {next_id}"),
            "headline": ad.get("headline", ""),
            "body": ad.get("body", ""),
            "claims": [],  # perception decides what the ad claims
            "offers": [{"product_id": p, "claimed_pct": 0.0} for p in offers],
        }
        if image_rel is not None:
            row["image"] = image_rel
        rows.append(row)
        existing_sigs.add(_spec_signature(ad, image_bytes))
        assigned.append({"creative_id": next_id, "name": row["name"],
                         "image": image_rel})
        next_id += 1
    creatives_path.write_text(json.dumps(doc, indent=2) + "\n")

    # 4. perceive — loudly refuse BEFORE any partial live calls if the key
    # is missing (the engine's offline guard would only fail at run time)
    missing = _missing_perceptions(catalog_dir, cache_dir, model)
    if missing and call is None:
        perceive._load_env_key()
        if not os.environ.get("OPENAI_API_KEY"):
            raise ValueError(
                f"ingest needs OPENAI_API_KEY (env or <repo>/.env.local) to "
                f"perceive {len(missing)} new ad(s): {sorted(missing)}")
    _, calls = perceive.perceive_catalog(
        catalog_dir, cache_dir=cache_dir, model=model, call=call)

    manifest = {
        "experiment": name,
        "catalog": str(catalog_dir),
        "perception_cache": str(cache_dir),
        "ingested": assigned,
        "perception_calls": calls,
        "all_creative_ids": sorted(r["creative_id"] for r in rows),
    }
    (exp_dir / "ads-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return exp_dir
