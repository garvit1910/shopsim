"""Perception as graph writer (Phase 2.2): the perceived stimulus facts land
in the objective layer through the existing whitelisted Cypher templates.

In engine runs the split is (agreed 2026-08-17, CONTRACT v3.2 note pending):

    ingest_catalog(..., include_stimuli=False)   products/categories/HAS_ATTR/
                                                 prices/latent/LISTS — catalog truth
    write_stimuli(...)                           CLAIMS{strength}/PROMOTES/
                                                 OFFERS{claimed_pct}/SHOWS/PAGE_FOR
                                                 — from the perception cache

HAS_ATTR and IN_CATEGORY always come from the catalog CSV, never the LLM.
Page SHOWS is a validated pass-through of the authored concept lists (pages
have no prose). All writes are MERGE — idempotent per (edge, props).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from ..contracts.enums import Concept
from ..hydramem import cypher, schema
from ..hydramem.client import HydraClient, Statement
from .schema import PerceivedCreative


def stimulus_statements(
    demo_brand_dir: Path | str, perceived: dict[int, PerceivedCreative]
) -> list[Statement]:
    d = Path(demo_brand_dir)
    stmts: list[Statement] = []

    creatives = json.loads((d / "creatives.json").read_text())["creatives"]
    for cr in creatives:
        cid = cr["creative_id"]
        p = perceived.get(cid)
        if p is None:
            raise KeyError(f"no perception for creative {cid} — perceive first")
        stmts.append(cypher.set_node_props("creative", cid, {"brand_id": cr["brand_id"]}))
        stmts.append(cypher.create_edge("LISTS", schema.CATALOG_ID, cid, merge=True))
        # PROMOTES comes from the descriptor (objective linkage), claims and
        # claimed_pct from perception
        stmts.append(cypher.create_edge("PROMOTES", cid, cr["brand_id"], merge=True))
        for concept_id, strength in p.claims:
            stmts.append(cypher.create_edge("CLAIMS", cid, concept_id,
                                            {"strength": strength}, merge=True))
        for product_id, claimed_pct in p.offers:
            stmts.append(cypher.create_edge("OFFERS", cid, product_id,
                                            {"claimed_pct": claimed_pct}, merge=True))

    product_brand: dict[int, int] = {}
    with open(d / "catalog.csv", newline="") as fh:
        for row in csv.DictReader(fh):
            product_brand[int(row["product_id"])] = int(row["brand_id"])

    valid_concepts = {int(c) for c in Concept}
    pages = json.loads((d / "page_variants.json").read_text())["page_variants"]
    for pg in pages:
        pgid = pg["page_id"]
        prod = pg["product_id"]
        shows = [int(c) for c in pg["shows_concept_ids"]]
        bad = [c for c in shows if c not in valid_concepts]
        if bad:
            raise ValueError(f"page {pgid} SHOWS unknown concepts {bad} (Law 11)")
        stmts.append(cypher.set_node_props("page", pgid, {
            "brand_id": product_brand.get(prod, 0), "product_id": prod}))
        stmts.append(cypher.create_edge("LISTS", schema.CATALOG_ID, pgid, merge=True))
        stmts.append(cypher.create_edge("PAGE_FOR", pgid, prod, merge=True))
        for concept_id in shows:
            stmts.append(cypher.create_edge("SHOWS", pgid, concept_id, merge=True))
    return stmts


def write_stimuli(
    client: HydraClient,
    demo_brand_dir: Path | str,
    perceived: dict[int, PerceivedCreative],
) -> int:
    stmts = stimulus_statements(demo_brand_dir, perceived)
    client.run_seq(stmts)
    return len(stmts)
