"""Phase 5.8: the Nisolo brand fixture — a real brand, perceived once, frozen.

The load-bearing claim of this fixture is that the ads' claims were READ OFF
THE IMAGES by a multimodal model, not typed into the catalog by hand. These
tests exist to make that claim falsifiable: if someone hand-edits a cache
entry, re-encodes an image, or quietly authors the 40% discount into
creatives.json, something here goes red.
"""

import csv
import hashlib
import json
from pathlib import Path

import pytest

from shopsim.contracts.enums import Category, Concept
from shopsim.perception.cache import load as cache_load
from shopsim.perception.perceive import (
    IMAGE_PROMPT_VERSION,
    descriptor_for,
    perceive_catalog,
    stimulus_hash,
)

REPO = Path(__file__).resolve().parents[2]
NISOLO = REPO / "fixtures" / "nisolo"
CACHE = NISOLO / "perception-cache"
MODEL = "gpt-4o-mini"

SALE_CREATIVE = 2000103        # "Up to 40% Off — our biggest sale of the year"
SALE_PRODUCT = 3000101         # Huarache Sandal 2.0 (Women's), $109


def creatives() -> list[dict]:
    return json.loads((NISOLO / "creatives.json").read_text())["creatives"]


def products() -> dict[int, dict]:
    with (NISOLO / "catalog.csv").open() as fh:
        return {int(r["product_id"]): r for r in csv.DictReader(fh)}


def cached(cr: dict):
    image_sha = hashlib.sha256((NISOLO / cr["image"]).read_bytes()).hexdigest()
    descriptor = descriptor_for(cr, image_sha256=image_sha)
    key = stimulus_hash(descriptor, IMAGE_PROMPT_VERSION, MODEL)
    return key, cache_load(CACHE, cr["creative_id"], key)


# -- the frozen cache -------------------------------------------------------


def test_every_creative_has_a_committed_image_perception():
    """Law 13: the committed key is recomputable from the fixture alone. A
    re-encoded image or edited copy changes the descriptor and orphans the
    entry, which must fail loudly rather than silently re-perceive."""
    for cr in creatives():
        key, entry = cached(cr)
        assert entry is not None, (
            f"creative {cr['creative_id']} has no cache entry at key {key[:16]} — "
            "re-run: python -m shopsim.experiments perceive-catalog "
            "--catalog fixtures/nisolo --cache fixtures/nisolo/perception-cache")
        assert entry["prompt_version"] == IMAGE_PROMPT_VERSION
        assert entry["model"] == MODEL
        assert entry["descriptor"]["image_sha256"], "an image ad must key on its bytes"


def test_perceiving_again_makes_zero_live_calls():
    def boom(*_a, **_k):  # noqa: ANN002, ANN003
        raise AssertionError("perception must be frozen — no live call at test time")

    perceived, calls = perceive_catalog(NISOLO, CACHE, model=MODEL, call=boom)
    assert calls == 0
    assert set(perceived) == {c["creative_id"] for c in creatives()}


# -- the exhibit: the discount came from the image --------------------------


def test_sale_creative_discount_was_perceived_not_authored():
    """The whole demo beat. creatives.json authors claimed_pct 0.0 for the
    sale ad; the ~40% that actually drives offer_attractiveness has to come
    from the model reading the creative."""
    cr = next(c for c in creatives() if c["creative_id"] == SALE_CREATIVE)

    authored = {o["product_id"]: o["claimed_pct"] for o in cr["offers"]}
    assert authored[SALE_PRODUCT] == 0.0, "the fixture must not author the discount"

    _key, entry = cached(cr)
    perceived = {d["product_id"]: d["claimed_pct"]
                 for d in entry["output"]["claimed_discounts"]}
    assert perceived.get(SALE_PRODUCT, 0.0) >= 0.35, (
        f"expected the eye to read ~40% off the creative, got {perceived}")
    assert entry["prompt_version"] == IMAGE_PROMPT_VERSION  # i.e. from the image

    concepts = {c["concept"] for c in entry["output"]["claims"]}
    assert "DISCOUNT" in concepts


def test_perceived_claims_reach_the_objective_view():
    """Perception overrides authored claims in ObjectiveView, so what the
    model read is what the simulation actually reacts to."""
    from shopsim.minds.objective_view import ObjectiveView

    perceived, calls = perceive_catalog(NISOLO, CACHE, model=MODEL,
                                        call=lambda *a, **k: pytest.fail("frozen"))
    assert calls == 0
    view = ObjectiveView.from_catalog(
        NISOLO,
        perceived_claims={cid: p.claims_dict for cid, p in perceived.items()},
        perceived_offers={cid: p.offers_dict for cid, p in perceived.items()})
    facts = view.facts(SALE_CREATIVE)
    assert facts is not None
    assert facts.max_claimed_pct >= 0.35, (
        "the perceived discount must survive into StimulusFacts — this is the "
        "value appraisal.py turns into offer_attractiveness")
    assert Concept.DISCOUNT.value in facts.claims


