"""ObjectiveView — the frozen slice of objective/stimulus truth a mind is
constructed with (Phase 2, agreed 2026-08-17; CONTRACT v3.2 note pending).

C1's DecisionContext deliberately carries only shopper-side state. Stimulus-
side objective facts (claims, claimed_pct, SHOWS) and catalog truth (HAS_ATTR,
SOLD_BY, IN_CATEGORY) enter the mind exactly once, here, at construction:

    FormulaMind(view=ObjectiveView...)   # engine/runner builds the view

appraise()/decide()/consolidate() stay pure: the view is frozen, built from
hashed inputs (perception cache + catalog files), so same inputs => same
outputs holds across the whole mind.

Law 15: this module reads catalog.csv / creatives.json / page_variants.json /
the perception cache only — never latent_quality.csv. Latent props cannot
enter a view.

Claims come from the perception cache when one is supplied (perception is the
graph writer for CLAIMS/OFFERS in engine runs); the authored creatives.json
claims are the fallback for fixture-driven tests and the golden targets
perception is tested against.
"""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class StimulusFacts:
    """One stimulus's objective slice (mirrors hydramem.reads.StimulusView)."""

    stimulus_id: int
    kind: str  # "creative" | "page"
    brand_id: int
    claims: dict[int, float] = field(default_factory=dict)  # concept -> strength
    offers: dict[int, float] = field(default_factory=dict)  # product -> claimed_pct
    shows: frozenset[int] = frozenset()  # page concepts
    products: dict[int, int] = field(default_factory=dict)  # product -> category

    @property
    def max_claimed_pct(self) -> float:
        """The headline perceived deal for this stimulus (0.0 = no offer)."""
        return max(self.offers.values(), default=0.0)


@dataclass(frozen=True)
class ObjectiveView:
    stimuli: dict[int, StimulusFacts]
    product_attrs: dict[int, frozenset[int]]  # HAS_ATTR (catalog truth, never LLM)
    product_brand: dict[int, int]  # SOLD_BY
    product_category: dict[int, int]  # IN_CATEGORY

    def facts(self, stimulus_id: int) -> StimulusFacts | None:
        return self.stimuli.get(stimulus_id)

    def view_hash(self) -> str:
        """Canonical content hash (rides in the run manifest alongside the
        perception-cache hash)."""
        payload = {
            "stimuli": {
                str(sid): {
                    "kind": f.kind,
                    "brand": f.brand_id,
                    "claims": {str(k): v for k, v in sorted(f.claims.items())},
                    "offers": {str(k): v for k, v in sorted(f.offers.items())},
                    "shows": sorted(f.shows),
                    "products": {str(k): v for k, v in sorted(f.products.items())},
                }
                for sid, f in sorted(self.stimuli.items())
            },
            "product_attrs": {str(k): sorted(v) for k, v in sorted(self.product_attrs.items())},
            "product_brand": {str(k): v for k, v in sorted(self.product_brand.items())},
            "product_category": {str(k): v for k, v in sorted(self.product_category.items())},
        }
        blob = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        return hashlib.sha256(blob).hexdigest()

    # -- builders -----------------------------------------------------------

    @classmethod
    def from_catalog(
        cls,
        demo_brand_dir: Path | str,
        perceived_claims: Mapping[int, Mapping[int, float]] | None = None,
        perceived_offers: Mapping[int, Mapping[int, float]] | None = None,
    ) -> "ObjectiveView":
        """Build from the fixture files. perceived_* (from the perception
        cache) override the authored creative claims/offers when given."""
        d = Path(demo_brand_dir)

        product_attrs: dict[int, frozenset[int]] = {}
        product_brand: dict[int, int] = {}
        product_category: dict[int, int] = {}
        with open(d / "catalog.csv", newline="") as fh:
            for row in csv.DictReader(fh):
                pid = int(row["product_id"])
                product_brand[pid] = int(row["brand_id"])
                product_category[pid] = int(row["category_id"])
                product_attrs[pid] = frozenset(
                    int(c) for c in row["attr_concept_ids"].split("|")
                )

        stimuli: dict[int, StimulusFacts] = {}
        creatives = json.loads((d / "creatives.json").read_text())["creatives"]
        for cr in creatives:
            cid = cr["creative_id"]
            if perceived_claims is not None and cid in perceived_claims:
                claims = {int(k): float(v) for k, v in perceived_claims[cid].items()}
            else:
                claims = {c["concept_id"]: c["strength"] for c in cr["claims"]}
            if perceived_offers is not None and cid in perceived_offers:
                offers = {int(k): float(v) for k, v in perceived_offers[cid].items()}
            else:
                offers = {o["product_id"]: o["claimed_pct"] for o in cr["offers"]}
            stimuli[cid] = StimulusFacts(
                stimulus_id=cid,
                kind="creative",
                brand_id=cr["brand_id"],
                claims=claims,
                offers=offers,
                products={p: product_category.get(p, 0) for p in offers},
            )

        pages = json.loads((d / "page_variants.json").read_text())["page_variants"]
        for pg in pages:
            prod = pg["product_id"]
            stimuli[pg["page_id"]] = StimulusFacts(
                stimulus_id=pg["page_id"],
                kind="page",
                brand_id=product_brand.get(prod, 0),
                shows=frozenset(pg["shows_concept_ids"]),
                products={prod: product_category.get(prod, 0)},
            )

        return cls(
            stimuli=stimuli,
            product_attrs=product_attrs,
            product_brand=product_brand,
            product_category=product_category,
        )

    @classmethod
    def from_objective_cache(cls, cache) -> "ObjectiveView":
        """Adapt a built hydramem.reads.ObjectiveCache (engine runs against
        the real store). HAS_ATTR is not in the per-tick cache, so it is read
        from the catalog CSV by the caller via from_catalog when EXPERIENCED
        consolidation is in play; this builder covers appraise/decide."""
        stimuli: dict[int, StimulusFacts] = {}
        for cid, meta in cache.creatives.items():
            stimuli[cid] = StimulusFacts(
                stimulus_id=cid,
                kind="creative",
                brand_id=meta["brand"],
                claims=dict(meta["claims"]),
                offers=dict(meta["offers"]),
                products={p: cache.product_category.get(p, 0) for p in meta["offers"]},
            )
        for pgid, meta in cache.pages.items():
            prod = meta["product"]
            stimuli[pgid] = StimulusFacts(
                stimulus_id=pgid,
                kind="page",
                brand_id=meta["brand"],
                shows=frozenset(meta["shows"]),
                products={prod: cache.product_category.get(prod, 0)},
            )
        return cls(
            stimuli=stimuli,
            product_attrs={},
            product_brand=dict(cache.product_brand),
            product_category=dict(cache.product_category),
        )
