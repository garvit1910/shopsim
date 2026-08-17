"""The tick-step generators: goals, exposure, fulfillment, promo.

Every random draw comes from a substream keyed by a stable tuple (Law 13);
all "shopper" keys are block OFFSETS, not shopper ids, so the same seed
produces the same trajectory in any run block (CONTRACT v3.3):

    goals      (seed, "goal",   offset, tick)
    exposure   (seed, "expose", offset, tick)
    decide     (seed, "decide", offset, tick, stimulus_id)   [used in loop.py]
    fulfil     (seed, "fulfil", offset, product, purchase_t)

Law 15: latent_quality.csv is read HERE (fulfillment satisfaction only) and
never enters a DecisionContext or any mind input.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..contracts.enums import EventType
from ..contracts.ids import shopper_offset
from ..contracts.types import Event
from ..hydramem import cypher, schema
from ..hydramem.client import Statement

GOAL_STREAM = int.from_bytes(b"goal", "big")
EXPOSE_STREAM = int.from_bytes(b"expose", "big")
DECIDE_STREAM = int.from_bytes(b"decide", "big")
FULFIL_STREAM = int.from_bytes(b"fulfil", "big")
PAGE_STREAM = int.from_bytes(b"page", "big")  # CONTRACT v3.4-draft: A/B split

SENT = schema.VALID_TO_SENTINEL


def substream(seed: int, stream: int, *key: int) -> np.random.Generator:
    return np.random.default_rng(np.random.SeedSequence((seed, stream, *key)))


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


# ---------------------------------------------------------------------------
# goals (tick step 0)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScriptedNeed:
    offset: int  # remapped from the config's block-0 shopper id (CONTRACT v3.3)
    category: int
    activate_tick: int
    strength: float
    budget_cap: float
    deadline_tick: int


@dataclass(frozen=True)
class GoalConfig:
    arrival_rates: dict[int, dict[int, float]]  # segment -> category -> rate/tick
    strength_range: tuple[float, float]
    deadline_ticks_range: tuple[int, int]
    budget_caps: dict[int, float]  # category -> cap
    waves: tuple[dict, ...]
    scripted: tuple[ScriptedNeed, ...]

    @classmethod
    def load(cls, path: Path | str) -> "GoalConfig":
        raw = json.loads(Path(path).read_text())
        nd = raw["need_defaults"]
        return cls(
            arrival_rates={
                int(seg): {int(cat): float(r) for cat, r in rates.items()}
                for seg, rates in raw["arrival_rates_per_tick"].items()
            },
            strength_range=(float(nd["strength_range"][0]), float(nd["strength_range"][1])),
            deadline_ticks_range=(int(nd["deadline_ticks_range"][0]),
                                  int(nd["deadline_ticks_range"][1])),
            budget_caps={int(c): float(v) for c, v in nd["budget_cap_by_category"].items()},
            waves=tuple(raw.get("waves", ())),
            scripted=tuple(
                ScriptedNeed(
                    offset=shopper_offset(int(s["shopper_id"])),
                    category=int(s["category_id"]),
                    activate_tick=int(s["activate_tick"]),
                    strength=float(s["strength"]),
                    budget_cap=float(s["budget_cap"]),
                    deadline_tick=int(s["deadline_tick"]),
                )
                for s in raw.get("scripted", ())
            ),
        )

    def wave_multiplier(self, category: int, tick: int, enabled: bool) -> float:
        if not enabled:
            return 1.0
        m = 1.0
        for w in self.waves:
            if int(w["category_id"]) == category and w["start_tick"] <= tick <= w["end_tick"]:
                m *= float(w["rate_multiplier"])
        return m


def _overlay_multiplier(goal_cfg: "GoalConfig", cat: int, tick: int,
                        extra_waves: tuple[dict, ...],
                        wave_scale: float | None) -> float:
    """Scenario-pack wave arithmetic (CONTRACT v3.4-draft): the configured
    waves plus overlay waves, each damped/amplified toward baseline by
    wave_scale (m *= 1 + (rm - 1)·scale; scale 1.0 = as configured, 0.0 =
    waves neutralized). Called only when an overlay key is present AND waves
    are enabled — the default path never enters here."""
    scale = 1.0 if wave_scale is None else float(wave_scale)
    m = 1.0
    for w in (*goal_cfg.waves, *extra_waves):
        if int(w["category_id"]) == cat and w["start_tick"] <= tick <= w["end_tick"]:
            m *= 1.0 + (float(w["rate_multiplier"]) - 1.0) * scale
    return m


@dataclass
class GoalState:
    """Live needs in memory: (offset, category) -> (deadline_t, activated_tick).
    Rebuilt from the JSONL on resume/branch — never persisted separately."""

    live: dict[tuple[int, int], tuple[int, int]] = field(default_factory=dict)

    def apply_record(self, rec: dict, t0: int, tick_seconds: int) -> None:
        key = (shopper_offset(rec["shopper_id"]), rec["subject"])
        if rec["type"] == EventType.NEED_ACTIVATED.value:
            tick = (rec["t"] - t0) // tick_seconds
            self.live[key] = (rec["deadline_t"], tick)
        elif rec["type"] in (EventType.NEED_EXPIRED.value, EventType.NEED_SATISFIED.value):
            self.live.pop(key, None)


def goal_step(
    *,
    seed: int,
    tick: int,
    now: int,
    t0: int,
    tick_seconds: int,
    run: int,
    goal_cfg: GoalConfig,
    overrides: dict,
    state: GoalState,
    segment_by_offset: dict[int, int],
    sid_of,  # offset -> shopper id in the active block
) -> tuple[list[Event], dict[int, list[Statement]]]:
    """Expiry, seeded arrivals, scripted overrides — in that canonical order.
    Returns (log records as Events, graph statements grouped by shopper)."""
    events: list[Event] = []
    stmts: dict[int, list[Statement]] = {}

    def add_stmt(offset: int, stmt: Statement) -> None:
        stmts.setdefault(sid_of(offset), []).append(stmt)

    def close(offset: int, cat: int) -> None:
        sid = sid_of(offset)
        events.append(Event(EventType.NEED_EXPIRED, sid, now, run, cat))
        add_stmt(offset, cypher.supersede_edge("NEEDS", sid, cat, now, {
            "closed_cause_kind": EventType.NEED_EXPIRED.value, "closed_cause_id": 0}))
        del state.live[(offset, cat)]

    def activate(offset: int, cat: int, strength: float, cap: float,
                 deadline_t: int, source: str) -> None:
        sid = sid_of(offset)
        events.append(Event(EventType.NEED_ACTIVATED, sid, now, run, cat, props=(
            ("strength", strength), ("budget_cap", cap),
            ("deadline_t", deadline_t), ("source", source))))
        add_stmt(offset, cypher.create_edge("NEEDS", sid, cat, {
            "strength": strength, "budget_cap": cap, "deadline_t": deadline_t,
            "t": now, "valid_to": SENT, "source": source}))
        state.live[(offset, cat)] = (deadline_t, tick)

    # 1. expiry (deadline_t <= now at the start of the tick)
    for (offset, cat), (deadline_t, _) in sorted(state.live.items()):
        if deadline_t <= now:
            close(offset, cat)

    # 2. seeded Bernoulli arrivals (skip-if-live per category; the arrival
    # draw happens regardless so the stream shape is state-independent)
    waves_on = bool(overrides.get("waves_enabled", True))
    # scenario overlays (CONTRACT v3.4-draft): with neither key present the
    # rate arithmetic below is the byte-identical Phase-3 path (no extra
    # float ops on the default branch)
    extra_waves = tuple(overrides.get("extra_waves") or ())
    wave_scale = overrides.get("wave_scale")
    has_overlay = bool(extra_waves) or wave_scale is not None
    lo_d, hi_d = goal_cfg.deadline_ticks_range
    lo_s, hi_s = goal_cfg.strength_range
    for offset in sorted(segment_by_offset):
        rates = goal_cfg.arrival_rates.get(segment_by_offset[offset])
        if not rates:
            continue
        rng = substream(seed, GOAL_STREAM, offset, tick)
        for cat in sorted(rates):
            u = rng.random()
            if has_overlay and waves_on:
                rate = rates[cat] * _overlay_multiplier(
                    goal_cfg, cat, tick, extra_waves, wave_scale)
            else:
                rate = rates[cat] * goal_cfg.wave_multiplier(cat, tick, waves_on)
            if u >= rate or (offset, cat) in state.live:
                continue
            strength = round(lo_s + (hi_s - lo_s) * rng.random(), 4)
            deadline_ticks = int(rng.integers(lo_d, hi_d + 1))
            activate(offset, cat, strength, goal_cfg.budget_caps.get(cat, 0.0),
                     now + deadline_ticks * tick_seconds, "seeded")

    # 3. scripted overrides (scripted wins: a live seeded need is closed first)
    if bool(overrides.get("scripted_enabled", True)):
        for s in goal_cfg.scripted:
            if s.activate_tick != tick or s.offset not in segment_by_offset:
                continue
            if (s.offset, s.category) in state.live:
                close(s.offset, s.category)
            activate(s.offset, s.category, s.strength, s.budget_cap,
                     t0 + s.deadline_tick * tick_seconds, "scripted")

    return events, stmts


# ---------------------------------------------------------------------------
# exposure (tick step 2)
# ---------------------------------------------------------------------------


@dataclass
class SawHistory:
    """In-memory SAW history for frequency capping: offset -> [(tick, creative)].
    Rebuilt from the JSONL on resume/branch."""

    seen: dict[int, list[tuple[int, int]]] = field(default_factory=dict)

    def record(self, offset: int, tick: int, creative: int) -> None:
        self.seen.setdefault(offset, []).append((tick, creative))

    def count_tick(self, offset: int, tick: int) -> int:
        return sum(1 for tk, _ in self.seen.get(offset, ()) if tk == tick)

    def count_72h(self, offset: int, tick: int) -> int:
        return sum(1 for tk, _ in self.seen.get(offset, ()) if tick - 2 <= tk <= tick)


def exposure_step(
    *,
    seed: int,
    tick: int,
    schedule,  # tuple[ScheduleRow, ...] (already sorted by creative_id)
    offsets: list[int],
    cap_per_tick: int,
    cap_72h: int,
    saw: SawHistory,
    segment_by_offset: dict[int, int] | None = None,
) -> dict[int, list[int]]:
    """Seeded Bernoulli reach per (shopper, scheduled creative) with frequency
    caps. Returns creative_id -> sorted exposed offsets. Records into `saw`.

    Audience targeting (CONTRACT v3.4-draft): a row's audience_segments filters
    AFTER the reach draw — the stream shape stays state- and audience-
    independent, exactly like the goal step's skip-if-live rule. Filtered
    exposures consume no caps and emit no SAW."""
    active_rows = [r for r in schedule if r.start_tick <= tick <= r.end_tick]
    # getattr: Phase-3-shaped row objects (no audience field) keep working
    audiences = [getattr(r, "audience_segments", None) for r in active_rows]
    if segment_by_offset is None and any(a is not None for a in audiences):
        raise ValueError("schedule rows carry audience_segments but "
                         "exposure_step got no segment_by_offset")
    out: dict[int, list[int]] = {r.creative_id: [] for r in active_rows}
    for offset in sorted(offsets):
        rng = substream(seed, EXPOSE_STREAM, offset, tick)
        for row, audience in zip(active_rows, audiences):
            u = rng.random()  # drawn per active row regardless of caps/audience
            if u >= row.reach_prob:
                continue
            if audience is not None and segment_by_offset[offset] not in audience:
                continue
            if saw.count_tick(offset, tick) >= cap_per_tick:
                continue
            if saw.count_72h(offset, tick) >= cap_72h:
                continue
            out[row.creative_id].append(offset)
            saw.record(offset, tick, row.creative_id)
    return out


def page_for(seed: int, splits: dict[int, tuple[int, ...]], pages: dict[int, int],
             offset: int, creative: int) -> int | None:
    """Landing page for (shopper offset, creative). Split rows (page_ids)
    draw once from (seed, "page", offset, creative) — tick-free, so a
    shopper's variant is stable for the whole run and re-derivable at click
    time, state rebuild, and replay without ever being logged (CONTRACT
    v3.4-draft). Non-split creatives take the static map with ZERO rng draws
    — the byte-identical Phase-3 path."""
    variants = splits.get(creative)
    if not variants:
        return pages.get(creative)
    rng = substream(seed, PAGE_STREAM, offset, creative)
    return variants[int(rng.integers(len(variants)))]


# ---------------------------------------------------------------------------
# fulfillment (tick step 6)
# ---------------------------------------------------------------------------


def load_latent_quality(catalog_dir: Path | str) -> dict[int, float]:
    """Runner-side only (Law 15): satisfaction generation, never retrieval."""
    out: dict[int, float] = {}
    with open(Path(catalog_dir) / "latent_quality.csv", newline="") as fh:
        for row in csv.DictReader(fh):
            out[int(row["product_id"])] = float(row["latent_quality"])
    return out


@dataclass
class FulfillmentQueue:
    """Purchases awaiting delivery: (offset, product, purchase_t, purchase_tick).
    Derived from BOUGHT records — reconstructed from the JSONL, never persisted
    (CONTRACT determinism rules)."""

    pending: list[tuple[int, int, int, int]] = field(default_factory=list)

    def record_bought(self, offset: int, product: int, t: int, tick: int) -> None:
        self.pending.append((offset, product, t, tick))

    def due(self, tick: int, lag_ticks: int) -> list[tuple[int, int, int, int]]:
        hits = [p for p in self.pending if p[3] == tick - lag_ticks]
        return sorted(hits)


def fulfillment_step(
    *,
    seed: int,
    tick: int,
    now: int,
    run: int,
    lag_ticks: int,
    sat_noise_sd: float,
    queue: FulfillmentQueue,
    latent: dict[int, float],
    sid_of,
) -> list[Event]:
    """EXPERIENCED for purchases made at tick - lag:
    sat = clamp01(latent_quality + N(0, sd)), substream keyed on purchase_t."""
    events: list[Event] = []
    for offset, product, purchase_t, _ in queue.due(tick, lag_ticks):
        rng = substream(seed, FULFIL_STREAM, offset, product, purchase_t)
        sat = _clamp01(latent.get(product, 0.5) + float(rng.normal(0.0, sat_noise_sd)))
        events.append(Event(EventType.EXPERIENCED, sid_of(offset), now, run, product,
                            props=(("sat", round(sat, 4)),)))
    return events


# ---------------------------------------------------------------------------
# promo hook (tick step 1)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PromoSchedule:
    # product -> ((start_tick, end_tick, discount_pct), ...)
    windows: dict[int, tuple[tuple[int, int, float], ...]]

    @classmethod
    def from_raw(cls, raw: dict) -> "PromoSchedule":
        """Same shape as promo_schedule.json; inline payloads come from a
        run_config arm's promo_overrides.schedule_inline (CONTRACT v3.4-draft)."""
        return cls(windows={
            int(p["product_id"]): tuple(
                (int(c["start_tick"]), int(c["end_tick"]), float(c["discount_pct"]))
                for c in p["cycles"])
            for p in raw.get("product_promos", ())
        })

    @classmethod
    def load(cls, path: Path | str) -> "PromoSchedule":
        return cls.from_raw(json.loads(Path(path).read_text()))

    def discount_at(self, product: int, tick: int) -> float:
        for start, end, pct in self.windows.get(product, ()):
            if start <= tick <= end:
                return pct
        return 0.0


