"""F1-F12 — the face-validity suite (PLAN 7.1).

Each law is one function returning a `LawResult`. Two kinds of function, kept
apart on purpose:

  * `analytic_*` take (population, ObjectiveView, Profile) and compute the law
    from mind arithmetic alone. No database, milliseconds, any number of seeds.
  * `scenario_*` / `audit_*` take payloads a finished run already wrote
    (results.json, comparison.json). They never re-derive a metric Phase 6
    computes — F7a reads `provenance_coverage.prefers.cause_kinds`, F5 reads
    `violations.bounce_delta`, F12 reads `fatigue_split`.

F7 and F9 are marked never_drop: PLAN.md says they ARE the demo claim.

Every result carries `numbers` (what was measured), `threshold` (what it had to
beat, and why that value), and `series` (what the chart draws). A law that
passes without saying what it measured is not evidence.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..contracts import evidence
from ..minds.appraisal import appraise
from ..minds.choice import stage_probabilities
from .contexts import DEFAULT_MIX, Profile, make_context

TIERS = ("analytic", "scenario", "audit")


@dataclass(frozen=True)
class LawResult:
    id: str
    name: str
    tier: str
    passed: bool
    numbers: dict = field(default_factory=dict)
    threshold: str = ""
    note: str = ""
    never_drop: bool = False
    series: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "tier": self.tier,
            "passed": self.passed, "never_drop": self.never_drop,
            "numbers": self.numbers, "threshold": self.threshold,
            "note": self.note, "series": self.series,
        }


def _r(x, n=5):
    return None if x is None else round(float(x), n)


def _mean_click(pop, ctx, stim, profile) -> float:
    tot = 0.0
    for sh in pop:
        a = appraise(ctx, sh.traits, stim, params=profile.appraisal)
        tot += stage_probabilities(a, ctx.scalars, sh.coeffs, kind="creative",
                                   params=profile.choice)["CLICK"]
    return tot / len(pop)


def _mean_gate(pop, ctx, stim, profile, stage: str, kind: str = "page") -> float:
    tot = 0.0
    for sh in pop:
        a = appraise(ctx, sh.traits, stim, params=profile.appraisal)
        tot += stage_probabilities(a, ctx.scalars, sh.coeffs, kind=kind,
                                   params=profile.choice)[stage]
    return tot / len(pop)


# ---------------------------------------------------------------------------
# F1 — frequency response rises, then wears out (asset level)
# ---------------------------------------------------------------------------

# Adstock after n consecutive daily exposures under the retrieval half-life
# (schema.RetrievalParams.adstock_half_life_s = 2 days): a geometric sum of
# decayed SAWs. Reproduced here rather than guessed, so the analytic curve and
# a real run's curve are the same quantity.
def adstock_after(n: int, half_life_days: float = 2.0) -> float:
    return sum(math.exp(-math.log(2.0) * i / half_life_days) for i in range(n))


def analytic_f1_frequency_response(pop, view, profile: Profile, *,
                                   stimulus: int = 2000003,
                                   max_exposures: int = 12,
                                   per_day: int = 2) -> LawResult:
    """Asset-level, so the brand-message motif is held at zero and the asset
    channel (gamma x adstock, then -delta x wearout) carries the whole curve.

    `exposures_72h` is capped at `3 * per_day`, because that is all a 72-hour
    window can physically hold (schema.RetrievalParams.freq_window_seconds).
    Sweeping it past that is the mistake that makes a wearout curve look
    healthy in a bench and flat in a real run: production frequency caps mean
    the reachable range is 0-6, so `wearout_free_exposures` and `wearout_scale`
    have to span THAT range, not an imaginary one.
    """
    stim = view.facts(stimulus)
    window_cap = 3 * per_day
    curve = []
    for n in range(1, max_exposures + 1):
        ctx = make_context("learned", kind="creative", fatigue=0.0,
                           adstock=adstock_after(n), exposures_72h=min(n, window_cap))
        curve.append({"exposures": n, "exposures_72h": min(n, window_cap),
                      "p_click": _r(_mean_click(pop, ctx, stim, profile), 6)})

    peak = max(curve, key=lambda r: r["p_click"])
    peak_i = curve.index(peak)
    final = curve[-1]["p_click"]
    rose = peak_i > 0 and peak["p_click"] > curve[0]["p_click"]
    decay = (peak["p_click"] - final) / peak["p_click"] if peak["p_click"] else 0.0
    passed = bool(rose and decay >= 0.15)
    return LawResult(
        id="F1", name="frequency response rises then wears out", tier="analytic",
        passed=passed,
        numbers={"p_click_first": curve[0]["p_click"],
                 "p_click_peak": peak["p_click"], "peak_at_exposure": peak["exposures"],
                 "p_click_final": final, "decay_from_peak": _r(decay)},
        threshold="peak after exposure 1, and >=15% decay from peak by the last "
                  "exposure (published creative-wearout curves fall 30-60% over a "
                  "campaign; 15% is the floor for 'visible')",
        note="adstock builds the rise (gamma x min(adstock, cap)); exposures_72h "
             "past wearout_free_exposures builds the fall (-delta x wearout).",
        series={"frequency_response": curve})


# ---------------------------------------------------------------------------
# F2 — unaware + no paths + no belief => engagement ~ 0
# ---------------------------------------------------------------------------


def analytic_f2_cold_gate(pop, view, profile: Profile, *,
                          stimulus: int = 2000003) -> LawResult:
    stim = view.facts(stimulus)
    cold = make_context("cold", kind="creative")
    warm = make_context("learned", kind="creative")
    p_cold = _mean_click(pop, cold, stim, profile)
    p_warm = _mean_click(pop, warm, stim, profile)
    a_cold = appraise(cold, pop[0].traits, stim, params=profile.appraisal)
    ratio = p_cold / p_warm if p_warm else None
    passed = bool(a_cold.relevance == 0.0 and ratio is not None and ratio <= 0.35)
    return LawResult(
        id="F2", name="unaware + no paths + no belief => engagement ~ 0",
        tier="analytic", passed=passed,
        numbers={"p_click_cold": _r(p_cold, 6), "p_click_warm": _r(p_warm, 6),
                 "ratio": _r(ratio), "cold_relevance": a_cold.relevance,
                 "cold_credibility": _r(a_cold.credibility)},
        threshold="cold relevance exactly 0 (structural, not small) and cold CTR "
                  "<= 0.35x warm CTR",
        note="Abstention is structural: no live PREFERS overlap => no "
             "preference_fit, no HOLDS row => null trust_belief. The gate then "
             "damps credibility and the perceived offer as well.")


# ---------------------------------------------------------------------------
# F3 — discount uplift ordering matches price sensitivity
# ---------------------------------------------------------------------------


def analytic_f3_discount_ordering(pop, view, profile: Profile, *,
                                  stimulus: int = 2000003,
                                  depths=(0.0, 0.1, 0.2, 0.3, 0.4)) -> LawResult:
    """The REALISED price channel (decide() row 13), which is where
    price_sensitivity enters. offer_attractiveness is the perceived claim and is
    held fixed here on purpose, so this law tests one mechanism, not two."""
    stim = view.facts(stimulus)
    ranked = sorted(pop, key=lambda s: s.coeffs.price_sensitivity)
    third = max(1, len(ranked) // 3)
    groups = {"low_price_sensitivity": ranked[:third],
              "mid_price_sensitivity": ranked[third:2 * third],
              "high_price_sensitivity": ranked[2 * third:]}

    series, uplift = {}, {}
    for gname, members in groups.items():
        rows = []
        for d in depths:
            ctx = make_context("learned", kind="page", price_gap=-d)
            rows.append({"depth": d, "p_buy": _r(_mean_gate(members, ctx, stim, profile, "BUY"), 6)})
        series[gname] = rows
        base, deep = rows[0]["p_buy"], rows[-1]["p_buy"]
        uplift[gname] = _r(deep / base if base else None)

    lo, mid, hi = (uplift["low_price_sensitivity"], uplift["mid_price_sensitivity"],
                   uplift["high_price_sensitivity"])
    passed = bool(None not in (lo, mid, hi) and hi > mid > lo)
    return LawResult(
        id="F3", name="discount uplift ordering matches price sensitivity",
        tier="analytic", passed=passed,
        numbers={"uplift_x_at_%d%%" % int(depths[-1] * 100): uplift,
                 "mean_price_sensitivity": {
                     g: _r(sum(s.coeffs.price_sensitivity for s in m) / len(m))
                     for g, m in groups.items()}},
        threshold="strict ordering high > mid > low on BUY uplift at the deepest "
                  "depth",
        series={"discount_ladder": series})


# ---------------------------------------------------------------------------
# F6 — abstention: gated vs ungated on an unknown brand   (PLAN 7.4's chart)
# ---------------------------------------------------------------------------


def analytic_f6_abstention(pop, view, profile: Profile, *,
                           stimulus: int = 2000003) -> LawResult:
    """Three bars, which is the whole argument in one picture:

      known brand           what engagement looks like with real evidence
      unknown, GATED        this engine: no path, no belief => near zero
      unknown, UNGATED      the strawman a persona-prompted LLM produces, which
                            invents familiarity it has no receipt for

    The ungated arm is built by handing the same unaware shopper a fabricated
    trust belief at the population's mean known-brand level and switching the
    cold factors off — i.e. exactly the hallucination the gate exists to refuse.
    """
    from dataclasses import replace

    stim = view.facts(stimulus)
    known = make_context("learned", kind="creative")
    unknown = make_context("cold", kind="creative")

    p_known = _mean_click(pop, known, stim, profile)
    p_gated = _mean_click(pop, unknown, stim, profile)

    # The ungated arm is the honest strawman: a model with no structural way to
    # say "I have never heard of this brand" answers about an unknown brand the
    # way it answers about a familiar one. It invents BOTH halves - a trust
    # belief with no receipt AND a preference path that was never earned - so
    # the unknown brand inherits known-brand engagement. Building it by taking
    # the known-brand context on a shopper the graph says is unaware is exactly
    # that failure, and it needs no new arithmetic.
    ungated_profile = replace(
        profile,
        appraisal=replace(profile.appraisal, cold_credibility_factor=1.0,
                          cold_offer_factor=1.0))
    fabricated = type(known)(
        scalars=replace(known.scalars, aware_of_brand=False),
        motifs=known.motifs)
    p_ungated = _mean_click(pop, fabricated, stim, ungated_profile)

    vs_known = p_gated / p_known if p_known else None
    vs_ungated = p_gated / p_ungated if p_ungated else None
    passed = bool(vs_known is not None and vs_known <= 0.35
                  and vs_ungated is not None and vs_ungated <= 0.35)
    return LawResult(
        id="F6", name="abstention: hallucinated familiarity ~ 0 when gated",
        tier="analytic", passed=passed,
        numbers={"p_click_known_brand": _r(p_known, 6),
                 "p_click_unknown_gated": _r(p_gated, 6),
                 "p_click_unknown_ungated": _r(p_ungated, 6),
                 "gated_vs_known": _r(vs_known), "gated_vs_ungated": _r(vs_ungated)},
        threshold="gated unknown-brand CTR <= 0.35x both the known-brand and the "
                  "ungated-strawman CTR",
        note="The ungated arm fabricates a trust belief the shopper has no "
             "evidence for. That is the failure mode this engine refuses "
             "structurally rather than by prompt instruction.",
        series={"abstention": [
            {"case": "known brand", "p_click": _r(p_known, 6)},
            {"case": "unknown, ungated", "p_click": _r(p_ungated, 6)},
            {"case": "unknown, gated", "p_click": _r(p_gated, 6)},
        ]})


# ---------------------------------------------------------------------------
# F8 — evidence hierarchy: equal counts => strictly ordered dw
# ---------------------------------------------------------------------------


def analytic_f8_evidence_hierarchy(*, w0: float = 0.4, e0: float = 2.0,
                                   count: int = 3) -> LawResult:
    """Unit-level and fully deterministic: the same starting edge, the same
    number of events, one event type each. Reads evidence.py directly, so it
    fails the moment the frozen table is edited."""
    from ..contracts.enums import EventType

    order = (EventType.CLICKED, EventType.BROWSED, EventType.CARTED, EventType.BOUGHT)
    deltas = {}
    for et in order:
        w, e = w0, e0
        wt = evidence.EVIDENCE_TABLE[et].pref_weight
        for _ in range(count):
            w, e = evidence.blend(w, e, evidence.PREF_TARGET, wt)
        deltas[et.value] = _r(w - w0, 6)

    values = [deltas[et.value] for et in order]
    passed = all(a < b for a, b in zip(values, values[1:]))
    return LawResult(
        id="F8", name="evidence hierarchy: CLICK < BROWSE < CART < BUY",
        tier="analytic", passed=passed,
        numbers={"delta_w": deltas, "start_w": w0, "start_evidence": e0,
                 "events_each": count},
        threshold="strictly increasing delta_w in CLICK < BROWSE < CART < BUY",
        note="Equal counts, one formula (evidence.blend); only the per-event "
             "weight differs. SAW carries pref_weight 0.0 and is absent by "
             "construction - that is F7, not this law.",
        series={"evidence_hierarchy": [{"event": k, "delta_w": v}
                                       for k, v in deltas.items()]})


# ---------------------------------------------------------------------------
# F10 — confidence-differential updating
# ---------------------------------------------------------------------------


def analytic_f10_confidence_differential(*, value: float = 0.75,
                                         low_e: float = 0.75, high_e: float = 6.0,
                                         contradiction: float = 0.15,
                                         weight: float = 2.0) -> LawResult:
    """Identical contradictory evidence, two beliefs that differ only in how
    much evidence stands behind them. No extra mechanism exists for this: it
    falls out of w' = (E*w + wt*target)/(E + wt)."""
    lw, _le = evidence.blend(value, low_e, contradiction, weight)
    hw, _he = evidence.blend(value, high_e, contradiction, weight)
    move_low, move_high = value - lw, value - hw
    passed = bool(move_low > move_high > 0)
    return LawResult(
        id="F10", name="confidence-differential updating", tier="analytic",
        passed=passed,
        numbers={"start_value": value, "contradiction_target": contradiction,
                 "low_evidence": low_e, "high_evidence": high_e,
                 "moved_low_E": _r(move_low), "moved_high_E": _r(move_high),
                 "ratio": _r(move_low / move_high if move_high else None),
                 "confidence_low": _r(evidence.confidence(low_e)),
                 "confidence_high": _r(evidence.confidence(high_e))},
        threshold="a low-evidence belief must move strictly further than a "
                  "high-evidence one under identical contradiction",
        series={"confidence_differential": [
            {"evidence": low_e, "moved": _r(move_low)},
            {"evidence": high_e, "moved": _r(move_high)}]})


