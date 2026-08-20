"""Assembling `/eval` — the report, the plots, and the README that indexes them.

One rule everywhere in this file: a number appears with the thing that
justifies it. Bands carry their source, laws carry the threshold they had to
beat, and anything that could not be computed is named as missing rather than
quietly omitted. An eval that only prints its passes is marketing.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import calibrate, charts
from .contexts import repo_root


def eval_root() -> Path:
    return repo_root() / "eval"


def write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n")
    return path


# ---------------------------------------------------------------------------
# plots
# ---------------------------------------------------------------------------


def plot_frequency_response(law, out: Path) -> Path | None:
    rows = (law.series or {}).get("frequency_response") or []
    if not rows:
        return None
    pts = [(r["exposures"], r["p_click"]) for r in rows]
    peak = law.numbers.get("peak_at_exposure")
    c = charts.Chart(
        "F1 · frequency response rises, then wears out",
        subtitle=f"peak at exposure {peak}, then −{law.numbers['decay_from_peak']:.0%} "
                 f"by the last impression the 72h window can hold",
        x_label="exposures to the same creative", y_label="P(click | exposure)")
    c.axes([p[0] for p in pts], [p[1] for p in pts])
    c.line(pts, color=charts.SERIES[0], label="P(click)")
    c.note("adstock builds the rise; exposures_72h past wearout_free_exposures builds the fall")
    return c.save(out)


def plot_abstention(law, out: Path) -> Path | None:
    rows = (law.series or {}).get("abstention") or []
    if not rows:
        return None
    vals = [r["p_click"] for r in rows]
    c = charts.Chart(
        "F6 · abstention — what happens on a brand with no receipts",
        subtitle="an ungated model answers about an unknown brand the way it answers "
                 "about a familiar one",
        y_label="P(click | exposure)")
    c.axes([0], vals, x_categories=[r["case"] for r in rows])
    c.bars(vals, colors=[charts.SERIES[2], charts.SERIES[1], charts.SERIES[0]],
           labels=[r["case"] for r in rows],
           value_fmt=lambda v: f"{v:.2%}")
    c.note("gated = this engine: no path, no belief, no invented familiarity")
    return c.save(out)


def plot_discount_ladder(law, out: Path) -> Path | None:
    series = (law.series or {}).get("discount_ladder") or {}
    if not series:
        return None
    c = charts.Chart(
        "F3 · discount response is ordered by price sensitivity",
        subtitle="realised-price channel only; the perceived-offer channel is held fixed",
        x_label="discount depth", y_label="P(buy | cart)")
    all_y = [r["p_buy"] for rows in series.values() for r in rows]
    all_x = [r["depth"] for rows in series.values() for r in rows]
    c.axes(all_x, all_y)
    for i, (name, rows) in enumerate(sorted(series.items())):
        c.line([(r["depth"], r["p_buy"]) for r in rows], color=charts.SERIES[i],
               label=name.replace("_price_sensitivity", " sensitivity"))
    return c.save(out)


def plot_ctr_by_day(results: dict, out: Path, *, title: str, band=(0.005, 0.02)) -> Path | None:
    rows = [r for r in (results.get("ctr_by_day") or []) if r.get("ctr") is not None]
    if not rows:
        return None
    pts = [(r["tick"], r["ctr"]) for r in rows]
    c = charts.Chart(title, subtitle="daily CTR against the researched 0.5–2% band "
                                     "(market-research.md §1)",
                     x_label="simulated day", y_label="CTR")
    c.axes([p[0] for p in pts], [p[1] for p in pts] + [band[1]])
    c.band(band[0], band[1], "published band")
    c.line(pts, color=charts.SERIES[0], label="CTR")
    return c.save(out)


def plot_funnel(rates: dict, out: Path, *, title: str) -> Path | None:
    order = [("p_click", "CTR"), ("bounce_rate", "bounce"),
             ("p_cart_given_browse", "cart|browse"), ("p_buy_given_cart", "buy|cart"),
             ("visit_to_purchase", "visit→purchase")]
    vals, labels, colors = [], [], []
    for key, label in order:
        v = rates.get(key)
        if v is None:
            continue
        lo, hi, _src = calibrate.TARGETS[key]
        vals.append(v)
        labels.append(label)
        colors.append(charts.SERIES[2] if lo <= v <= hi else charts.SERIES[1])
    if not vals:
        return None
    c = charts.Chart(title, subtitle="green = inside the published band, red = outside",
                     y_label="rate")
    c.axes([0], vals, x_categories=labels)
    c.bars(vals, colors=colors, labels=labels, value_fmt=lambda v: f"{v:.1%}")
    return c.save(out)


def plot_calibration_before_after(rows, out: Path) -> Path | None:
    if not rows:
        return None
    c = charts.Chart("7.2 · calibration, before and after",
                     subtitle="each metric as a fraction of its own band "
                              "(1.0 = the band's midpoint)",
                     y_label="value ÷ band midpoint")
    labels = [r["metric"].replace("p_", "").replace("_", " ") for r in rows]
    def norm(v, band):
        mid = (band[0] + band[1]) / 2.0
        return None if v is None else v / mid
    before = [norm(r["before"], r["band"]) or 0.0 for r in rows]
    after = [norm(r["after"], r["band"]) or 0.0 for r in rows]
    c.axes([0], before + after + [1.5], x_categories=labels)
    n = len(rows)
    slot = (c.px1 - c.px0) / n
    for i in range(n):
        cx = c.px0 + slot * (i + 0.5)
        for j, (vals, color) in enumerate(((before, charts.SERIES[1]),
                                           (after, charts.SERIES[2]))):
            x = cx + (j - 0.5) * slot * 0.34
            y = c.sy(vals[i])
            c.parts.append(f'<rect x="{x - slot * 0.15:.1f}" y="{y:.1f}" '
                           f'width="{slot * 0.30:.1f}" height="{max(0.0, c.py1 - y):.1f}" '
                           f'fill="{color}" rx="2"/>')
        c.parts.append(f'<text x="{cx:.1f}" y="{c.py1 + 18}" text-anchor="middle" '
                       f'font-size="11" fill="{charts.MUTED}">{charts._esc(labels[i])}</text>')
    lo_y, hi_y = c.sy(rows[0]["band"][0] / ((rows[0]["band"][0] + rows[0]["band"][1]) / 2)), c.sy(1.0)
    c.parts.append(f'<line x1="{c.px0}" y1="{hi_y:.1f}" x2="{c.px1}" y2="{hi_y:.1f}" '
                   f'stroke="{charts.BAND_EDGE}" stroke-width="1.5" stroke-dasharray="5 3"/>')
    c.legend = [("before (Phase 6 defaults)", charts.SERIES[1]),
                ("after (reference profile)", charts.SERIES[2])]
    c.note("dashed line = band midpoint; bars near it are correctly calibrated")
    return c.save(out)


def plot_fatigue_separation(law, out: Path) -> Path | None:
    s = (law.series or {}).get("fatigue_ctr") or {}
    rep, rot = s.get("repetition") or [], s.get("rotation") or []
    if not rep or not rot:
        return None
    c = charts.Chart("F12 · same story wears out faster than a rotated one",
                     subtitle="identical impression budget and identical asset-level "
                              "wearout; only the shared CONCEPT differs",
                     x_label="simulated day", y_label="CTR")
    allpts = [(r["tick"], r["ctr"]) for r in rep + rot]
    c.axes([p[0] for p in allpts], [p[1] for p in allpts])
    c.line([(r["tick"], r["ctr"]) for r in rep], color=charts.SERIES[1],
           label="same concept")
    c.line([(r["tick"], r["ctr"]) for r in rot], color=charts.SERIES[0],
           label="concept rotation")
    return c.save(out)


def plot_twin(law, out: Path) -> Path | None:
    rows = [r for r in ((law.series or {}).get("twin") or [])
            if r.get("uplift_x") is not None]
    if not rows:
        return None
    vals = [r["uplift_x"] for r in rows]
    c = charts.Chart("F9 · a goal moves BUY far more than it moves CTR",
                     subtitle="paired twin arms, same seed, same ad — the twin branches "
                              "from the live arm's own log",
                     y_label="uplift, need-on ÷ need-off")
    c.axes([0], vals + [1.0], x_categories=[r["metric"] for r in rows])
    c.bars(vals, colors=[charts.SERIES[0], charts.SERIES[2]],
           labels=[r["metric"] for r in rows], value_fmt=lambda v: f"{v:.2f}×")
    c.note("relevance carries weight 1.2 at the CLICK gate and 2.2 at BUY — "
           "goal-gating is supposed to show up down the funnel")
    return c.save(out)


def plot_rank_agreement(study: dict, out: Path) -> Path | None:
    seeds = study.get("per_seed") or []
    if not seeds:
        return None
    first = seeds[0]
    oracle, sim = first["oracle"], first["sim"]
    c = charts.Chart("7.3 · rank agreement with the synthetic oracle",
                     subtitle=f"Spearman ρ = {study['mean_spearman']} mean over "
                              f"{len(seeds)} seeds (worst {study['worst_spearman']}); "
                              f"points are seed {first['seed']}",
                     x_label="oracle score (priors × claims + deal)",
                     y_label="simulated P(click)")
    c.axes(oracle, sim, y_from_zero=False)
    for i, (x, y) in enumerate(zip(oracle, sim)):
        c.parts.append(f'<circle cx="{c.sx(x):.1f}" cy="{c.sy(y):.1f}" r="5" '
                       f'fill="{charts.SERIES[0]}" fill-opacity="0.85"/>')
        c.parts.append(f'<text x="{c.sx(x):.1f}" y="{c.sy(y) - 10:.1f}" '
                       f'text-anchor="middle" font-size="10" fill="{charts.MUTED}">'
                       f'{study["creatives"][i]}</text>')
    c.note("construct validity: the oracle reads the same priors, not the same mechanism")
    return c.save(out)


def plot_evidence_hierarchy(law, out: Path) -> Path | None:
    rows = (law.series or {}).get("evidence_hierarchy") or []
    if not rows:
        return None
    vals = [r["delta_w"] for r in rows]
    c = charts.Chart("F8 · the evidence hierarchy is strict",
                     subtitle="equal event counts on an identical starting edge; "
                              "only the per-event weight differs",
                     y_label="Δw after 3 events")
    c.axes([0], vals, x_categories=[r["event"] for r in rows])
    c.bars(vals, colors=[charts.SERIES[0]] * len(vals),
           labels=[r["event"] for r in rows], value_fmt=lambda v: f"{v:.3f}")
    c.note("SAW is absent by construction: it carries pref_weight 0.0 — that is F7")
    return c.save(out)


# ---------------------------------------------------------------------------
# markdown
# ---------------------------------------------------------------------------


def render_markdown(report: dict) -> str:
    L = []
    A = L.append
    A("# /eval — Phase 7 calibration & evals\n")
    A("Generated by `make eval` (`python -m shopsim.eval report`). Every number "
      "here is reproduced from scratch by that command; nothing is hand-entered.\n")

    laws = report.get("laws") or []
    passed = sum(1 for x in laws if x["passed"])
    A(f"## Face-validity suite — {passed}/{len(laws)} passing\n")
    A("| law | tier | result | what it measured |")
    A("|---|---|---|---|")
    for x in laws:
        mark = "PASS" if x["passed"] else "**FAIL**"
        if x.get("never_drop"):
            mark += " · never-drop"
        head = _headline(x)
        A(f"| **{x['id']}** {x['name']} | {x['tier']} | {mark} | {head} |")
    A("")
    missing = report.get("laws_not_run") or []
    if missing:
        A("Not run in this pass (named rather than omitted): "
          + ", ".join(f"`{m['id']}` — {m['reason']}" for m in missing) + "\n")

    cal = report.get("calibration") or {}
    rows = cal.get("before_after") or []
    if rows:
        A("## 7.2 — aggregate calibration\n")
        A("| metric | published band | before | after | source |")
        A("|---|---|---|---|---|")
        for r in rows:
            def cell(v, ok):
                return "—" if v is None else (f"{v:.4f} ✓" if ok else f"{v:.4f} ✗")
            A(f"| `{r['metric']}` | {r['band'][0]:.3f}–{r['band'][1]:.3f} | "
              f"{cell(r['before'], r['before_in_band'])} | "
              f"{cell(r['after'], r['after_in_band'])} | {r['source']} |")
        A("")

    ra = report.get("rank_agreement") or {}
    if ra:
        A("## 7.3 — rank agreement\n")
        A(f"Spearman ρ **{ra.get('mean_spearman')}** (mean over {len(ra.get('seeds') or [])} "
          f"seeds, worst {ra.get('worst_spearman')}), threshold {ra.get('threshold')} — "
          f"{'PASS' if ra.get('passed') else 'FAIL'}.\n")
        A(f"*{ra.get('caveat', '')}*\n")

    plots = report.get("plots") or []
    if plots:
        A("## Plots\n")
        for p in plots:
            A(f"- [`{p}`]({p})")
        A("")
    runs = report.get("runs") or []
    if runs:
        A("## Runs behind the scenario tier\n")
        A("| label | arm | run | ticks × shoppers | wall |")
        A("|---|---|---|---|---|")
        for r in runs:
            A(f"| {r['label']} | {r['arm']} | `{r['run_id']}` | "
              f"{r.get('ticks','?')} × {r.get('population','?')} | {r['wall_s']}s |")
        A("")
    return "\n".join(L)


def _headline(x: dict) -> str:
    n = x.get("numbers") or {}
    def g(*keys):
        for k in keys:
            if n.get(k) is not None:
                return n[k]
        return None
    picks = {
        "F1": lambda: f"peak ×{g('p_click_peak')/g('p_click_first'):.2f} at exposure "
                      f"{g('peak_at_exposure')}, −{g('decay_from_peak'):.0%} from peak",
        "F2": lambda: f"cold {g('p_click_cold'):.4f} vs warm {g('p_click_warm'):.4f} "
                      f"({g('ratio'):.2f}×), cold relevance {g('cold_relevance')}",
        "F3": lambda: "uplift ordered low→high price sensitivity",
        "F5": lambda: f"bounce {g('bounce_rate_consistent')} → {g('bounce_rate_violating')} "
                      f"(Δ {g('bounce_delta')})",
        "F6": lambda: f"gated {g('gated_vs_ungated'):.2f}× the ungated strawman",
        "F7a": lambda: f"{g('learned_versions')} learned versions, causes "
                       f"{list((g('pooled_cause_kinds') or {}))}",
        "F7b": lambda: f"{g('exposures')} impressions, {g('clicks')} clicks, "
                       f"max drift {g('largest_preference_move')}",
        "F8": lambda: "CLICK < BROWSE < CART < BUY",
        "F9": lambda: f"CTR ×{g('ctr_uplift_x')}, BUY ×{g('buy_uplift_x')}",
        "F10": lambda: f"low-E moves {g('ratio'):.2f}× further",
        "F11": lambda: f"trust gap {g('trust_gap')}",
        "F12": lambda: f"decay {g('repetition_decay')} vs {g('rotation_decay')}",
        "F4": lambda: f"promo share +{g('promo_share_gain_pp')}pp cycle 1→last",
    }
    try:
        return picks.get(x["id"], lambda: "")() or ""
    except (TypeError, ZeroDivisionError, KeyError):
        return ""
