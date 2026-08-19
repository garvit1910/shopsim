"""C3 results accumulation + the full-key results.json skeleton + validator.

Phase-3 scope (decision 13): real values for every key the run already sees —
run_manifest, funnel[arm][segment], ctr_by_day, preference_drift, goal_stats,
reference_price_trajectory, motif_stats, violations.count — and typed-but-
empty placeholders for the Phase-6 analytics keys (fatigue_split, belief
metrics, bounce_delta, ci). Garvit codes against the complete shape now.

Phase-6 scope (CONTRACT v3.8-draft) fills those placeholders, split by what
each one needs:

  * accumulator-resident, therefore LIVE through /results-live and exact on
    resume — fatigue_split, belief_drift, violations.bounce_delta,
    repeat_ltv_by_arm, social_lift;
  * finalize-only, because they need the segment map or a graph read — ci,
    belief_confidence_dist, provenance_coverage. results(manifest) without
    `extras` emits those as the same typed-empty placeholders as before, so
    the live path is byte-identical to Phase 5.

Two observation channels, deliberately split:
  * observe_events  — event-derived (funnel, ctr, exposures): available live
    AND on replay, so branch arms accumulate these over their replayed prefix.
  * observe_decision — decision-context-derived (motif prevalence, the
    need-on/off buy split, violation sightings): live decisions only. A branch
    arm accumulates these from its divergence tick on (goal_stats_from_tick
    marks that in the output).

The accumulator state round-trips through JSON (results_state.json is written
each tick before the TICK_COMPLETE marker) so resume restores it exactly.
No wall-clock values anywhere here: same seed => byte-identical results.json.
"""

from __future__ import annotations

from ..analytics import metrics
from ..contracts.enums import Action, EventType, MotifType
from ..contracts.ids import shopper_offset
from ..hydramem import cypher
from ..minds.calibration import DEFAULT_CHOICE_PARAMS
from ..minds.choice import asset_wearout

_FUNNEL_TYPES = tuple(e.value for e in (
    EventType.SAW, EventType.CLICKED, EventType.VISITED, EventType.BROWSED,
    EventType.BOUNCED, EventType.CARTED, EventType.ABANDONED, EventType.BOUGHT,
    EventType.EXPERIENCED,
))

# per-creative attribution (CONTRACT v3.4-draft): SAW/CLICKED carry the
# creative as subject; page/product funnel events carry cause_creative
# (v3.2 item 6). EXPERIENCED is fulfillment-side and stays unattributed.
_CREATIVE_SUBJECT = (EventType.SAW.value, EventType.CLICKED.value)
_CREATIVE_CAUSED = tuple(e.value for e in (
    EventType.VISITED, EventType.BROWSED, EventType.BOUNCED,
    EventType.CARTED, EventType.ABANDONED, EventType.BOUGHT,
))
# page-variant funnel: the events whose subject is the page itself
_PAGE_TYPES = tuple(e.value for e in (
    EventType.VISITED, EventType.BROWSED, EventType.BOUNCED,
))

# CONTRACT v3.8-draft: the per-shopper count vector the Phase-6 bootstrap
# resamples (the shopper is the independent unit — one person's exposures,
# clicks and purchases are one correlated story). A positional int list, not a
# dict, so a 5,000-shopper results_state stays small; this tuple is the only
# index authority and analytics.metrics takes it as a parameter.
BY_SHOPPER_FIELDS: tuple[str, ...] = (
    "SAW", "CLICKED", "BROWSED", "BOUNCED", "CARTED", "BOUGHT",
    "dec_need_on", "buy_need_on", "dec_need_off", "buy_need_off",
    "dec_social_on", "buy_social_on", "dec_social_off", "buy_social_off",
)
_BS = {name: i for i, name in enumerate(BY_SHOPPER_FIELDS)}
_BS_EVENTS = {name: _BS[name] for name in BY_SHOPPER_FIELDS[:6]}

_FATIGUE_ZERO = {
    "n": 0, "clicks": 0,
    "asset_sum": 0.0, "asset_hi_n": 0, "asset_hi_clicks": 0,
    "brand_sum": 0.0, "brand_hi_n": 0, "brand_hi_clicks": 0,
    "concept_sum": 0.0, "concept_hi_n": 0, "concept_hi_clicks": 0,
}