ANALYTIC_LAWS = (
    analytic_f1_frequency_response,
    analytic_f2_cold_gate,
    analytic_f3_discount_ordering,
    analytic_f6_abstention,
)


# ===========================================================================
# audit tier — assertions over what a finished run already wrote
# ===========================================================================

# Behavioural receipts. "SEED" is the population factory's prior and is filtered
# out before this check (it is not a LEARNED version); "SAW" must never appear
# at all, and neither must "none".
LEARNED_CAUSES = frozenset(("CLICKED", "BROWSED", "VISITED", "CARTED", "BOUGHT",
                            "EXPERIENCED"))
FORBIDDEN_CAUSES = frozenset(("SAW", "none", "SEED", "PRICE_SEEN", "BOUNCED",
                              "ABANDONED"))


def audit_f7a_no_learning_from_exposure(results_by_name: dict[str, dict]) -> LawResult:
    """F7(a) — the invariant audit, never-drop.

    Reads `provenance_coverage.prefers.cause_kinds`, which Phase 6 already
    computes on every finalize. Nothing is re-derived here: if this law needed
    its own sweep it could disagree with the report, and then neither would be
    evidence.
    """
    pooled: dict[str, int] = {}
    per_run, skipped = {}, []
    for name, results in sorted(results_by_name.items()):
        pc = (results or {}).get("provenance_coverage")
        if not pc:
            skipped.append(name)
            continue
        kinds = pc.get("prefers", {}).get("cause_kinds") or {}
        per_run[name] = {"cause_kinds": dict(sorted(kinds.items())),
                         "coverage": pc.get("prefers", {}).get("coverage")}
        for k, v in kinds.items():
            pooled[k] = pooled.get(k, 0) + int(v)

    violations = {k: v for k, v in pooled.items()
                  if k in FORBIDDEN_CAUSES or k not in LEARNED_CAUSES}
    audited = bool(per_run)
    passed = bool(audited and not violations)
    return LawResult(
        id="F7a", name="no learning from exposure (invariant audit)", tier="audit",
        passed=passed, never_drop=True,
        numbers={"runs_audited": sorted(per_run), "runs_without_provenance": skipped,
                 "pooled_cause_kinds": dict(sorted(pooled.items())),
                 "forbidden_causes_seen": violations,
                 "learned_versions": sum(pooled.values())},
        threshold="every LEARNED PREFERS version cites a behavioural cause; a "
                  "single SAW-caused or cause-less version fails the law",
        note="Exposure touches awareness, adstock and EXPECTS only "
             "(evidence.py: SAW carries pref_weight 0.0). This audit is the "
             "thing that would catch one confused updater putting taste back "
             "on the exposure channel." if passed else
             "FORBIDDEN CAUSE PRESENT — a preference was learned from something "
             "that is not a behavioural receipt.")


