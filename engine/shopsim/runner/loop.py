"""SimRunner — the Phase-3 tick loop (PLAN.md Phase 3, steps 0-8 + progress).

Write/marker ordering per tick (crash soundness, CONTRACT v3.3):
  * JSONL records are appended and flushed BEFORE the graph writes of every
    phase, so the log is always a superset of the graph for the partial tick
    (the one exception: the NEED_SATISFIED record follows its supersession,
    but its causing BOUGHT record precedes both — rollback sweeps NEEDS by
    timestamp, so the invariant that matters still holds).
  * Every graph write of tick k carries t == now_k (creates) or
    valid_to == now_k (supersessions): the partial tick is identifiable, and
    rollback.py can undo it by timestamp.
  * The TICK_COMPLETE marker (fsync'd) is written only after all graph writes
    and the results/progress snapshots: last marker == last consistent tick.

Determinism: shoppers iterate sorted by offset; schedule rows by creative_id;
pages by page id; all rng comes from steps.substream keyed on offsets
(CONTRACT v3.3). No wall-clock value reaches events, results, or the manifest.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path

from ..contracts.enums import Action, EventType
from ..contracts.ids import shopper_id as make_sid, shopper_offset
from ..contracts.types import Event
from ..eventlog import JsonlEventLog
from ..hydramem.real import HydraMem
from ..hydramem.writes import ApplyReport, OrderedDelta
from ..minds import FormulaMind, ObjectiveView
from ..minds.scripted import ScriptedMind
from ..perception.cache import perceived_maps
from ..perception.perceive import perceive_catalog
from ..perception.writer import write_stimuli
from ..population.factory import PopulationConfig, generate_population, load_segment_specs, seed_population
from . import steps
from .config import RunConfig
from .expansion import expand_creative, expand_page
from .results import ResultsAccumulator
from .runstore import build_manifest, write_json_atomic
from .steps import (
    DECIDE_STREAM,
    CreativeStats,
    FulfillmentQueue,
    GoalConfig,
    GoalState,
    PromoSchedule,
    SawHistory,
    substream,
)


def _no_llm(*_a, **_k):
    raise RuntimeError("engine runs are offline: perception must come from the cache")


@dataclass
class RunnerState:
    """All in-memory cross-tick state. Everything here is derivable from the
    JSONL log (rebuild_from_records) — nothing is persisted separately."""

    goal: GoalState = field(default_factory=GoalState)
    saw: SawHistory = field(default_factory=SawHistory)
    # offset -> (product, page, cause_creative, carted_tick)
    carts: dict[int, tuple[int, int, int, int]] = field(default_factory=dict)
    fulfil: FulfillmentQueue = field(default_factory=FulfillmentQueue)
    alloc: CreativeStats = field(default_factory=CreativeStats)

    def rebuild_from_records(self, records: list[dict], t0: int, tick_seconds: int,
                             page_of) -> None:
        """page_of(offset, creative) -> page|None — the same pure resolver the
        live loop uses (steps.page_for), so seeded A/B assignments re-derive
        identically on resume (CONTRACT v3.4-draft)."""
        for rec in records:
            rtype = rec.get("type")
            if rtype == "TICK_COMPLETE":
                continue
            if rtype in (EventType.NEED_ACTIVATED.value, EventType.NEED_EXPIRED.value,
                         EventType.NEED_SATISFIED.value):
                self.goal.apply_record(rec, t0, tick_seconds)
                continue
            offset = shopper_offset(rec["shopper_id"])
            tick = (rec["t"] - t0) // tick_seconds
            # allocation weights are a pure function of the SAW/CLICKED log,
            # so resume/branch re-derive the same schedule rescale (v3.6-draft)
            self.alloc.apply_record(rec)
            if rtype == EventType.SAW.value:
                self.saw.record(offset, tick, rec["subject"])
            elif rtype == EventType.CARTED.value:
                cause = rec.get("cause_creative", 0)
                page = page_of(offset, cause) or 0
                self.carts[offset] = (rec["subject"], page, cause, tick)
            elif rtype == EventType.BOUGHT.value:
                self.carts.pop(offset, None)
                self.fulfil.record_bought(offset, rec["subject"], rec["t"], tick)
            elif rtype == EventType.ABANDONED.value:
                self.carts.pop(offset, None)


class CrashRequested(SystemExit):
    pass


class SimRunner:
    def __init__(self, cfg: RunConfig, arm_name: str, run_index: int, run_dir: Path,
                 *, crash_after: str | None = None, quiet: bool = False):
        self.cfg = cfg
        self.arm = cfg.arm(arm_name)
        self.overrides = cfg.goal_overrides(self.arm)
        self.run_index = run_index
        self.run_dir = Path(run_dir)
        self.crash_after = crash_after  # "phase:tick", e.g. "consolidation:7"
        self.quiet = quiet
        self.phase_s: dict[str, float] = {}
        self.mem: HydraMem | None = None
        self.log: JsonlEventLog | None = None

    # -- setup ---------------------------------------------------------------

    def prepare(self, *, seed_graph: bool = True) -> None:
        cfg = self.cfg
        # calibration block (CONTRACT v3.4-draft): absent => the module
        # DEFAULT objects, so populations and minds are byte-identical
        appraisal_params, choice_params, stage_bases = cfg.calibration()
        specs = load_segment_specs(cfg.personas_path)
        self._boot("population")
        self.shoppers = generate_population(PopulationConfig(
            seed=cfg.seed, population_size=cfg.population_size,
            segments=specs, run_index=self.run_index,
            stage_bases=stage_bases))
        self.by_offset = {shopper_offset(s.shopper_id): s for s in self.shoppers}
        self.segment_by_offset = {o: s.segment_id for o, s in self.by_offset.items()}

        self._boot("perception")
        perceived, calls = perceive_catalog(
            cfg.catalog_dir, cache_dir=cfg.perception_cache, call=_no_llm)
        assert calls == 0
        self._perceived = perceived
        claims, offers = perceived_maps(perceived)
        self.view = ObjectiveView.from_catalog(cfg.catalog_dir, claims, offers)
        # per-arm schedule + page resolution (CONTRACT v3.4-draft; no
        # overrides => the shared Phase-3 objects, byte-identical behavior)
        self.schedule = cfg.schedule_for(self.arm)
        self.pages = cfg.resolve_pages(self.view, schedule=self.schedule)
        self.splits = cfg.page_splits(self.schedule)
        for cid, variants in sorted(self.splits.items()):
            for pgid in variants:
                f = self.view.facts(pgid)
                if f is None or f.kind != "page":
                    raise ValueError(
                        f"schedule {cid}: page_ids entry {pgid} is not a known page")
        self.page_of = partial(steps.page_for, cfg.seed, self.splits, self.pages)

        self._boot("catalog")
        self.goal_cfg = GoalConfig.load(cfg.goal_config_path)
        promo_on, promo_path, promo_inline = cfg.promos_for(self.arm)
        if not promo_on:
            self.promo = None
        elif promo_inline is not None:
            self.promo = PromoSchedule.from_raw(promo_inline)
        else:
            self.promo = PromoSchedule.load(promo_path) if promo_path else None
        self.latent = steps.load_latent_quality(cfg.catalog_dir)
        self.list_prices = self._load_list_prices()
        self.manifest = build_manifest(cfg, self.arm.name, self.run_index,
                                       self.view.view_hash())

        self.log = JsonlEventLog(self.run_dir / "events.jsonl")
        self.mem = HydraMem(run_index=self.run_index, event_log=self.log)

        if seed_graph:
            self._boot("stimuli")
            self.mem.ingest_catalog(cfg.catalog_dir, now=cfg.t0, include_stimuli=False)
            write_stimuli(self.mem.client, cfg.catalog_dir, perceived)
            self._boot("seed_population")
            # v3.8-draft: the social graph is drawn from (seed, "social",
            # population) over OFFSETS, so it is identical across run blocks;
            # cfg.social is None unless a config opts in, and then no
            # TRUSTS_PERSON statement is emitted at all.
            social_edges = None
            if cfg.social is not None:
                from ..population.factory import social_graph
                social_edges = social_graph(cfg.population_size, cfg.seed, cfg.social)
            seed_population(self.mem, self.shoppers, t=cfg.t0 - cfg.tick_seconds,
                            social_edges=social_edges)
            self.mem.cache._built_at = None
        self._boot("manifest")
        write_json_atomic(self.run_dir / "manifest.json", self.manifest)

        def make_mind(kind: str):
            if kind == "formula":
                return FormulaMind(self.view, appraisal_params=appraisal_params,
                                   choice_params=choice_params)
            return ScriptedMind(self.view)

        self.decide_mind = make_mind(cfg.mind_decide)
        self.consolidator = make_mind(cfg.mind_consolidate)

        hero = min(self.promo.windows) if self.promo else None
        drift_concepts = sorted({
            c for row in self.schedule
            for c in (self.view.facts(row.creative_id).claims if self.view.facts(row.creative_id) else ())})
        # v3.8-draft: the run's own seeded A/B pairs (declared page_ids order)
        # feed the within-run violations.bounce_delta; choice_params and
        # w_social are measurement inputs for the fatigue and social channels.
        page_pairs = [list(v[:2]) for _cid, v in sorted(self.splits.items())
                      if len(v) >= 2]
        self.results = ResultsAccumulator(
            arm=self.arm.name, segment_by_offset=self.segment_by_offset,
            drift_concepts=drift_concepts, hero_product=hero,
            page_pairs=page_pairs, choice_params=choice_params,
            w_social=getattr(appraisal_params, "w_social", 0.0))

    def _load_list_prices(self) -> dict[int, float]:
        import csv
        out = {}
        with open(self.cfg.catalog_dir / "catalog.csv", newline="") as fh:
            for row in csv.DictReader(fh):
                out[int(row["product_id"])] = float(row["list_price"])
        return out

    def sid_of(self, offset: int) -> int:
        return make_sid(self.run_index, offset)

    # -- crash injection (kill/resume checkpoint) ----------------------------

    def _maybe_crash(self, phase: str, tick: int) -> None:
        if self.crash_after is None:
            return
        want_phase, want_tick = self.crash_after.split(":")
        if phase == want_phase and tick == int(want_tick):
            # simulate SIGKILL: no flush, no close, no cleanup
            os._exit(137)

    # -- the loop ------------------------------------------------------------

    def run(self, *, from_tick: int = 0, state: RunnerState | None = None) -> dict:
        cfg = self.cfg
        state = state or RunnerState()
        self.state = state
        wall_start = time.perf_counter()

        for tick in range(from_tick, cfg.ticks):
            self._run_tick(tick, state)
            self._write_progress(tick, wall_start, status="running")

        # Phase 6 (CONTRACT v3.8-draft): the finalize pass turns the live
        # skeleton into the full MetricsReport — bootstrap CIs over the
        # per-shopper vectors, plus one read-only belief/provenance sweep. It
        # can only fail on the graph, and a failed sweep degrades to a note
        # rather than losing a finished run.
        from ..analytics.report import finalize_results
        results, notes = finalize_results(
            self.results, self.manifest, mem=self.mem, now=cfg.now_at(cfg.ticks - 1))
        write_json_atomic(self.run_dir / "results.json", results)
        if notes and not self.quiet:
            for note in notes:
                print(f"[{self.arm.name}] metrics note: {note}")
        self._write_progress(cfg.ticks - 1, wall_start, status="complete")
        return results

    def _run_tick(self, tick: int, state: RunnerState) -> None:
        cfg, mem, log = self.cfg, self.mem, self.log
        now = cfg.now_at(tick)
        run = self.run_index
        mem.set_tick(tick=tick, now=now, tick_start=now)
        t_phase = time.perf_counter()

        def lap(name: str) -> None:
            nonlocal t_phase
            self.phase_s[name] = self.phase_s.get(name, 0.0) + (time.perf_counter() - t_phase)
            t_phase = time.perf_counter()
            self._maybe_crash(name, tick)

        # 0. goal step — JSONL first, then per-shopper NEEDS singles
        goal_events, goal_stmts = steps.goal_step(
            seed=cfg.seed, tick=tick, now=now, t0=cfg.t0,
            tick_seconds=cfg.tick_seconds, run=run, goal_cfg=self.goal_cfg,
            overrides=self.overrides, state=state.goal,
            segment_by_offset=self.segment_by_offset, sid_of=self.sid_of)
        for e in goal_events:
            log.append_event(e)
        log.flush()
        mem.client.run_grouped(goal_stmts)
        lap("goal")

        # 1. promo hook (config-derived; self-healing; not logged)
        if self.promo is not None:
            steps.promo_step(mem.client, self.promo, self.list_prices, tick, now)
        lap("promo")

        # 2. exposure draws — with allocation on, the day's reach per creative
        # is rescaled by its trailing smoothed CTR BEFORE the draws. Only the
        # thresholds move: the (seed,"expose",offset,tick) substream, the
        # one-draw-per-active-row order, and the cap checks are untouched, so
        # the stream stays state-independent and resume-identical (v3.6-draft).
        schedule = self.schedule
        alloc_cfg = cfg.allocation
        if alloc_cfg is not None and alloc_cfg.enabled:
            active = [r for r in schedule if r.start_tick <= tick <= r.end_tick]
            shares = steps.allocation_shares(alloc_cfg, active, state.alloc)
            schedule = steps.allocated_schedule(schedule, shares)
        exposures = steps.exposure_step(
            seed=cfg.seed, tick=tick, schedule=schedule,
            offsets=list(self.segment_by_offset), cap_per_tick=cfg.frequency_cap_per_tick,
            cap_72h=cfg.frequency_cap_72h, saw=state.saw,
            segment_by_offset=self.segment_by_offset)
        lap("exposure")

        # 3+4. creative phase — batched retrieval per scheduled creative
        events_by_offset: dict[int, list[Event]] = {}
        page_cohort: dict[tuple[int, int], dict] = {}  # (offset, page) -> info
        for creative in sorted(exposures):
            offs = exposures[creative]
            if not offs:
                continue
            ctxs = mem.get_decision_contexts([self.sid_of(o) for o in offs], creative)
            mind = self.decide_mind.for_stimulus(creative)
            for o in offs:
                sid = self.sid_of(o)
                ctx = ctxs[sid]
                sh = self.by_offset[o]
                a = mind.appraise(ctx, sh.traits)
                rng = substream(cfg.seed, DECIDE_STREAM, o, tick, creative)
                act = mind.decide(a, ctx.scalars, sh.coeffs, rng)
                self.results.observe_decision(ctx, act, "creative", tick)
                events_by_offset.setdefault(o, []).extend(
                    expand_creative(act, sid, creative, now, run))
                if act is Action.CLICK:
                    page = self.page_of(o, creative)
                    if page is None:
                        continue  # page-less product: funnel ends at CLICK
                    facts = self.view.facts(page)
                    product = next(iter(facts.products))
                    key = (o, page)
                    if key not in page_cohort:
                        cart = state.carts.get(o)
                        page_cohort[key] = {
                            "product": product, "cause": creative,
                            "resumed": bool(cart and cart[0] == product)}
        lap("creative")

        # 5. page phase — clickers ∪ cart resumers, batched per page
        for o, (product, page, cause, _) in sorted(state.carts.items()):
            if page and (o, page) not in page_cohort:
                page_cohort[(o, page)] = {"product": product, "cause": cause,
                                          "resumed": True}
        by_page: dict[int, list[int]] = {}
        for (o, page) in sorted(page_cohort):
            by_page.setdefault(page, []).append(o)
        for page in sorted(by_page):
            offs = sorted(by_page[page])
            ctxs = mem.get_decision_contexts([self.sid_of(o) for o in offs], page)
            mind = self.decide_mind.for_stimulus(page)
            for o in offs:
                info = page_cohort[(o, page)]
                product = info["product"]
                price = mem.cache.prices.get(product, self.list_prices.get(product, 0.0))
                sid = self.sid_of(o)
                ctx = ctxs[sid]
                sh = self.by_offset[o]
                a = mind.appraise(ctx, sh.traits)
                rng = substream(cfg.seed, DECIDE_STREAM, o, tick, page)
                act = mind.decide(a, ctx.scalars, sh.coeffs, rng)
                self.results.observe_decision(ctx, act, "page", tick)
                # Expand against what the MIND saw, not what the runner
                # remembers. decide() calls a cart "resumed" iff the cart
                # intersects the stimulus's reference prices, and a
                # REFERENCE_PRICE write can legitimately be evicted by the
                # Law-14 per-tick cap (6 subjective writes, ref_price ranks
                # below PREFERS) — a busy shopper can hold a cart the graph
                # cannot show. Deriving the flag from ctx makes runner and
                # mind read one truth: the cart simply stays in runner state
                # and resumes on a later tick once the price is rewritten.
                resumed = bool(set(ctx.scalars.cart) & set(ctx.scalars.reference_price))
                events_by_offset.setdefault(o, []).extend(expand_page(
                    act, sid, page, product, price, info["cause"],
                    resumed, now, run))
                if act is Action.BUY:
                    state.fulfil.record_bought(o, product, now, tick)
                    state.carts.pop(o, None)
                elif act is Action.CART:
                    state.carts[o] = (product, page, info["cause"], tick)
                elif act is Action.ABANDON:
                    state.carts.pop(o, None)
        lap("page")

        # 6. fulfillment — purchases from tick - lag come back as experiences
        for e in steps.fulfillment_step(
                seed=cfg.seed, tick=tick, now=now, run=run,
                lag_ticks=cfg.fulfillment_lag_ticks, sat_noise_sd=cfg.sat_noise_sd,
                queue=state.fulfil, latent=self.latent, sid_of=self.sid_of):
            events_by_offset.setdefault(shopper_offset(e.shopper_id), []).append(e)
        lap("fulfillment")

        # 7. episodic write — canonical order (offset asc, emission order)
        all_events = [e for o in sorted(events_by_offset) for e in events_by_offset[o]]
        mem.record_events(all_events)  # JSONL write-ahead + grouped edge CREATEs
        self.results.observe_events(all_events, tick)
        # fold this tick's SAW/CLICKED in AFTER the draws: tick t's allocation
        # saw ticks 0..t-1 only (trailing evidence, never lookahead)
        state.alloc.observe(all_events)
        lap("episodic")

        # 8. consolidation — batched snapshots -> consolidate -> apply
        from ..hydramem import writes as hw
        active = sorted(events_by_offset)
        snaps = hw.snapshot_worldviews(mem.client, [self.sid_of(o) for o in active], now)
        per_shopper: dict[int, list[OrderedDelta]] = {}
        for o in active:
            sid = self.sid_of(o)
            deltas = self.consolidator.consolidate(events_by_offset[o], snaps[sid])
            if deltas:
                per_shopper[sid] = [OrderedDelta(now, i, d) for i, d in enumerate(deltas)]
        report = mem.apply_deltas(per_shopper) if per_shopper else ApplyReport()
        lap("consolidation")

        # 9. NEED_SATISFIED records (post-apply, from the kept supersessions)
        for sid, cat, pid in report.satisfied_needs:
            o = shopper_offset(sid)
            log.append({"type": EventType.NEED_SATISFIED.value, "shopper_id": sid,
                        "subject": cat, "t": now, "run": run,
                        "cause_kind": EventType.BOUGHT.value, "cause_id": pid})
            entry = state.goal.live.pop((o, cat), None)
            if entry is not None:
                self.results.observe_satisfaction(entry[1], tick)
        log.flush()
        lap("satisfied")

        # 10. results sweep + snapshots (before the marker: part of the tick).
        # Snapshots are per-tick files (last two kept): a crash between the
        # snapshot and the marker must not clobber the last COMPLETE tick's
        # snapshot, which resume needs.
        self.results.end_tick_sweep(tick, now, mem)
        write_json_atomic(self.run_dir / f"results_state_{tick}.json",
                          {"tick": tick, "state": self.results.state()})
        stale = self.run_dir / f"results_state_{tick - 2}.json"
        if stale.exists():
            stale.unlink()
        lap("results")

        # 11. durable tick marker — the tick officially happened
        log.append({"type": "TICK_COMPLETE", "tick": tick, "t": now, "run": run,
                    "n_events": len(all_events),
                    "belief_counter": mem.allocator._counters["belief"]})
        log.sync()
        lap("marker")
        if not self.quiet:
            n_clicks = sum(1 for e in all_events if e.type is EventType.CLICKED)
            n_buys = sum(1 for e in all_events if e.type is EventType.BOUGHT)
            print(f"[{self.arm.name}] tick {tick:>2}: {len(all_events):>4} events "
                  f"({n_clicks} clicks, {n_buys} buys), "
                  f"needs live {len(state.goal.live)}")

    # -- progress ------------------------------------------------------------

    def _boot(self, phase: str) -> None:
        """Progress during prepare(), before manifest.json exists (v3.7-draft).

        The registry row is published by RunStore.allocate() the moment the run
        dir is made, but manifest.json is only written at the END of prepare()
        — after population generation and graph seeding, which is seconds to
        tens of seconds. In that window a dashboard that opened the run saw a
        bare 404 and no way to tell "still starting" from "broken". This is the
        only file-level signal in between.

        `status: "preparing"` is additive: every consumer keys on "running" or
        "complete", and tick -1 marks that no simulated day exists yet."""
        if not hasattr(self, "_boot_start"):
            self._boot_start = time.perf_counter()
        write_json_atomic(self.run_dir / "progress.json", {
            "run_id": self.run_dir.name,
            "label": self.cfg.label,
            "arm": self.arm.name,
            "status": "preparing",
            "phase": phase,
            "tick": -1,
            "ticks": self.cfg.ticks,
            "population_size": self.cfg.population_size,
            "phase_s": {},
            "total_wall_s": round(time.perf_counter() - self._boot_start, 3),
            "updated_at": time.time(),
        })

    def _write_progress(self, tick: int, wall_start: float, *, status: str) -> None:
        write_json_atomic(self.run_dir / "progress.json", {
            "run_id": self.run_dir.name,
            "label": self.cfg.label,
            "arm": self.arm.name,
            "status": status,
            "tick": tick,
            "ticks": self.cfg.ticks,
            "phase_s": {k: round(v, 3) for k, v in sorted(self.phase_s.items())},
            "total_wall_s": round(time.perf_counter() - wall_start, 3),
            "updated_at": time.time(),
        })

    def close(self) -> None:
        if self.mem is not None:
            self.mem.close()
        if self.log is not None:
            self.log.close()