# -- catalog coherence ------------------------------------------------------


def test_every_offered_product_has_a_landing_page():
    """A creative whose product has no page dead-ends at CLICK; in a shared
    market it still wins impressions on CTR while earning zero revenue."""
    pages = json.loads((NISOLO / "page_variants.json").read_text())["page_variants"]
    have = {p["product_id"] for p in pages}
    for cr in creatives():
        for offer in cr["offers"]:
            assert offer["product_id"] in have, (
                f"creative {cr['creative_id']} offers {offer['product_id']} "
                "which has no landing page")


def test_each_creative_offers_exactly_one_product():
    """resolve_pages sends a creative to the page of its LOWEST offered
    product id, so a multi-offer ad can land somewhere unintended. One
    product per ad keeps the intent unambiguous."""
    for cr in creatives():
        assert len(cr["offers"]) == 1, cr["creative_id"]


def test_ids_and_vocabulary_stay_inside_the_contract():
    prods = products()
    for pid, row in prods.items():
        assert 3_000_000 <= pid < 4_000_000
        assert int(row["brand_id"]) >= 6_000
        Category(int(row["category_id"]))                      # closed enum
        for c in row["attr_concept_ids"].split("|"):
            Concept(int(c))                                    # closed enum
        assert float(row["list_price"]) > 0

    for cr in creatives():
        assert 2_000_000 <= cr["creative_id"] < 3_000_000
        for claim in cr["claims"]:
            Concept(claim["concept_id"])
        for offer in cr["offers"]:
            assert offer["product_id"] in prods

    pages = json.loads((NISOLO / "page_variants.json").read_text())["page_variants"]
    for p in pages:
        assert 4_000_000 <= p["page_id"] < 5_000_000
        assert p["product_id"] in prods
        for c in p["shows_concept_ids"]:
            Concept(int(c))


def test_latent_quality_columns_match_the_hygiene_contract():
    with (NISOLO / "latent_quality.csv").open() as fh:
        reader = csv.DictReader(fh)
        assert set(reader.fieldnames or []) == {
            "product_id", "latent_quality", "ship_reliability"}
        rows = list(reader)
    assert {int(r["product_id"]) for r in rows} == set(products())
    for r in rows:
        assert 0.0 <= float(r["latent_quality"]) <= 1.0
        assert 0.0 <= float(r["ship_reliability"]) <= 1.0


# -- premium calibration ----------------------------------------------------


def test_budgets_clear_the_catalog_without_erasing_price_pressure():
    """Nisolo is $109-295 against value-tier budgets of $90-180, so budgets
    had to rise or `price > budget_left` blocks nearly every purchase. But if
    they rise too far, price stops discriminating and the ladder means
    nothing: the deal-driven segments must still be priced out of the top."""
    segs = json.loads((NISOLO / "personas.json").read_text())["segments"]
    budgets = {s["name"]: s["coeffs"]["budget"][0] for s in segs}
    prices = [float(r["list_price"]) for r in products().values()]
    cheapest, dearest = min(prices), max(prices)

    assert min(budgets.values()) > cheapest, "nobody could buy the entry product"
    for name in ("deal_stacker", "bargain_hunter"):
        assert budgets[name] < dearest, f"{name} should be priced out of the top item"
    assert budgets["quality_investor"] > dearest, "somebody must afford the tote"


def test_needs_only_arrive_in_categories_nisolo_sells():
    """A need in a category with no products can never convert. demo-brand's
    rates are running-shoe heavy (5504) and Nisolo sells none."""
    goals = json.loads((NISOLO / "goal_config.json").read_text())
    sold = {int(r["category_id"]) for r in products().values()}
    for seg, rates in goals["arrival_rates_per_tick"].items():
        for cat in rates:
            assert int(cat) in sold, f"segment {seg} wants {cat}, which Nisolo does not sell"

    caps = goals["need_defaults"]["budget_cap_by_category"]
    for cat in sold:
        floor = min(float(r["list_price"]) for r in products().values()
                    if int(r["category_id"]) == cat)
        assert float(caps[str(cat)]) >= floor, (
            f"budget_cap for {cat} sits under its cheapest product — every buy "
            "in it would take the x0.25 damp")


@pytest.mark.parametrize("name", [
    "catalog.csv", "creatives.json", "page_variants.json", "latent_quality.csv",
    "personas.json", "goal_config.json", "promo_schedule.json", "README.md",
])
def test_fixture_is_complete(name):
    assert (NISOLO / name).exists()