# ===========================================================================
# scenario tier — laws that only exist once the graph is in the loop
# ===========================================================================


def _funnel_totals(results: dict, arm: str | None = None) -> dict[str, int]:
    out: dict[str, int] = {}
    for a, segments in (results.get("funnel") or {}).items():
        if arm is not None and a != arm:
            continue
        for counts in segments.values():
            for k, v in counts.items():
                out[k] = out.get(k, 0) + int(v)
    return out


def _ctr(t: dict) -> float | None:
    return t.get("CLICKED", 0) / t["SAW"] if t.get("SAW") else None


def scenario_f5_violation_bounce(results: dict, *, page_a: int, page_b: int) -> LawResult:
    """F5 — the variant that breaks an expectation must bounce harder.

    `violations.bounce_delta` is Phase 6's own within-run number over the
    schedule's declared page_ids order (B minus A, violating variant second),
    so this law reads it rather than recomputing a second bounce rate that
    could disagree with the report.
    """
    by_page = results.get("funnel_by_page") or {}
    a, b = by_page.get(str(page_a), {}), by_page.get(str(page_b), {})
    delta = (results.get("violations") or {}).get("bounce_delta")
    sighted = (results.get("violations") or {}).get("count", 0)
    passed = bool(delta is not None and delta > 0 and sighted > 0)
    return LawResult(
        id="F5", name="the violating page variant bounces more", tier="scenario",
        passed=passed,
        numbers={"bounce_rate_consistent": a.get("bounce_rate"),
                 "bounce_rate_violating": b.get("bounce_rate"),
                 "bounce_delta": delta, "violations_sighted": sighted,
                 "visits_consistent": a.get("VISITED", 0) + a.get("BOUNCED", 0),
                 "visits_violating": b.get("VISITED", 0) + b.get("BOUNCED", 0)},
        threshold="bounce_delta > 0 with at least one expectation_violation motif "
                  "actually retrieved",
        note="Same seed, same shoppers, seeded 50/50 split — the only difference "
             "is that the B variant hides a concept its own creative claimed.",
        series={"page_bounce": [
            {"variant": f"{page_a} (consistent)", "bounce_rate": a.get("bounce_rate")},
            {"variant": f"{page_b} (violating)", "bounce_rate": b.get("bounce_rate")}]})


