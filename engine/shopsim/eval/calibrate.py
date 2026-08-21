"""PLAN 7.2 — aggregate calibration to published ranges, before/after documented.

The targets are not invented here. Every band comes from `eval/market-research.md`
with its source, and the band tuple carries the citation so a number can never
appear in a report without the thing that justifies it.

The fit is a coordinate descent over a small, deliberately-chosen parameter set,
scored by `loss()` against those bands, and evaluated by replaying a real run's
decision trace (`trace.score`). That makes each candidate cost milliseconds
instead of the 20-110 minutes a real run costs — which is the only reason
iterating to a good profile is possible at all.

**What the offline fit cannot see, stated plainly:** replay re-scores the
contexts the BASELINE run produced. It cannot model the feedback loop where a
better click rate teaches more preferences, forms more trust beliefs, and raises
relevance for every later impression. Offline numbers are therefore a lower
bound on a re-run, and `verify()` measures the gap rather than assuming it away.
"""

from __future__ import annotations

from dataclasses import replace

from ..minds.calibration import STAGES
from . import trace

# metric -> (lo, hi, source). `visit_to_purchase` is the consistency check that
# ties the others together: 0.5 x 0.15 x 0.26 ~ 2%, which is where the apparel
# sitewide conversion band independently lands.
TARGETS: dict[str, tuple[float, float, str]] = {
    "p_click": (0.005, 0.02,
                "market-research.md S1 — Meta retail CTR 1.59-1.71%, display "
                "0.46%; adopted band 0.5-2%"),
    "bounce_rate": (0.45, 0.55,
                    "market-research.md S2 — BROWSE = 1 - bounce, target 0.45-0.55"),
    "p_cart_given_browse": (0.10, 0.20,
                            "market-research.md S2 — fashion add-to-cart 7.1-7.7% "
                            "of sessions, ~2x conditioned on non-bounce"),
    "p_buy_given_cart": (0.24, 0.28,
                         "market-research.md S2 — 1 - cart abandonment (72-76%)"),
    "visit_to_purchase": (0.01, 0.03,
                          "market-research.md S2 — apparel sitewide conversion 1-3%"),
}

# The knobs the fit is allowed to move, and the range it may move them in.
# Deliberately small: every one of these is a documented calibration constant
# with a mechanism behind it, and a fit that can reach anything explains nothing.
SEARCH_SPACE: tuple[tuple[str, tuple, float, float], ...] = (
    ("stage_bases.CLICK", ("stage_bases", "CLICK"), 3.0, 8.0),
    ("stage_bases.BROWSE", ("stage_bases", "BROWSE"), 1.0, 3.5),
    ("stage_bases.CART", ("stage_bases", "CART"), 2.5, 5.0),
    ("stage_bases.BUY", ("stage_bases", "BUY"), 2.0, 4.5),
)


def _band_loss(value: float | None, lo: float, hi: float) -> float:
    """Relative distance outside the band; 0 inside it.

    Relative rather than absolute because the metrics differ by two orders of
    magnitude — an absolute loss would let a 1pp CTR miss outweigh a 20pp bounce
    miss. Being inside the band is a pass, not something to over-optimise: there
    is no reward for sitting exactly at the midpoint of a range the literature
    reports as a range.
    """
    if value is None:
        return 1.0
    if value < lo:
        return (lo - value) / lo
    if value > hi:
        return (value - hi) / hi
    return 0.0


def loss(rates: dict, targets: dict = TARGETS) -> tuple[float, dict]:
    per = {name: round(_band_loss(rates.get(name), lo, hi), 6)
           for name, (lo, hi, _src) in targets.items()}
    return round(sum(per.values()), 6), per


def in_band(rates: dict, targets: dict = TARGETS) -> dict[str, bool]:
    return {name: (rates.get(name) is not None and lo <= rates[name] <= hi)
            for name, (lo, hi, _s) in targets.items()}


def _with(profile, path: tuple, value: float):
    """A copy of `profile` with one search-space coordinate replaced."""
    group, key = path
    if group == "stage_bases":
        return replace(profile, stage_bases=tuple(
            (st, value if st == key else dict(profile.stage_bases)[st]) for st in STAGES))
    if group == "choice":
        return replace(profile, choice=replace(profile.choice, **{key: value}))
    if group == "appraisal":
        return replace(profile, appraisal=replace(profile.appraisal, **{key: value}))
    raise KeyError(group)


def evaluate(rows, profile, traced_stage_bases) -> dict:
    return trace.score(rows, appraisal_params=profile.appraisal,
                       choice_params=profile.choice,
                       stage_bases=profile.stage_bases,
                       traced_stage_bases=traced_stage_bases)["model"]


