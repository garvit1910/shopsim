"""Phase-6 analytics: the statistical half of the C3 MetricsReport.

Everything here is a pure function over data the run already holds — the
ResultsAccumulator's state, plus (for the belief block) one read-only sweep of
the graph. Nothing writes; nothing consults a wall clock.

Determinism rules this module obeys, because results.json must stay
byte-identical for the same seed across a crash/resume in a DIFFERENT run
block (tests/real/test_runner_real.py::norm_results_hash):

  * the bootstrap rng is seeded from the run seed only, via the fixed CI_STREAM
    tag, and resamples SHOPPER OFFSETS — never absolute shopper ids;
  * no belief-node id, shopper id or wall-clock value reaches any output;
  * every float is rounded the way the rest of results.py rounds (5 dp, money 2).

Why the bootstrap clusters on shoppers: a shopper's events are strongly
correlated (one person's exposures, clicks and purchases are one story), so
resampling individual events would understate the interval badly. The shopper
is the independent unit, which is also why the accumulator keeps a per-offset
count vector (results.py::BY_SHOPPER_FIELDS) rather than only segment totals.
"""

from __future__ import annotations

import numpy as np

# int.from_bytes(b"ci") — a stable substream tag beside "pop"/"goal"/"fulfil"
# /"social" (Law 13: seeded substreams keyed by stable tuples).
CI_STREAM = int.from_bytes(b"ci", "big")

N_BOOT = 2000
ALPHA = 0.05

# A decision counts as "high" on a fatigue channel at or above this level.
# All three channels are already 0..1: asset wearout is
# clamp01((exposures_72h - free)/scale) and both motif strengths are capped at
# 1.0 by their retrieval normalizers. 0.5 on the asset channel means
# exposures_72h >= 4 with the default ChoiceParams, which is where the
# dashboard's own detector rule sits (web/lib/detectors.ts fatigueExposures).
FATIGUE_HIGH = 0.5

# The funnel ratios the report carries a CI for. Each is (numerator field,
# denominator field) over BY_SHOPPER_FIELDS, so one set of bootstrap replicates
# serves all of them — the intervals stay mutually coherent.
CI_RATIOS: tuple[tuple[str, str, str], ...] = (
    ("ctr", "CLICKED", "SAW"),
    ("browse_rate", "BROWSED", "CLICKED"),
    ("cart_rate", "CARTED", "BROWSED"),
    ("buy_rate", "BOUGHT", "CARTED"),
    ("buy_per_exposure", "BOUGHT", "SAW"),
)

# Decision-channel ratios: available only from the tick the arm started
# deciding (branch arms accumulate these from their divergence tick, exactly
# like goal_stats — goal_stats.decisions_from_tick marks that).
CI_DECISION_RATIOS: tuple[tuple[str, str, str], ...] = (
    ("p_buy_need_on", "buy_need_on", "dec_need_on"),
    ("p_buy_need_off", "buy_need_off", "dec_need_off"),
)


def _r5(x):
    return None if x is None else round(float(x), 5)


def _ratio(num: float, den: float):
    return None if not den else num / den


# ---------------------------------------------------------------------------
# bootstrap
# ---------------------------------------------------------------------------