def scenario_f9_maya_law(on: dict, off: dict, *, arm_on: str, arm_off: str,
                         ctr_floor: float = 1.05, buy_floor: float = 1.5) -> LawResult:
    """F9 — the demo claim as a test, never-drop.

    Paired twin arms, same seed, identical except that one has the goal. A need
    should move PURCHASE far more than it moves CLICK: relevance carries weight
    1.2 at the CLICK gate and 2.2 at BUY, so goal-gating is supposed to show up
    down the funnel, not at the top of it. If CTR moved as much as BUY, the goal
    would just be a generic attention multiplier and the claim would be empty.
    """
    t_on, t_off = _funnel_totals(on, arm_on), _funnel_totals(off, arm_off)
    ctr_on, ctr_off = _ctr(t_on), _ctr(t_off)
    buy_on = t_on.get("BOUGHT", 0) / t_on["SAW"] if t_on.get("SAW") else None
    buy_off = t_off.get("BOUGHT", 0) / t_off["SAW"] if t_off.get("SAW") else None
    ctr_ratio = (ctr_on / ctr_off) if ctr_on is not None and ctr_off else None
    buy_ratio = (buy_on / buy_off) if buy_on is not None and buy_off else None

    # The decision-level split the accumulator measures at the page stage is the
    # cleaner statement of the same claim, and it survives small buy counts.
    gs_on = on.get("goal_stats") or {}
    p_need_on, p_need_off = gs_on.get("p_buy_need_on"), gs_on.get("p_buy_need_off")
    within = (p_need_on / p_need_off) if p_need_on and p_need_off else None

    passed = bool(buy_ratio is not None and ctr_ratio is not None
                  and buy_ratio > ctr_ratio and buy_ratio >= buy_floor
                  and ctr_ratio >= ctr_floor)
    return LawResult(
        id="F9", name="the Maya law: a goal moves BUY more than it moves CTR",
        tier="scenario", passed=passed, never_drop=True,
        numbers={"ctr_need_on": _r(ctr_on, 6), "ctr_need_off": _r(ctr_off, 6),
                 "ctr_uplift_x": _r(ctr_ratio), "buy_per_exposure_need_on": _r(buy_on, 6),
                 "buy_per_exposure_need_off": _r(buy_off, 6), "buy_uplift_x": _r(buy_ratio),
                 "within_run_p_buy_need_on": p_need_on,
                 "within_run_p_buy_need_off": p_need_off,
                 "within_run_uplift_x": _r(within),
                 "buys_need_on": t_on.get("BOUGHT", 0), "buys_need_off": t_off.get("BOUGHT", 0)},
        threshold=f"BUY uplift > CTR uplift, with BUY uplift >= {buy_floor}x and "
                  f"CTR uplift >= {ctr_floor}x",
        note="Same seed, same population, same ad. The twin arm branches from the "
             "live arm's own log, so everything before the divergence tick is "
             "shared history rather than a re-simulation.",
        series={"twin": [{"metric": "CTR", "uplift_x": _r(ctr_ratio)},
                         {"metric": "BUY per exposure", "uplift_x": _r(buy_ratio)}]})


