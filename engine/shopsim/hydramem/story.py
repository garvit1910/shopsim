"""The scripted story graph (Phase-1 checkpoint fixture).

Seeds the demo-brand catalog plus a cast of shoppers whose ids mirror the
canned context fixtures, so the contract tests can run unchanged against the
real HydraMem (SHOPSIM_HYDRAMEM=real). Every P0 motif has a designed hit AND
a designed miss; abstention is structural (nothing seeded for the unknown-
brand shopper).

Cast (stimulus 2000003 = "EcoStride Sale", brand 6001, claims {5003,5005,5011}):
    1000041  twin, need OFF   PREFERS eco + SAW same-brand eco creative
    1000042  twin, need ON    identical + one NEEDS(5504) edge
    1000043  belief low-conf  trust belief value .60, E .75
    1000044  belief high-conf trust belief value .60, E 6.0 (same value!)
    1000045  fatigue          3x SAW eco story + 2x SAW the stimulus itself;
                              rival SAWs share no concept (designed miss)
    1000046  social           trusts 1000077 who bought + experienced 3000001
    1000047  unknown brand    nothing seeded; served vs stimulus 2000005
    1000049  provenance       trust belief .70/E3.0 "from 2 visits and 1 purchase"
    1000050  violation        EXPECTS DISCOUNT(5011) from 6001; hit vs page
                              4000002 (hides 5011), miss vs page 4000001
    1000051  designed misses  PREFERS style(5017) only + NEEDS casual(5500)
    1000052  golden chain     reserved for the golden-chain test (it seeds
                              its own prior and drives the applier)
    1000077  the trusted peer
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from . import cypher, schema
from .client import Statement
from .real import HydraMem
from .writes import ingest_catalog

SENT = schema.VALID_TO_SENTINEL

STORY_NOW = 1_755_150_000  # matches the Appendix-B last_seen_t epoch
STORY_TICK = 8
STORY_TICK_START = STORY_NOW - 3_600
DAY = 86_400
H = 3_600

TWIN_OFF, TWIN_ON = 1_000_041, 1_000_042
BELIEF_LOW, BELIEF_HIGH = 1_000_043, 1_000_044
FATIGUE = 1_000_045
SOCIAL = 1_000_046
UNKNOWN = 1_000_047
PROVENANCE = 1_000_049
VIOLATION = 1_000_050
MISSES = 1_000_051
GOLDEN = 1_000_052
PEER = 1_000_077

STIM_AD = 2_000_003  # EcoStride Sale (eco story + DISCOUNT claim)
ECO_AD = 2_000_001  # Planet-First Run (same brand, same eco story)
RIVAL_AD = 2_000_004  # Apex Performance (brand 6002, disjoint claims)
UNKNOWN_AD = 2_000_005  # UrbanStride (never seen by 1000047)
PAGE_OK, PAGE_VIOLATING = 4_000_001, 4_000_002
ECO, LIGHTWEIGHT, DISCOUNT, STYLE = 5_003, 5_005, 5_011, 5_017
RUNNING, CASUAL = 5_504, 5_500
SHOECO = 6_001
PRODUCT = 3_000_001

# fixed belief-node ids (deterministic wipe; inside run-0's belief block,
# far above anything the run-0 allocator hands out in tests)
B_LOW, B_HIGH, B_PROV = 8_900_043, 8_900_044, 8_900_049

ALL_SHOPPERS = (TWIN_OFF, TWIN_ON, BELIEF_LOW, BELIEF_HIGH, FATIGUE, SOCIAL,
                UNKNOWN, PROVENANCE, VIOLATION, MISSES, GOLDEN, PEER)

# name -> (shopper_id, stimulus_id): mirrors MockHydraMem.cases exactly
CASES: dict[str, tuple[int, int]] = {
    "twin-need-off": (TWIN_OFF, STIM_AD),
    "twin-need-on": (TWIN_ON, STIM_AD),
    "belief-low-conf": (BELIEF_LOW, STIM_AD),
    "belief-high-conf": (BELIEF_HIGH, STIM_AD),
    "fatigue-present": (FATIGUE, STIM_AD),
    "social-case": (SOCIAL, STIM_AD),
    "unknown-brand-abstention": (UNKNOWN, UNKNOWN_AD),
}


def _demo_brand_dir() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "fixtures" / "demo-brand"
        if candidate.exists():
            return candidate
    raise FileNotFoundError("fixtures/demo-brand not found above " + __file__)


def _belief(shopper: int, belief_id: int, about: int, value: float, e: float,
            t: int, derived: list[dict] | None = None) -> list[Statement]:
    stmts = [
        cypher.set_node_props("belief", belief_id, {
            "value": value, "evidence": e, "about_id": about,
            "that_id": schema.ASPECT_TRUST_ID, "t": t, "valid_to": SENT}),
        cypher.create_edge("HOLDS", shopper, belief_id, {"t": t, "valid_to": SENT}),
        cypher.create_edge("ABOUT", belief_id, about),
        cypher.create_edge("THAT", belief_id, schema.ASPECT_TRUST_ID),
    ]
    for row in derived or []:
        stmts.append(cypher.create_edge("DERIVED_FROM", belief_id, row["target"], {
            "kind": row["kind"], "count": row["count"], "first_t": row["first_t"],
            "last_t": row["last_t"], "weight": row["weight"]}))
    return stmts


def _prefers(s: int, concept: int, w: float, e: float, t: int,
             source: str = "learned", ck: str = "CLICKED", cid: int = ECO_AD) -> Statement:
    return cypher.create_edge("PREFERS", s, concept, {
        "w": w, "evidence": e, "source": source, "cause_kind": ck,
        "cause_id": cid, "t": t, "valid_to": SENT})


def _saw(s: int, creative: int, t: int) -> Statement:
    return cypher.create_edge("SAW", s, creative, {"t": t, "run": 0})


def _seed_statements() -> list[Statement]:
    now = STORY_NOW
    stmts: list[Statement] = []

    # shopper node props
    for s in ALL_SHOPPERS:
        stmts.append(cypher.set_node_props("shopper", s, {"segment_id": 1001, "budget": 120.0}))

    # twins: identical outside the NEEDS edge
    for s in (TWIN_OFF, TWIN_ON):
        stmts.append(_prefers(s, ECO, 0.61, 2.85, now - 1 * DAY))
        stmts.append(_saw(s, ECO_AD, now - 2 * DAY))
        stmts.append(cypher.create_edge("REFERENCE_PRICE", s, PRODUCT, {
            "price": 39.0, "t": now - 2 * DAY, "valid_to": SENT}))
    stmts.append(cypher.create_edge("NEEDS", TWIN_ON, RUNNING, {
        "strength": 0.8, "budget_cap": 90.0, "deadline_t": now + 2 * DAY,
        "t": now - 6 * H, "valid_to": SENT, "source": "scripted"}))

    # belief pair: same value, different evidence mass
    stmts += _belief(BELIEF_LOW, B_LOW, SHOECO, 0.60, 0.75, now - 1 * DAY)
    stmts += _belief(BELIEF_HIGH, B_HIGH, SHOECO, 0.60, 6.0, now - 1 * DAY)

    # fatigue: same-brand same-story repetition + the designed rival miss
    for t in (now - 1 * DAY, now - 2 * DAY, now - 3 * DAY):
        stmts.append(_saw(FATIGUE, ECO_AD, t))
    stmts.append(_saw(FATIGUE, STIM_AD, now - 1 * H))
    stmts.append(_saw(FATIGUE, STIM_AD, now - 30 * H))
    stmts.append(_saw(FATIGUE, RIVAL_AD, now - 1 * DAY))
    stmts.append(_saw(FATIGUE, RIVAL_AD, now - 2 * DAY))

    # social: a trusted peer who bought and lived with the product
    stmts.append(cypher.create_edge("TRUSTS_PERSON", SOCIAL, PEER, {"w": 0.7}))
    stmts.append(cypher.create_edge("BOUGHT", PEER, PRODUCT, {
        "t": now - 2 * DAY, "run": 0, "price": 39.0}))
    stmts.append(cypher.create_edge("EXPERIENCED", PEER, PRODUCT, {
        "t": now - 1 * DAY, "run": 0, "sat": 0.9}))

    # provenance: "value 0.70, confidence 0.81 — from 2 visits and 1 purchase"
    stmts += _belief(PROVENANCE, B_PROV, SHOECO, 0.70, 3.0, now - 1 * DAY, derived=[
        {"kind": "VISITED", "target": PAGE_OK, "count": 2,
         "first_t": now - 3 * DAY, "last_t": now - 2 * DAY, "weight": 1.5},
        {"kind": "BOUGHT", "target": PRODUCT, "count": 1,
         "first_t": now - 2 * DAY, "last_t": now - 2 * DAY, "weight": 1.5},
    ])

    # violation: the ad promised DISCOUNT; page 4000002 hides it
    stmts.append(cypher.create_edge("EXPECTS", VIOLATION, DISCOUNT, {
        "about": SHOECO, "strength": 0.9, "t": now - 1 * DAY, "valid_to": SENT,
        "cause_id": STIM_AD}))
    stmts.append(_saw(VIOLATION, STIM_AD, now - 1 * DAY))

    # designed misses: preference and goal both present but disjoint
    stmts.append(_prefers(MISSES, STYLE, 0.8, 2.0, now - 1 * DAY, source="prior",
                          ck="SEED", cid=0))
    stmts.append(cypher.create_edge("NEEDS", MISSES, CASUAL, {
        "strength": 0.7, "budget_cap": 60.0, "deadline_t": now + 3 * DAY,
        "t": now - 1 * DAY, "valid_to": SENT, "source": "seeded"}))

    return stmts


# every (rel, a, b) pair the seeder creates — the wipe deletes exactly these
def _seeded_edge_pairs() -> list[tuple[str, int, int]]:
    pairs: list[tuple[str, int, int]] = []
    for s in (TWIN_OFF, TWIN_ON):
        pairs += [("PREFERS", s, ECO), ("SAW", s, ECO_AD), ("REFERENCE_PRICE", s, PRODUCT)]
    pairs.append(("NEEDS", TWIN_ON, RUNNING))
    for s, b in ((BELIEF_LOW, B_LOW), (BELIEF_HIGH, B_HIGH), (PROVENANCE, B_PROV)):
        pairs += [("HOLDS", s, b), ("ABOUT", b, SHOECO),
                  ("THAT", b, schema.ASPECT_TRUST_ID)]
    pairs += [("DERIVED_FROM", B_PROV, PAGE_OK), ("DERIVED_FROM", B_PROV, PRODUCT)]
    pairs += [("SAW", FATIGUE, ECO_AD), ("SAW", FATIGUE, STIM_AD), ("SAW", FATIGUE, RIVAL_AD)]
    pairs += [("TRUSTS_PERSON", SOCIAL, PEER), ("BOUGHT", PEER, PRODUCT),
              ("EXPERIENCED", PEER, PRODUCT)]
    pairs += [("EXPECTS", VIOLATION, DISCOUNT), ("SAW", VIOLATION, STIM_AD)]
    pairs += [("PREFERS", MISSES, STYLE), ("NEEDS", MISSES, CASUAL)]
    # anything the golden-chain test wrote for its dedicated shopper
    pairs += [("PREFERS", GOLDEN, ECO)]
    return pairs


def story_hash() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:16]


def is_seeded(mem: HydraMem) -> bool:
    rows = mem.client.run_stmt(cypher.node_props("marker", schema.STORY_MARKER_ID,
                                                 ("seeded_hash",)))
    return bool(rows) and rows[0].get("seeded_hash") == story_hash()


def wipe(mem: HydraMem) -> None:
    for rel, a, b in _seeded_edge_pairs():
        mem.client.run_stmt(cypher.delete_edge(rel, a, b))
    mem.client.run_stmt(cypher.set_node_props("marker", schema.STORY_MARKER_ID,
                                              {"seeded_hash": "wiped"}))


def seed(mem: HydraMem, demo_brand_dir: Path | None = None) -> None:
    """Wipe + reseed the story graph and the demo-brand catalog."""
    wipe(mem)
    ingest_catalog(mem.client, demo_brand_dir or _demo_brand_dir(), now=0)
    mem.client.run_seq(_seed_statements())
    mem.client.run_stmt(cypher.set_node_props("marker", schema.STORY_MARKER_ID,
                                              {"seeded_hash": story_hash()}))
    mem.cache._built_at = None


def ensure_seeded(mem: HydraMem, demo_brand_dir: Path | None = None) -> None:
    """Seed once per story.py content hash; cheap no-op when already clean."""
    if not is_seeded(mem):
        seed(mem, demo_brand_dir)
    mem.set_tick(tick=STORY_TICK, now=STORY_NOW, tick_start=STORY_TICK_START)
