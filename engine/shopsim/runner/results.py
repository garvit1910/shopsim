"""C3 results accumulation + the full-key results.json skeleton + validator.

Phase-3 scope (decision 13): real values for every key the run already sees —
run_manifest, funnel[arm][segment], ctr_by_day, preference_drift, goal_stats,
reference_price_trajectory, motif_stats, violations.count — and typed-but-
empty placeholders for the Phase-6 analytics keys (fatigue_split, belief
metrics, bounce_delta, ci). Garvit codes against the complete shape now.

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

from ..contracts.enums import Action, EventType, MotifType
from ..contracts.ids import shopper_offset
from ..hydramem import cypher

_FUNNEL_TYPES = tuple(e.value for e in (
    EventType.SAW, EventType.CLICKED, EventType.VISITED, EventType.BROWSED,
    EventType.BOUNCED, EventType.CARTED, EventType.ABANDONED, EventType.BOUGHT,
    EventType.EXPERIENCED,
))


class ResultsAccumulator:
    def __init__(self, *, arm: str, segment_by_offset: dict[int, int],
                 drift_concepts: list[int], hero_product: int | None,
                 decisions_from_tick: int = 0):
        self.arm = arm
        self.segment_by_offset = segment_by_offset
        self.drift_concepts = sorted(drift_concepts)
        self.hero_product = hero_product
        self.decisions_from_tick = decisions_from_tick

        self.funnel: dict[str, dict[str, int]] = {}  # segment -> type -> n
        self.ctr: dict[str, dict[str, int]] = {}  # tick -> {exposures, clicks}
        self.motifs: dict[str, dict] = {}  # type -> {outcomes, strength_sum, n}
        self.goal_split = {"need_on": {"decisions": 0, "buys": 0},
                           "need_off": {"decisions": 0, "buys": 0}}
        self.tts: list[int] = []  # ticks from activation to satisfaction
        self.drift: dict[str, list] = {}  # "concept:segment" -> [mean w per tick]
        self.ref_traj: list[dict] = []
        self.violations = 0

    # -- channels ------------------------------------------------------------

    def observe_events(self, events, tick: int) -> None:
        c = self.ctr.setdefault(str(tick), {"exposures": 0, "clicks": 0})
        for e in events:
            etype = e.type.value if hasattr(e.type, "value") else str(e.type)
            seg = str(self.segment_by_offset.get(shopper_offset(e.shopper_id), 0))
            if etype in _FUNNEL_TYPES:
                self.funnel.setdefault(seg, {t: 0 for t in _FUNNEL_TYPES})
                self.funnel[seg][etype] += 1
            if etype == EventType.SAW.value:
                c["exposures"] += 1
            elif etype == EventType.CLICKED.value:
                c["clicks"] += 1

    def observe_decision(self, ctx, action: Action, kind: str) -> None:
        for m in ctx.motifs:
            row = self.motifs.setdefault(m.type.value, {
                "outcomes": {}, "strength_sum": 0.0, "n": 0})
            row["outcomes"][action.value] = row["outcomes"].get(action.value, 0) + 1
            if m.strength is not None:
                row["strength_sum"] += m.strength
                row["n"] += 1
            if m.type is MotifType.EXPECTATION_VIOLATION:
                self.violations += 1
        if kind == "page":
            bucket = "need_on" if ctx.scalars.active_need is not None else "need_off"
            self.goal_split[bucket]["decisions"] += 1
            if action is Action.BUY:
                self.goal_split[bucket]["buys"] += 1

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
            ]
        rows = mem.client.run_grouped(groups)

        sums: dict[tuple[int, int], list] = {}
        ref_prices: list[float] = []
        for o in offsets:
            seg = self.segment_by_offset[o]
            prefers, refs = rows[sid_of[o]]
            for r in prefers:
                if r["dst"] in self.drift_concepts:
                    sums.setdefault((r["dst"], seg), []).append(r["w"])
            for r in refs:
                if self.hero_product is not None and r["dst"] == self.hero_product:
                    ref_prices.append(r["price"])
        for (concept, seg), ws in sorted(sums.items()):
            key = f"{concept}:{seg}"
            series = self.drift.setdefault(key, [])
            while len(series) < tick:
                series.append(None)  # segment had no holders in earlier ticks
            series.append(round(sum(ws) / len(ws), 5))
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
            "goal_split": self.goal_split, "tts": self.tts, "drift": self.drift,
            "ref_traj": self.ref_traj, "violations": self.violations,
        }

    @classmethod
    def from_state(cls, state: dict, *, segment_by_offset, drift_concepts,
                   hero_product) -> "ResultsAccumulator":
        acc = cls(arm=state["arm"], segment_by_offset=segment_by_offset,
                  drift_concepts=drift_concepts, hero_product=hero_product,
                  decisions_from_tick=state.get("decisions_from_tick", 0))
        acc.funnel = state["funnel"]
        acc.ctr = state["ctr"]
        acc.motifs = state["motifs"]
        acc.goal_split = state["goal_split"]
        acc.tts = state["tts"]
        acc.drift = state["drift"]
        acc.ref_traj = state["ref_traj"]
        acc.violations = state["violations"]
        return acc

    # -- final results.json ---------------------------------------------------

    def results(self, manifest: dict) -> dict:
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

        return {
            "run_manifest": manifest,
            "funnel": {self.arm: {seg: dict(sorted(counts.items()))
                                  for seg, counts in sorted(self.funnel.items())}},
            "ctr_by_day": ctr_by_day,
            "fatigue_split": {"asset": [], "brand_msg": []},  # Phase 6
            "reference_price_trajectory": self.ref_traj,
            "violations": {"count": self.violations, "bounce_delta": None},  # delta: Phase 6
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
            "belief_confidence_dist": [],  # Phase 6
            "belief_drift": [],  # Phase 6
            "provenance_coverage": None,  # Phase 6
            "ci": {},  # Phase 6
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

    fs = need("fatigue_split", dict)
    if fs is not None and not {"asset", "brand_msg"} <= set(fs):
        problems.append("fatigue_split needs asset[] + brand_msg[]")

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

    need("belief_confidence_dist", list)
    need("belief_drift", list)
    if "provenance_coverage" not in results:
        problems.append("missing key provenance_coverage")
    need("ci", dict)
    return problems