def scenario_f12_fatigue_separation(repetition: dict, rotation: dict,
                                    *, min_gap: float = 0.10) -> LawResult:
    """F12 — same-concept repetition decays CTR faster than concept rotation.

    Both arms carry the same impression budget; only the creative mix differs.
    The brand-message channel is what separates them: repeating one story keeps
    re-hitting the same claimed concepts, so `brand_semantic_fatigue` saturates,
    while rotation spreads the recency sum across different concepts.
    """
    def decay(results):
        rows = [r for r in (results.get("ctr_by_day") or []) if r.get("ctr") is not None]
        if len(rows) < 4:
            return None, None, None, []
        half = len(rows) // 2
        first = sum(r["clicks"] for r in rows[:half]) / max(1, sum(r["exposures"] for r in rows[:half]))
        last = sum(r["clicks"] for r in rows[half:]) / max(1, sum(r["exposures"] for r in rows[half:]))
        return first, last, (1.0 - last / first if first else None), rows

    rep_first, rep_last, rep_decay, rep_rows = decay(repetition)
    rot_first, rot_last, rot_decay, rot_rows = decay(rotation)

    def mean_brand_fatigue(results):
        rows = ((results.get("fatigue_split") or {}).get("brand_msg") or [])
        return (sum(r["mean"] * r["n"] for r in rows) / sum(r["n"] for r in rows)
                if rows and sum(r["n"] for r in rows) else None)

    gap = (rep_decay - rot_decay) if None not in (rep_decay, rot_decay) else None
    passed = bool(gap is not None and gap >= min_gap)
    return LawResult(
        id="F12", name="repetition decays CTR faster than concept rotation",
        tier="scenario", passed=passed,
        numbers={"repetition_ctr_first_half": _r(rep_first, 6),
                 "repetition_ctr_second_half": _r(rep_last, 6),
                 "repetition_decay": _r(rep_decay),
                 "rotation_ctr_first_half": _r(rot_first, 6),
                 "rotation_ctr_second_half": _r(rot_last, 6),
                 "rotation_decay": _r(rot_decay),
                 "decay_gap": _r(gap),
                 "mean_brand_fatigue_repetition": _r(mean_brand_fatigue(repetition)),
                 "mean_brand_fatigue_rotation": _r(mean_brand_fatigue(rotation))},
        threshold=f"repetition CTR decay exceeds rotation decay by >= {min_gap:.0%} "
                  "(half-run vs half-run)",
        series={"fatigue_ctr": {
            "repetition": [{"tick": r["tick"], "ctr": r["ctr"]} for r in rep_rows],
            "rotation": [{"tick": r["tick"], "ctr": r["ctr"]} for r in rot_rows]}})