def fit(rows, profile, traced_stage_bases, *, space=SEARCH_SPACE,
        rounds: int = 4, grid: int = 13, targets=TARGETS) -> dict:
    """Coordinate descent: sweep one knob at a time on a shrinking grid.

    Coordinate descent rather than a global optimiser because the parameters are
    close to separable — each stage base moves its own gate and only weakly
    affects the others through the shared adstock/wearout terms — and because
    the trajectory is readable. A calibration nobody can follow is not a
    calibration, it is a magic number with extra steps.
    """
    best = profile
    best_rates = evaluate(rows, best, traced_stage_bases)
    best_loss, _ = loss(best_rates, targets)
    history = [{"round": 0, "knob": None, "loss": best_loss,
                "rates": {k: round(v, 5) for k, v in best_rates.items() if v is not None}}]

    for rnd in range(1, rounds + 1):
        shrink = 0.5 ** (rnd - 1)
        improved = False
        for name, path, lo, hi in space:
            group, key = path
            cur = (dict(best.stage_bases)[key] if group == "stage_bases"
                   else getattr(getattr(best, group), key))
            span = (hi - lo) * shrink / 2.0
            width_lo, width_hi = max(lo, cur - span), min(hi, cur + span)
            if width_hi <= width_lo:
                continue
            step = (width_hi - width_lo) / (grid - 1)
            for i in range(grid):
                cand = _with(best, path, width_lo + i * step)
                rates = evaluate(rows, cand, traced_stage_bases)
                cand_loss, _ = loss(rates, targets)
                if cand_loss < best_loss - 1e-9:
                    best, best_loss, best_rates, improved = cand, cand_loss, rates, True
            history.append({
                "round": rnd, "knob": name, "loss": round(best_loss, 6),
                "value": round(dict(best.stage_bases)[key] if group == "stage_bases"
                               else getattr(getattr(best, group), key), 4)})
        if not improved:
            break

    return {
        "profile": best,
        "loss": best_loss,
        "rates": best_rates,
        "in_band": in_band(best_rates, targets),
        "history": history,
    }


def profile_block(profile) -> dict:
    """A fitted Profile back into the `calibration` block a run_config takes.

    Only the stage bases are emitted when nothing else moved: a profile that
    restates every default would bury the two numbers that actually changed.
    """
    from ..minds.calibration import (
        DEFAULT_APPRAISAL_PARAMS, DEFAULT_CHOICE_PARAMS, DEFAULT_STAGE_BASES)
    from dataclasses import fields

    block: dict = {"stage_bases": {st: round(v, 4) for st, v in profile.stage_bases}}
    if tuple(profile.stage_bases) == tuple(DEFAULT_STAGE_BASES):
        block.pop("stage_bases")
    for group, default in (("appraisal", DEFAULT_APPRAISAL_PARAMS),
                           ("choice", DEFAULT_CHOICE_PARAMS)):
        obj = getattr(profile, group)
        diff = {f.name: getattr(obj, f.name) for f in fields(default)
                if f.name != "stage_weights"
                and getattr(obj, f.name) != getattr(default, f.name)}
        if diff:
            block[group] = diff
    return block


def compare(before: dict, after: dict, targets=TARGETS) -> list[dict]:
    """The before/after table PLAN 7.2 asks to be documented."""
    rows = []
    for name, (lo, hi, source) in targets.items():
        rows.append({
            "metric": name,
            "band": [lo, hi],
            "before": None if before.get(name) is None else round(before[name], 5),
            "after": None if after.get(name) is None else round(after[name], 5),
            "before_in_band": bool(before.get(name) is not None and lo <= before[name] <= hi),
            "after_in_band": bool(after.get(name) is not None and lo <= after[name] <= hi),
            "source": source,
        })
    return rows


def solve_stage_base(rows, profile, traced_stage_bases, stage: str,
                     target: float, *, metric: str, lo: float = 0.0,
                     hi: float = 10.0, tol: float = 1e-4, max_iter: int = 40):
    """The stage base that puts `metric` at `target`, by bisection.

    Used to DERIVE the demo profile's acceleration instead of guessing it: the
    demo exists to make a demo-scale run produce visible events, and the honest
    way to build it is to state the rate you want, solve for the one constant
    that produces it, and then publish the multiple. Monotone in the base (a
    higher threshold can only lower a gate probability), so bisection is exact
    to tolerance and needs no search space.
    """
    def rate(base):
        return evaluate(rows, _with(profile, ("stage_bases", stage), base),
                        traced_stage_bases).get(metric)

    if rate(lo) is None or rate(hi) is None:
        return None, None
    if rate(lo) < target:      # even the loosest threshold cannot reach it
        return lo, rate(lo)
    if rate(hi) > target:
        return hi, rate(hi)
    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        r = rate(mid)
        if abs(r - target) <= tol:
            return round(mid, 4), r
        if r > target:
            lo = mid
        else:
            hi = mid
    mid = round((lo + hi) / 2.0, 4)
    return mid, rate(mid)


def acceleration_multiples(reference_rates: dict, demo_rates: dict) -> dict:
    """How far a demo profile sits from the calibrated one, metric by metric.

    PLAN's own honesty requirement, generalised: market-research.md §6 already
    states the CTR multiple on screen, but CTR is not the only thing an
    accelerated profile distorts. Publishing one multiple and hiding four is
    how an accelerated number gets mistaken for a real one.
    """
    out = {}
    for name in TARGETS:
        ref, demo = reference_rates.get(name), demo_rates.get(name)
        if ref in (None, 0) or demo is None:
            continue
        lo, hi, _src = TARGETS[name]
        out[name] = {
            "reference": round(ref, 5), "demo": round(demo, 5),
            "multiple": round(demo / ref, 3),
            "band": [lo, hi],
            "demo_in_band": bool(lo <= demo <= hi),
        }
    return out