def bootstrap_ratio_ci(num: np.ndarray, den: np.ndarray, seed_seq: np.random.SeedSequence,
                       *, n_boot: int = N_BOOT, alpha: float = ALPHA):
    """Percentile CI for sum(num)/sum(den) under resampling of the rows.

    num/den are per-shopper vectors; a replicate that draws an all-zero
    denominator contributes nothing (the ratio is undefined, not zero).
    Returns [lo, hi] or None when the point estimate itself is undefined or
    too few replicates are usable.
    """
    n = len(den)
    if n == 0 or den.sum() == 0:
        return None
    rng = np.random.default_rng(seed_seq)
    stats = np.empty(n_boot, dtype=float)
    # chunked so a 5,000-shopper population never materializes a 2000xN index
    chunk = max(1, min(n_boot, 4_000_000 // max(n, 1)))
    done = 0
    while done < n_boot:
        k = min(chunk, n_boot - done)
        idx = rng.integers(0, n, size=(k, n))
        d = den[idx].sum(axis=1)
        with np.errstate(divide="ignore", invalid="ignore"):
            stats[done:done + k] = np.where(d > 0, num[idx].sum(axis=1) / d, np.nan)
        done += k
    good = stats[~np.isnan(stats)]
    if good.size < n_boot // 10:
        return None
    lo, hi = np.percentile(good, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return [_r5(lo), _r5(hi)]


def funnel_ci(by_shopper: dict, fields: tuple[str, ...], segment_by_offset: dict,
              seed: int, *, n_boot: int = N_BOOT, alpha: float = ALPHA) -> dict:
    """C3 `ci{metric: [lo, hi]}` over the per-shopper count vectors.

    Keys are "<metric>" for the whole arm and "<metric>:<segment>" per segment
    (PLAN 6.1: "funnels per arm x segment with bootstrap CIs"). Segments with
    no shoppers, and ratios whose denominator is empty, are simply absent —
    an interval is never invented for a rate that does not exist.
    """
    if not by_shopper:
        return {}
    offsets = sorted(by_shopper, key=int)
    col = {name: i for i, name in enumerate(fields)}
    mat = np.array([[by_shopper[o][i] for i in range(len(fields))] for o in offsets],
                   dtype=float)
    seg_of = {str(k): v for k, v in (segment_by_offset or {}).items()}

    scopes: list[tuple[str, int, np.ndarray]] = [("", 0, np.arange(len(offsets)))]
    if seg_of:
        by_seg: dict[int, list[int]] = {}
        for i, o in enumerate(offsets):
            seg = seg_of.get(str(int(o)))
            if seg is not None:
                by_seg.setdefault(int(seg), []).append(i)
        for seg in sorted(by_seg):
            scopes.append((f":{seg}", seg, np.array(by_seg[seg])))

    out: dict[str, list] = {}
    for suffix, scope_key, rows in scopes:
        if rows.size == 0:
            continue
        sub = mat[rows]
        for i, (name, num_f, den_f) in enumerate(CI_RATIOS + CI_DECISION_RATIOS):
            if num_f not in col or den_f not in col:
                continue
            num, den = sub[:, col[num_f]], sub[:, col[den_f]]
            if den.sum() == 0:
                continue
            ss = np.random.SeedSequence((int(seed), CI_STREAM, int(scope_key), i))
            ci = bootstrap_ratio_ci(num, den, ss, n_boot=n_boot, alpha=alpha)
            if ci is not None:
                out[f"{name}{suffix}"] = ci
    return dict(sorted(out.items()))


# ---------------------------------------------------------------------------
# fatigue split (PLAN 6.1: asset wearout vs brand-message vs concept)
# ---------------------------------------------------------------------------

# accumulator row -> (mean-sum key, high-count key, high-click key)
FATIGUE_CHANNELS: tuple[tuple[str, str], ...] = (
    ("asset", "asset"),
    ("brand_msg", "brand"),
    ("concept", "concept"),
)


def fatigue_rows(fatigue: dict) -> dict:
    """Three parallel per-tick series, one per fatigue channel.

    Deliberately NOT a decomposition of a single number: the three channels are
    separate mechanisms measured on the same decisions (asset repetition enters
    decide() as -delta*wearout; brand-message fatigue enters appraise() as its
    own dim; concept saturation is retrieved and, at P0, behaviourally inert).
    `mean` is the population mean channel level among that tick's creative
    decisions; high/low split those decisions at FATIGUE_HIGH so the CTR
    columns answer the F12 question directly.
    """
    out: dict[str, list] = {}
    for label, prefix in FATIGUE_CHANNELS:
        rows = []
        for tick in sorted(fatigue, key=int):
            r = fatigue[tick]
            n = int(r.get("n", 0))
            if not n:
                continue
            hi_n = int(r.get(f"{prefix}_hi_n", 0))
            hi_c = int(r.get(f"{prefix}_hi_clicks", 0))
            lo_n, lo_c = n - hi_n, int(r.get("clicks", 0)) - hi_c
            rows.append({
                "tick": int(tick),
                "n": n,
                "mean": _r5(r.get(f"{prefix}_sum", 0.0) / n),
                "high_n": hi_n,
                "high_ctr": _r5(_ratio(hi_c, hi_n)),
                "low_n": lo_n,
                "low_ctr": _r5(_ratio(lo_c, lo_n)),
            })
        out[label] = rows
    return out


# ---------------------------------------------------------------------------
# belief drift (from the per-tick sweep the accumulator already runs)
# ---------------------------------------------------------------------------


def belief_drift_rows(belief_avg: dict, belief_conf_avg: dict) -> list[dict]:
    """C3 `belief_drift[]` from the v3.5 sweep's series.

    Keys are "<aspect>:<brand>:<segment|all>", the same keys /results-live
    already serves as live_extras.belief_avg — Phase 6 promotes them into the
    report and pairs each value series with its confidence series (free: the
    sweep's live_holds read already returns evidence)."""
    rows = []
    for key in sorted(belief_avg):
        parts = key.split(":")
        if len(parts) != 3:
            continue
        aspect, about, seg = parts
        rows.append({
            "aspect": aspect,
            "about": int(about),
            "segment": "all" if seg == "all" else int(seg),
            "series": belief_avg[key],
            "confidence_series": belief_conf_avg.get(key, []),
        })
    return rows


# ---------------------------------------------------------------------------
# within-run page-split bounce delta (the per-run counterpart of the
# cross-arm delta comparison.json already computes)
# ---------------------------------------------------------------------------


def bounce_delta(by_page: dict, page_pairs) -> float | None:
    """Pooled bounce_rate(B) - bounce_rate(A) over the run's own seeded page
    splits, in the schedule's declared page_ids order (same B-A convention as
    experiments/compare.py::_page_ab_section, where the violating variant is
    listed second and the delta is expected positive)."""
    if not page_pairs:
        return None
    a_b = a_v = b_b = b_v = 0
    for pair in page_pairs:
        if len(pair) < 2:
            continue
        a, b = str(pair[0]), str(pair[1])
        ra, rb = by_page.get(a), by_page.get(b)
        if not ra or not rb:
            continue
        a_b += ra.get("BOUNCED", 0)
        a_v += ra.get("BOUNCED", 0) + ra.get("VISITED", 0)
        b_b += rb.get("BOUNCED", 0)
        b_v += rb.get("BOUNCED", 0) + rb.get("VISITED", 0)
    if not a_v or not b_v:
        return None
    return _r5(b_b / b_v - a_b / a_v)


# ---------------------------------------------------------------------------
# repeat purchase / LTV (P1) and social lift (P1)
# ---------------------------------------------------------------------------


def repeat_ltv(by_shopper: dict, fields: tuple[str, ...],
               revenue_by_shopper: dict, arm: str) -> list[dict]:
    """C3 `repeat_ltv_by_arm[]` — one row, since a results.json is single-arm
    (cross-arm merging is comparison.json's job). "LTV" here is honestly just
    realized revenue per buyer over the simulated window: no discounting, no
    projection beyond the run."""
    idx = fields.index("BOUGHT")
    buys = [row[idx] for row in by_shopper.values()]
    buyers = sum(1 for b in buys if b > 0)
    repeat = sum(1 for b in buys if b > 1)
    total_buys = sum(buys)
    revenue = round(sum(revenue_by_shopper.values()), 2)
    return [{
        "arm": arm,
        "buyers": buyers,
        "buys": total_buys,
        "repeat_buyers": repeat,
        "repeat_rate": _r5(_ratio(repeat, buyers)),
        "buys_per_buyer": _r5(_ratio(total_buys, buyers)),
        "revenue_total": revenue,
        "revenue_per_buyer": (round(revenue / buyers, 2) if buyers else None),
    }]


def social_lift(by_shopper: dict, fields: tuple[str, ...], w_social: float):
    """C3 `social_lift?` — P(buy) at decisions that carried a social_proof
    motif vs decisions that did not, within the run.

    `causal` is the honesty flag: the social_proof channel only moves behaviour
    when the run's calibration sets w_social > 0 (registry row 20, P1). With
    w_social == 0 the motif is retrieved and reported but never read by
    appraise(), so any gap here is correlation — peers who bought are peers of
    shoppers the schedule also happened to reach — and the payload says so.
    Returns None when no decision in the run carried the motif (i.e. the social
    layer was never seeded), because an interval over nothing is not a metric.
    """
    i_on, i_bon = fields.index("dec_social_on"), fields.index("buy_social_on")
    i_off, i_boff = fields.index("dec_social_off"), fields.index("buy_social_off")
    dec_on = sum(r[i_on] for r in by_shopper.values())
    if not dec_on:
        return None
    buy_on = sum(r[i_bon] for r in by_shopper.values())
    dec_off = sum(r[i_off] for r in by_shopper.values())
    buy_off = sum(r[i_boff] for r in by_shopper.values())
    p_on, p_off = _ratio(buy_on, dec_on), _ratio(buy_off, dec_off)
    causal = bool(w_social)
    return {
        "p_buy_social_on": _r5(p_on),
        "p_buy_social_off": _r5(p_off),
        "lift": _r5(p_on / p_off) if p_on is not None and p_off else None,
        "decisions_on": dec_on,
        "decisions_off": dec_off,
        "w_social": _r5(w_social),
        "causal": causal,
        "note": ("social_proof feeds credibility at w_social>0 (registry row 20)"
                 if causal else
                 "w_social = 0: the motif is retrieved and reported but never "
                 "read by appraise(), so this gap is correlation, not lift"),
    }