def scenario_f11_experience_loop(good: dict, bad: dict, *,
                                 good_q: float = 0.85, bad_q: float = 0.35) -> LawResult:
    """F11 — latent quality the shopper cannot see, felt only through delivery.

    Latent quality never enters a DecisionContext (Law 15): it reaches the
    shopper solely as EXPERIENCED satisfaction after a fulfilment lag. So a
    divergence in trust trajectories is proof the experience loop is closed,
    not proof the mind was told the answer.
    """
    def trust_end(results):
        rows = [r for r in (results.get("belief_drift") or [])
                if r.get("aspect") == "trust" and r.get("segment") == "all"]
        series = [v for r in rows for v in (r.get("series") or []) if v is not None]
        return (series[-1] if series else None,
                [{"i": i, "value": v} for r in rows
                 for i, v in enumerate(r.get("series") or []) if v is not None])

    g_trust, g_series = trust_end(good)
    b_trust, b_series = trust_end(bad)
    g_ltv = (good.get("repeat_ltv_by_arm") or [{}])[0]
    b_ltv = (bad.get("repeat_ltv_by_arm") or [{}])[0]
    gap = (g_trust - b_trust) if None not in (g_trust, b_trust) else None
    g_rep, b_rep = g_ltv.get("repeat_rate"), b_ltv.get("repeat_rate")
    repeat_ok = (g_rep is not None and b_rep is not None and g_rep >= b_rep)
    passed = bool(gap is not None and gap > 0.05 and repeat_ok)
    return LawResult(
        id="F11", name="experience loop: latent quality moves trust and repeat rate",
        tier="scenario", passed=passed,
        numbers={"latent_quality_good": good_q, "latent_quality_bad": bad_q,
                 "final_trust_good": g_trust, "final_trust_bad": b_trust,
                 "trust_gap": _r(gap),
                 "repeat_rate_good": g_rep, "repeat_rate_bad": b_rep,
                 "buyers_good": g_ltv.get("buyers"), "buyers_bad": b_ltv.get("buyers"),
                 "revenue_per_buyer_good": g_ltv.get("revenue_per_buyer"),
                 "revenue_per_buyer_bad": b_ltv.get("revenue_per_buyer")},
        threshold="final mean trust in the good-quality arm exceeds the bad arm by "
                  "> 0.05, and repeat-purchase rate does not invert",
        note="Two FRESH runs, never a branch: an alternate latent_quality.csv "
             "changes latent_quality_hash, which is a shared manifest hash.",
        series={"trust_trajectories": {"good": g_series, "bad": b_series}})