class ResultsAccumulator:
    def __init__(self, *, arm: str, segment_by_offset: dict[int, int],
                 drift_concepts: list[int], hero_product: int | None,
                 decisions_from_tick: int = 0,
                 page_pairs: list | None = None,
                 choice_params=DEFAULT_CHOICE_PARAMS,
                 w_social: float = 0.0):
        self.arm = arm
        self.segment_by_offset = segment_by_offset
        self.drift_concepts = sorted(drift_concepts)
        self.hero_product = hero_product
        self.decisions_from_tick = decisions_from_tick
        # v3.8-draft: the run's own seeded A/B page splits, in the schedule's
        # declared page_ids order, so violations.bounce_delta is a within-run
        # number (cross-arm deltas stay in comparison.json).
        self.page_pairs = [list(p) for p in (page_pairs or [])]
        # measurement inputs, never behavioral: the run's choice calibration is
        # what turns exposures_72h into the asset-wearout level the utility
        # actually subtracted, and w_social says whether the social channel was
        # live at all. Neither is persisted (both are re-supplied on resume).
        self.choice_params = choice_params
        self.w_social = w_social

        self.funnel: dict[str, dict[str, int]] = {}  # segment -> type -> n
        self.ctr: dict[str, dict[str, int]] = {}  # tick -> {exposures, clicks}
        # Phase-4 experiment dimensions (CONTRACT v3.4-draft), all str-keyed
        # for exact JSON round-trip like funnel/ctr above:
        self.by_creative: dict[str, dict[str, int]] = {}  # creative -> type -> n
        self.by_page: dict[str, dict[str, int]] = {}  # page -> type -> n
        self.ctr_creative: dict[str, dict[str, dict[str, int]]] = {}  # creative -> tick
        self.motifs: dict[str, dict] = {}  # type -> {outcomes, strength_sum, n}
        self.goal_split = {"need_on": {"decisions": 0, "buys": 0},
                           "need_off": {"decisions": 0, "buys": 0}}
        self.tts: list[int] = []  # ticks from activation to satisfaction
        self.drift: dict[str, list] = {}  # "concept:segment" -> [mean w per tick]
        self.ref_traj: list[dict] = []
        self.violations = 0
        # CONTRACT v3.5-draft item 3: "trust:{brand}:{seg}" / "trust:{brand}:all"
        # -> [mean live trust-belief value per tick]. Travels ONLY through
        # results_state -> /results-live.live_extras; results() never emits it
        # (C3 + the Phase-6 belief_* placeholders stay untouched).
        self.belief_avg: dict[str, list] = {}
        # CONTRACT v3.6-draft item 3: purchase money. BOUGHT already carries
        # price + cause_creative, so revenue is a real simulated quantity
        # (unlike ad spend, which needs an assumed CPM and stays in the UI).
        self.revenue_total: float = 0.0
        self.revenue_by_creative: dict[str, float] = {}
        # CONTRACT v3.8-draft item 1: the bootstrap's resampling unit. Keyed by
        # OFFSET (str for exact JSON round-trip) — never an absolute shopper id,
        # so a crash/resume in a different run block still hashes identically.
        self.by_shopper: dict[str, list] = {}
        self.revenue_by_shopper: dict[str, float] = {}
        # v3.8-draft item 2: per-tick fatigue channels, measured at decision
        # time from the context the mind actually saw.
        self.fatigue: dict[str, dict] = {}
        # v3.8-draft item 3: mean belief confidence per tick, same keys as
        # belief_avg above (the sweep's live_holds read already returns
        # evidence, so this costs zero extra statements).
        self.belief_conf_avg: dict[str, list] = {}

    # -- channels ------------------------------------------------------------

    def observe_events(self, events, tick: int) -> None:
        c = self.ctr.setdefault(str(tick), {"exposures": 0, "clicks": 0})
        for e in events:
            etype = e.type.value if hasattr(e.type, "value") else str(e.type)
            off = shopper_offset(e.shopper_id)
            seg = str(self.segment_by_offset.get(off, 0))
            if etype in _BS_EVENTS:  # v3.8-draft: the bootstrap unit
                self._row(off)[_BS_EVENTS[etype]] += 1
            if etype in _FUNNEL_TYPES:
                self.funnel.setdefault(seg, {t: 0 for t in _FUNNEL_TYPES})
                self.funnel[seg][etype] += 1
            if etype == EventType.SAW.value:
                c["exposures"] += 1
            elif etype == EventType.CLICKED.value:
                c["clicks"] += 1
            # per-creative funnel + CTR (v3.4-draft)
            if etype in _CREATIVE_SUBJECT:
                creative = e.subject
            elif etype in _CREATIVE_CAUSED:
                creative = e.prop("cause_creative", 0)
            else:
                creative = 0
            if etype == EventType.BOUGHT.value:
                price = float(e.prop("price", 0.0) or 0.0)
                self.revenue_total = round(self.revenue_total + price, 2)
                self.revenue_by_shopper[str(off)] = round(
                    self.revenue_by_shopper.get(str(off), 0.0) + price, 2)
                if creative:
                    self.revenue_by_creative[str(creative)] = round(
                        self.revenue_by_creative.get(str(creative), 0.0) + price, 2)
            if creative:
                row = self.by_creative.setdefault(
                    str(creative), {t: 0 for t in _FUNNEL_TYPES})
                row[etype] += 1
                cc = self.ctr_creative.setdefault(str(creative), {}).setdefault(
                    str(tick), {"exposures": 0, "clicks": 0})
                if etype == EventType.SAW.value:
                    cc["exposures"] += 1
                elif etype == EventType.CLICKED.value:
                    cc["clicks"] += 1
            # per-page-variant funnel (v3.4-draft)
            if etype in _PAGE_TYPES:
                prow = self.by_page.setdefault(
                    str(e.subject), {t: 0 for t in _PAGE_TYPES})
                prow[etype] += 1

    def _row(self, offset: int) -> list:
        return self.by_shopper.setdefault(str(offset), [0] * len(BY_SHOPPER_FIELDS))

    def observe_decision(self, ctx, action: Action, kind: str,
                         tick: int | None = None) -> None:
        brand_msg = concept_sat = 0.0
        social = False
        for m in ctx.motifs:
            row = self.motifs.setdefault(m.type.value, {
                "outcomes": {}, "strength_sum": 0.0, "n": 0})
            row["outcomes"][action.value] = row["outcomes"].get(action.value, 0) + 1
            if m.strength is not None:
                row["strength_sum"] += m.strength
                row["n"] += 1
            if m.type is MotifType.EXPECTATION_VIOLATION:
                self.violations += 1
            elif m.type is MotifType.BRAND_SEMANTIC_FATIGUE:
                brand_msg = max(brand_msg, m.strength or 0.0)
            elif m.type is MotifType.CONCEPT_SATURATION:
                concept_sat = max(concept_sat, m.strength or 0.0)
            elif m.type is MotifType.SOCIAL_PROOF:
                social = True
        offset = shopper_offset(ctx.scalars.shopper_id)
        if kind == "page":
            bucket = "need_on" if ctx.scalars.active_need is not None else "need_off"
            self.goal_split[bucket]["decisions"] += 1
            if action is Action.BUY:
                self.goal_split[bucket]["buys"] += 1
            # v3.8-draft: the same splits per shopper, so the bootstrap can put
            # an interval on the F9 claim. Measured at the PAGE stage because
            # that is where BUY is decided.
            vec = self._row(offset)
            for prefix, on in (("need", ctx.scalars.active_need is not None),
                               ("social", social)):
                suffix = "on" if on else "off"
                vec[_BS[f"dec_{prefix}_{suffix}"]] += 1
                if action is Action.BUY:
                    vec[_BS[f"buy_{prefix}_{suffix}"]] += 1
        elif kind == "creative" and tick is not None:
            # v3.8-draft item 2 — the three fatigue channels, each measured on
            # the decision the mind actually made. asset_wearout() is the same
            # pure function decide() subtracts, called here for MEASUREMENT
            # only: no second entry point (registry row 12 is unchanged).
            r = self.fatigue.setdefault(str(tick), dict(_FATIGUE_ZERO))
            clicked = 1 if action is Action.CLICK else 0
            r["n"] += 1
            r["clicks"] += clicked
            levels = (
                ("asset", asset_wearout(ctx.scalars.exposures_72h, self.choice_params)),
                ("brand", brand_msg),
                ("concept", concept_sat),
            )
            for prefix, level in levels:
                r[f"{prefix}_sum"] += level
                if level >= metrics.FATIGUE_HIGH:
                    r[f"{prefix}_hi_n"] += 1
                    r[f"{prefix}_hi_clicks"] += clicked

    def observe_satisfaction(self, activated_tick: int, satisfied_tick: int) -> None:
        self.tts.append(satisfied_tick - activated_tick)

    # -- per-tick worldview sweep (drift + reference-price trajectory) -------

    def end_tick_sweep(self, tick: int, now: int, mem) -> None:
        offsets = sorted(self.segment_by_offset)
        sid_of = {o: None for o in offsets}
        groups = {}
        from ..contracts.ids import shopper_id as make_sid
        for o in offsets:
            sid = make_sid(mem.run_index, o)
            sid_of[o] = sid
            groups[sid] = [
                cypher.live_edges("PREFERS", sid, now, ("w",)),
                cypher.live_edges("REFERENCE_PRICE", sid, now, ("price",)),
                # CONTRACT v3.5-draft item 3: live trust beliefs per shopper
                cypher.live_holds(sid, now),
            ]
        rows = mem.client.run_grouped(groups)

        from ..contracts.evidence import confidence
        from ..hydramem.schema import ASPECT_TRUST_ID

        sums: dict[tuple[int, int], list] = {}
        ref_prices: list[float] = []
        trust_vals: dict[tuple[int, int], list] = {}  # (brand, segment) -> values
        trust_conf: dict[tuple[int, int], list] = {}  # same keys -> confidences
        for o in offsets:
            seg = self.segment_by_offset[o]
            prefers, refs, holds = rows[sid_of[o]]
            for r in prefers:
                if r["dst"] in self.drift_concepts:
                    sums.setdefault((r["dst"], seg), []).append(r["w"])
            for r in refs:
                if self.hero_product is not None and r["dst"] == self.hero_product:
                    ref_prices.append(r["price"])
            for r in holds:
                if r["that_id"] == ASPECT_TRUST_ID:
                    trust_vals.setdefault((r["about_id"], seg), []).append(r["value"])
                    trust_conf.setdefault((r["about_id"], seg), []).append(
                        confidence(r["evidence"]))
        for (concept, seg), ws in sorted(sums.items()):
            key = f"{concept}:{seg}"
            series = self.drift.setdefault(key, [])
            while len(series) < tick:
                series.append(None)  # segment had no holders in earlier ticks
            series.append(round(sum(ws) / len(ws), 5))
        def push(store: dict, key: str, values: list) -> None:
            series = store.setdefault(key, [])
            while len(series) < tick:
                series.append(None)  # no holders in this cell in earlier ticks
            series.append(round(sum(values) / len(values), 5))

        per_brand: dict[int, list] = {}
        per_brand_conf: dict[int, list] = {}
        for (brand, seg), vs in sorted(trust_vals.items()):
            per_brand.setdefault(brand, []).extend(vs)
            per_brand_conf.setdefault(brand, []).extend(trust_conf[(brand, seg)])
            push(self.belief_avg, f"trust:{brand}:{seg}", vs)
            # v3.8-draft item 3: the confidence twin of the same series
            push(self.belief_conf_avg, f"trust:{brand}:{seg}", trust_conf[(brand, seg)])
        for brand, vs in sorted(per_brand.items()):
            push(self.belief_avg, f"trust:{brand}:all", vs)
            push(self.belief_conf_avg, f"trust:{brand}:all", per_brand_conf[brand])
        if self.hero_product is not None:
            mem.cache.build(now)
            self.ref_traj.append({
                "tick": tick,
                "current_price": mem.cache.prices.get(self.hero_product),
                "mean_reference_price": (round(sum(ref_prices) / len(ref_prices), 4)
                                         if ref_prices else None),
                "n_holders": len(ref_prices),
            })

    # -- persistence (results_state.json) ------------------------------------

    def state(self) -> dict:
        return {
            "arm": self.arm,
            "decisions_from_tick": self.decisions_from_tick,
            "funnel": self.funnel, "ctr": self.ctr, "motifs": self.motifs,
            "by_creative": self.by_creative, "by_page": self.by_page,
            "ctr_creative": self.ctr_creative,
            "goal_split": self.goal_split, "tts": self.tts, "drift": self.drift,
            "ref_traj": self.ref_traj, "violations": self.violations,
            "belief_avg": self.belief_avg,
            "revenue_total": self.revenue_total,
            "revenue_by_creative": self.revenue_by_creative,
            # v3.8-draft
            "by_shopper": self.by_shopper,
            "revenue_by_shopper": self.revenue_by_shopper,
            "fatigue": self.fatigue,
            "belief_conf_avg": self.belief_conf_avg,
            "page_pairs": self.page_pairs,
        }

    @classmethod
    def from_state(cls, state: dict, *, segment_by_offset, drift_concepts,
                   hero_product, choice_params=DEFAULT_CHOICE_PARAMS,
                   w_social: float = 0.0) -> "ResultsAccumulator":
        acc = cls(arm=state["arm"], segment_by_offset=segment_by_offset,
                  drift_concepts=drift_concepts, hero_product=hero_product,
                  decisions_from_tick=state.get("decisions_from_tick", 0),
                  page_pairs=state.get("page_pairs"),
                  choice_params=choice_params, w_social=w_social)
        acc.funnel = state["funnel"]
        acc.ctr = state["ctr"]
        acc.motifs = state["motifs"]
        # .get: snapshots written before the v3.4 keys existed still resume
        acc.by_creative = state.get("by_creative", {})
        acc.by_page = state.get("by_page", {})
        acc.ctr_creative = state.get("ctr_creative", {})
        acc.goal_split = state["goal_split"]
        acc.tts = state["tts"]
        acc.drift = state["drift"]
        acc.ref_traj = state["ref_traj"]
        acc.violations = state["violations"]
        # .get: pre-v3.5 snapshots still resume (CONTRACT v3.5-draft item 3)
        acc.belief_avg = state.get("belief_avg", {})
        # .get: pre-v3.6 snapshots still resume (CONTRACT v3.6-draft item 3)
        acc.revenue_total = state.get("revenue_total", 0.0)
        acc.revenue_by_creative = state.get("revenue_by_creative", {})
        # .get: pre-v3.8 snapshots still resume (CONTRACT v3.8-draft). A run
        # started before Phase 6 simply carries no bootstrap unit and no
        # fatigue channels — the report says so rather than inventing them.
        acc.by_shopper = state.get("by_shopper", {})
        acc.revenue_by_shopper = state.get("revenue_by_shopper", {})
        acc.fatigue = state.get("fatigue", {})
        acc.belief_conf_avg = state.get("belief_conf_avg", {})
        return acc

    # -- final results.json ---------------------------------------------------

    def results(self, manifest: dict, extras: dict | None = None) -> dict:
        """The C3 MetricsReport.

        `extras` carries the finalize-only Phase-6 blocks (ci,
        belief_confidence_dist, provenance_coverage) — see analytics.report.
        Omitted, they stay the typed-empty placeholders Phase 3 shipped, which
        is exactly what /results-live needs: that path rebuilds the accumulator
        without a segment map or a graph handle."""
        extras = extras or {}
        ctr_by_day = []
        for tick in sorted(self.ctr, key=int):
            row = self.ctr[tick]
            ctr_by_day.append({
                "tick": int(tick),
                "exposures": row["exposures"],
                "clicks": row["clicks"],
                "ctr": (round(row["clicks"] / row["exposures"], 5)
                        if row["exposures"] else None),
            })
        motif_stats = {
            mtype: {
                "prevalence_by_outcome": dict(sorted(row["outcomes"].items())),
                "mean_strength": (round(row["strength_sum"] / row["n"], 5)
                                  if row["n"] else None),
            }
            for mtype, row in sorted(self.motifs.items())
        }
        drift = [
            {"concept": int(k.split(":")[0]), "segment": int(k.split(":")[1]),
             "series": series}
            for k, series in sorted(self.drift.items())
        ]
        gs = self.goal_split

        def p(bucket):
            d = gs[bucket]["decisions"]
            return round(gs[bucket]["buys"] / d, 5) if d else None

        funnel_by_creative = {
            creative: dict(sorted(counts.items()))
            for creative, counts in sorted(self.by_creative.items())}
        funnel_by_page = {}
        for page, counts in sorted(self.by_page.items()):
            visits = counts[EventType.VISITED.value] + counts[EventType.BOUNCED.value]
            funnel_by_page[page] = {
                **dict(sorted(counts.items())),
                "bounce_rate": (round(counts[EventType.BOUNCED.value] / visits, 5)
                                if visits else None),
            }
        ctr_by_creative_by_day = []
        for creative in sorted(self.ctr_creative):
            for tick in sorted(self.ctr_creative[creative], key=int):
                row = self.ctr_creative[creative][tick]
                ctr_by_creative_by_day.append({
                    "creative": int(creative), "tick": int(tick),
                    "exposures": row["exposures"], "clicks": row["clicks"],
                    "ctr": (round(row["clicks"] / row["exposures"], 5)
                            if row["exposures"] else None),
                })

        return {
            "run_manifest": manifest,
            "funnel": {self.arm: {seg: dict(sorted(counts.items()))
                                  for seg, counts in sorted(self.funnel.items())}},
            "ctr_by_day": ctr_by_day,
            "funnel_by_creative": funnel_by_creative,  # v3.4-draft
            "funnel_by_page": funnel_by_page,  # v3.4-draft
            "ctr_by_creative_by_day": ctr_by_creative_by_day,  # v3.4-draft
            "revenue": {"total": round(self.revenue_total, 2),  # v3.6-draft
                        "by_creative": dict(sorted(self.revenue_by_creative.items()))},
            "fatigue_split": metrics.fatigue_rows(self.fatigue),  # v3.8-draft
            "reference_price_trajectory": self.ref_traj,
            "violations": {
                "count": self.violations,
                # within-run page-split delta (v3.8-draft); cross-arm deltas
                # stay in the experiment's comparison.json
                "bounce_delta": metrics.bounce_delta(funnel_by_page, self.page_pairs),
            },
            "motif_stats": motif_stats,
            "preference_drift": drift,
            "goal_stats": {
                "p_buy_need_on": p("need_on"),
                "p_buy_need_off": p("need_off"),
                "decisions_need_on": gs["need_on"]["decisions"],
                "decisions_need_off": gs["need_off"]["decisions"],
                "time_to_satisfaction": sorted(self.tts),
                "decisions_from_tick": self.decisions_from_tick,
            },
            # v3.8-draft: accumulator-resident, therefore live
            "belief_drift": metrics.belief_drift_rows(
                self.belief_avg, self.belief_conf_avg),
            "repeat_ltv_by_arm": metrics.repeat_ltv(
                self.by_shopper, BY_SHOPPER_FIELDS, self.revenue_by_shopper, self.arm),
            "social_lift": metrics.social_lift(
                self.by_shopper, BY_SHOPPER_FIELDS, self.w_social),
            # finalize-only: filled by analytics.report, empty on the live path
            "belief_confidence_dist": extras.get("belief_confidence_dist", []),
            "provenance_coverage": extras.get("provenance_coverage"),
            "ci": extras.get("ci", {}),
        }