def promo_step(client, promo: PromoSchedule, list_prices: dict[int, float],
               tick: int, now: int) -> int:
    """Self-healing PRICED_AT alignment: read the as-of-now price for each
    scheduled product; if it differs from the schedule's target, supersede and
    create. Idempotent across arms/branches sharing the objective layer (the
    as-of read finds the version an earlier arm already wrote). Config-derived
    — deliberately not logged; rollback is by timestamp (rollback.py)."""
    writes = 0
    for product in sorted(promo.windows):
        base = list_prices.get(product)
        if base is None:
            continue
        target = round(base * (1.0 - promo.discount_at(product, tick)), 2)
        rows = [r for r in client.run_stmt(cypher.all_edges(
            "PRICED_AT", product, ("price", "t", "valid_to")))
            if r["t"] <= now < r["valid_to"]]
        current = max(rows, key=lambda r: r["t"])["price"] if rows else None
        if current is not None and abs(current - target) < 1e-9:
            continue
        client.run_stmt(cypher.supersede_edge("PRICED_AT", product, schema.PRICEBOOK_ID, now))
        client.run_stmt(cypher.create_edge("PRICED_AT", product, schema.PRICEBOOK_ID, {
            "price": target, "t": now, "valid_to": SENT}))
        writes += 1
    return writes