def buys_by_tick(events_path) -> dict[int, int]:
    """Purchases per tick, straight from the run's own event log.

    C3 has no purchases-by-tick key and does not need one for its own sake, so
    F4 derives it here rather than growing the MetricsReport a field that exists
    only to serve one law.
    """
    import json as _json
    from pathlib import Path as _Path

    out: dict[int, int] = {}
    t0 = tick_seconds = None
    manifest = _Path(events_path).parent / "manifest.json"
    if manifest.exists():
        m = _json.loads(manifest.read_text())
        t0, tick_seconds = int(m["t0"]), int(m["tick_seconds"])
    with _Path(events_path).open() as fh:
        for line in fh:
            if '"BOUGHT"' not in line:
                continue
            rec = _json.loads(line)
            if rec.get("type") != "BOUGHT":
                continue
            tick = ((int(rec["t"]) - t0) // tick_seconds
                    if t0 is not None else int(rec.get("tick", 0)))
            out[tick] = out.get(tick, 0) + 1
    return out


def scenario_f4_promo_addiction(results: dict, promo_cycles, *,
                                buys: dict[int, int] | None = None,
                                min_gain_pp: float = 15.0) -> LawResult:
    """F4 — promo addiction: purchases migrate into the discount window.

    `promo_cycles` is [(cycle, start_tick, end_tick, discount_pct)] from the
    schedule the run actually used. Share is computed per cycle as purchases
    inside the window over purchases in the window plus the same number of
    full-price ticks either side, so a widening window cannot flatter the share.
    """
    buys = buys or {}
    cycles = []
    for cycle, start, end, pct in promo_cycles:
        window = range(int(start), int(end) + 1)
        span = len(window)
        before = range(max(0, int(start) - span), int(start))
        after = range(int(end) + 1, int(end) + 1 + span)
        inside = sum(buys.get(t, 0) for t in window)
        outside = sum(buys.get(t, 0) for t in before) + \
            sum(buys.get(t, 0) for t in after)
        total = inside + outside
        cycles.append({"cycle": int(cycle), "discount_pct": pct,
                       "buys_in_window": inside, "buys_full_price": outside,
                       "promo_share": _r(inside / total) if total else None})

    first = next((c for c in cycles if c["promo_share"] is not None), None)
    last = next((c for c in reversed(cycles) if c["promo_share"] is not None), None)
    gain_pp = ((last["promo_share"] - first["promo_share"]) * 100.0
               if first and last and first is not last else None)
    passed = bool(gain_pp is not None and gain_pp >= min_gain_pp)
    return LawResult(
        id="F4", name="promo addiction: purchase share migrates into the window",
        tier="scenario", passed=passed,
        numbers={"cycles": cycles, "promo_share_gain_pp": _r(gain_pp),
                 "reference_price_end": ((results.get("reference_price_trajectory") or
                                          [{}])[-1].get("mean_reference_price"))},
        threshold=f"promo-window purchase share rises >= {min_gain_pp:.0f}pp from the "
                  "first cycle to the last",
        note="The mechanism is the learned reference price: each window teaches a "
             "lower anchor (evidence.smooth_reference_price, alpha 0.3), so the "
             "full-price shelf reads as a loss afterwards (decide() row 13, "
             "losses x2).",
        series={"promo_cycles": cycles})