# ---------------------------------------------------------------------------
# C3 validation
# ---------------------------------------------------------------------------

_REQUIRED_MANIFEST = (
    "seed", "config_hash", "perception_cache_hash", "appraisal_cache_hash",
    "evidence_hash", "goal_config_hash", "latent_quality_hash",
)


def validate_results(results: dict) -> list[str]:
    """C3 shape check. Returns problems (empty = valid)."""
    problems = []

    def need(key, typ):
        if key not in results:
            problems.append(f"missing key {key}")
            return None
        if typ is not None and not isinstance(results[key], typ):
            problems.append(f"{key}: expected {typ.__name__}, got {type(results[key]).__name__}")
            return None
        return results[key]

    manifest = need("run_manifest", dict)
    if manifest is not None:
        for k in _REQUIRED_MANIFEST:
            if k not in manifest:
                problems.append(f"run_manifest missing {k}")

    funnel = need("funnel", dict)
    if funnel is not None:
        for arm, segments in funnel.items():
            if not isinstance(segments, dict):
                problems.append(f"funnel[{arm}] must be a dict of segments")
                continue
            for seg, counts in segments.items():
                if not isinstance(counts, dict):
                    problems.append(f"funnel[{arm}][{seg}] must be a dict of counts")

    ctr = need("ctr_by_day", list)
    if ctr is not None:
        for row in ctr:
            if not {"tick", "ctr"} <= set(row):
                problems.append("ctr_by_day rows need tick + ctr")
                break

    # v3.4-draft experiment keys: validated only when present — results.json
    # committed before Phase 4 (fixtures/scripted-run-1) must keep validating
    if "funnel_by_creative" in results:
        if not isinstance(results["funnel_by_creative"], dict):
            problems.append("funnel_by_creative must be a dict")
        else:
            for creative, counts in results["funnel_by_creative"].items():
                if not isinstance(counts, dict):
                    problems.append(f"funnel_by_creative[{creative}] must be a dict")
    if "funnel_by_page" in results:
        if not isinstance(results["funnel_by_page"], dict):
            problems.append("funnel_by_page must be a dict")
        else:
            for page, counts in results["funnel_by_page"].items():
                if not isinstance(counts, dict) or "bounce_rate" not in counts:
                    problems.append(f"funnel_by_page[{page}] needs counts + bounce_rate")
    if "ctr_by_creative_by_day" in results:
        for row in results.get("ctr_by_creative_by_day") or []:
            if not {"creative", "tick", "ctr"} <= set(row):
                problems.append("ctr_by_creative_by_day rows need creative/tick/ctr")
                break

    # v3.6-draft: additive, so validated only when present (pre-3.6 results
    # files stay valid — the same rule the v3.4 keys above follow)
    if "revenue" in results:
        rev = results["revenue"]
        if not isinstance(rev, dict) or not {"total", "by_creative"} <= set(rev):
            problems.append("revenue needs total + by_creative")

    fs = need("fatigue_split", dict)
    if fs is not None:
        if not {"asset", "brand_msg"} <= set(fs):
            problems.append("fatigue_split needs asset[] + brand_msg[]")
        else:
            # v3.8-draft row shape, checked only where rows exist: every
            # results.json written before Phase 6 carries empty channels and
            # must keep validating (fixtures/scripted-run-1 is frozen).
            for channel, rows in fs.items():
                if not isinstance(rows, list):
                    problems.append(f"fatigue_split[{channel}] must be a list")
                    continue
                for row in rows:
                    if not {"tick", "mean", "high_ctr", "low_ctr"} <= set(row):
                        problems.append(
                            f"fatigue_split[{channel}] rows need "
                            "tick/mean/high_ctr/low_ctr")
                        break

    need("reference_price_trajectory", list)

    v = need("violations", dict)
    if v is not None and "count" not in v:
        problems.append("violations needs count")

    ms = need("motif_stats", dict)
    if ms is not None:
        for mtype, row in ms.items():
            if not {"prevalence_by_outcome", "mean_strength"} <= set(row):
                problems.append(f"motif_stats[{mtype}] shape wrong")

    drift = need("preference_drift", list)
    if drift is not None:
        for row in drift:
            if not {"concept", "segment", "series"} <= set(row):
                problems.append("preference_drift rows need concept/segment/series")
                break

    gs = need("goal_stats", dict)
    if gs is not None:
        for k in ("p_buy_need_on", "p_buy_need_off", "time_to_satisfaction"):
            if k not in gs:
                problems.append(f"goal_stats missing {k}")

    dist = need("belief_confidence_dist", list)
    if dist is not None:
        for row in dist:
            if not {"aspect", "bin_lo", "bin_hi", "count"} <= set(row):
                problems.append(
                    "belief_confidence_dist rows need aspect/bin_lo/bin_hi/count")
                break
    bd = need("belief_drift", list)
    if bd is not None:
        for row in bd:
            if not {"aspect", "about", "segment", "series"} <= set(row):
                problems.append("belief_drift rows need aspect/about/segment/series")
                break
    if "provenance_coverage" not in results:
        problems.append("missing key provenance_coverage")
    else:
        # v3.8-draft: null until Phase 6 fills it (every pre-6 file), then the
        # summary dict — a bare float would have hidden the counts behind it.
        pc = results["provenance_coverage"]
        if pc is not None and (not isinstance(pc, dict) or "coverage" not in pc):
            problems.append("provenance_coverage must be null or a dict with coverage")
    ci = need("ci", dict)
    if ci is not None:
        for metric, span in ci.items():
            if not isinstance(span, (list, tuple)) or len(span) != 2:
                problems.append(f"ci[{metric}] must be [lo, hi]")
                break
    # v3.8-draft additive keys: validated only when present, the same rule the
    # v3.4/v3.6 keys follow
    if "repeat_ltv_by_arm" in results:
        for row in results.get("repeat_ltv_by_arm") or []:
            if not {"arm", "buyers", "buys", "repeat_rate"} <= set(row):
                problems.append("repeat_ltv_by_arm rows need arm/buyers/buys/repeat_rate")
                break
    if "social_lift" in results:
        sl = results["social_lift"]
        if sl is not None and (not isinstance(sl, dict) or "causal" not in sl):
            problems.append("social_lift must be null or a dict carrying causal")
    return problems
