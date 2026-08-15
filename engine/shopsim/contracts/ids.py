"""ID allocation map (Appendix A). Integer ids only; patterns anchor on id.

Run isolation lives in the shopper block: shopper_id = 1_000_000 + run_index *
100_000 + offset. TRUSTS_PERSON edges stay within a run's block. Belief nodes
get a fresh id per version, allocated from a per-run block.
"""

from __future__ import annotations

SEGMENT_BASE = 1_000

CONCEPT_MIN, CONCEPT_MAX = 5_000, 5_499
CATEGORY_MIN, CATEGORY_MAX = 5_500, 5_999

BRAND_BASE = 6_000
DEMO_BRAND_ID = 6_001  # ShoeCo
RIVAL_BRAND_IDS = (6_002, 6_003)  # TrailForge, UrbanStride

SHOPPER_BASE = 1_000_000
SHOPPER_RUN_BLOCK = 100_000

CREATIVE_BASE = 2_000_000
PRODUCT_BASE = 3_000_000  # latent props unretrievable (Law 15)
PAGE_VARIANT_BASE = 4_000_000

BELIEF_BASE = 8_000_000
BELIEF_RUN_BLOCK = 1_000_000  # new id per belief version, per-run block


def shopper_id(run_index: int, offset: int) -> int:
    if not 0 <= offset < SHOPPER_RUN_BLOCK:
        raise ValueError(f"shopper offset {offset} outside run block [0, {SHOPPER_RUN_BLOCK})")
    if run_index < 0:
        raise ValueError(f"run_index must be >= 0, got {run_index}")
    return SHOPPER_BASE + run_index * SHOPPER_RUN_BLOCK + offset


def shopper_run(sid: int) -> int:
    return (sid - SHOPPER_BASE) // SHOPPER_RUN_BLOCK


def shopper_offset(sid: int) -> int:
    return (sid - SHOPPER_BASE) % SHOPPER_RUN_BLOCK


def belief_id(run_index: int, offset: int) -> int:
    if not 0 <= offset < BELIEF_RUN_BLOCK:
        raise ValueError(f"belief offset {offset} outside run block [0, {BELIEF_RUN_BLOCK})")
    return BELIEF_BASE + run_index * BELIEF_RUN_BLOCK + offset


class IdAllocator:
    """Sequential allocator for one run. The engine process is the single
    writer (constraint 8), so a plain in-process counter is sufficient."""

    def __init__(self, run_index: int = 0):
        self.run_index = run_index
        self._counters = {
            "shopper": 0,
            "belief": 0,
            "creative": 0,
            "product": 0,
            "page_variant": 0,
            "segment": 0,
        }

    def _next(self, kind: str) -> int:
        n = self._counters[kind]
        self._counters[kind] = n + 1
        return n

    def next_shopper(self) -> int:
        return shopper_id(self.run_index, self._next("shopper"))

    def next_belief(self) -> int:
        return belief_id(self.run_index, self._next("belief"))

    def next_creative(self) -> int:
        return CREATIVE_BASE + 1 + self._next("creative")

    def next_product(self) -> int:
        return PRODUCT_BASE + 1 + self._next("product")

    def next_page_variant(self) -> int:
        return PAGE_VARIANT_BASE + 1 + self._next("page_variant")

    def next_segment(self) -> int:
        return SEGMENT_BASE + 1 + self._next("segment")