def scenario_f7b_heavy_exposure(results: dict, *, drift_tol: float = 0.02) -> LawResult:
    """F7(b) — the scenario half of never-drop F7.

    Heavy exposure with the CLICK gate shut: awareness and EXPECTS must climb
    while learned preferences stay exactly flat. This is the behavioural
    statement of what F7a asserts structurally.
    """
    drift = results.get("preference_drift") or []
    moves = []
    for row in drift:
        series = [v for v in (row.get("series") or []) if v is not None]
        if len(series) >= 2:
            moves.append(abs(series[-1] - series[0]))
    worst = max(moves) if moves else None
    totals = _funnel_totals(results)
    passed = bool(totals.get("SAW", 0) > 0 and totals.get("CLICKED", 0) == 0
                  and (worst is None or worst <= drift_tol))
    return LawResult(
        id="F7b", name="heavy exposure, zero clicks => flat learned preferences",
        tier="scenario", passed=passed, never_drop=True,
        numbers={"exposures": totals.get("SAW", 0), "clicks": totals.get("CLICKED", 0),
                 "preference_series_tracked": len(moves),
                 "largest_preference_move": _r(worst),
                 "motif_types_seen": sorted((results.get("motif_stats") or {}))},
        threshold=f"zero clicks, and no tracked preference series moves by more "
                  f"than {drift_tol}",
        note="Awareness, adstock and EXPECTS are free to move — those ARE the "
             "exposure channels. Taste is not.")
