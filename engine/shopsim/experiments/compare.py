"""Cross-arm comparison reports (Phase 4, CONTRACT v3.4-draft).

comparison.json = the C3-style merge (funnel keyed by every arm, the
export-fixtures pattern) + a type-specific section computed from the per-arm
results.json payloads. Cross-arm deltas live HERE, not in results.json —
per-run results stay single-arm (violations.bounce_delta remains Phase 6).
"""

from __future__ import annotations

import json
from pathlib import Path

from ..runner.config import RunConfig
from ..runner.runstore import RunStore


def _bought_total(results: dict, arm: str) -> int:
    segments = results["funnel"].get(arm, {})
    return sum(counts.get("BOUGHT", 0) for counts in segments.values())


def _overall_ctr(row: dict) -> float | None:
    saw = row.get("SAW", 0)
    return round(row.get("CLICKED", 0) / saw, 5) if saw else None


def _ad_section(raw: dict, results_by_arm: dict) -> dict:
    """One arm per creative (arm name c<creative_id>): the arm's
    funnel_by_creative row for its own creative IS the creative's funnel.

    Shared market (v3.6-draft): every creative lives on the single "market"
    arm, so all N rows come out of one results payload. funnel_by_segment is
    then the whole market's segment funnel, not the creative's — it is shared
    by every row, so the per-creative comparison reads the creative columns."""
    spec = raw["experiment"]["spec"]
    shared = bool(spec.get("market", {}).get("shared"))
    table = []
    for spec_row in spec.get("creatives", ()):
        cid = spec_row["creative_id"]
        arm = "market" if shared else f"c{cid}"
        results = results_by_arm.get(arm)
        if results is None:
            continue
        row = results.get("funnel_by_creative", {}).get(str(cid), {})
        table.append({
            "creative": cid,
            "arm": arm,
            "SAW": row.get("SAW", 0),
            "CLICKED": row.get("CLICKED", 0),
            "BROWSED": row.get("BROWSED", 0),
            "BOUNCED": row.get("BOUNCED", 0),
            "CARTED": row.get("CARTED", 0),
            "BOUGHT": row.get("BOUGHT", 0),
            "ctr": _overall_ctr(row),
            "revenue": (results.get("revenue", {})
                        .get("by_creative", {}).get(str(cid))),
            "funnel_by_segment": results["funnel"].get(arm, {}),
        })
    if shared:
        return {"creatives": table, "shared_market": True,
                "impressions_by_creative_by_day":
                    next(iter(results_by_arm.values()), {})
                    .get("ctr_by_creative_by_day", [])}
    return {"creatives": table}


def _page_ab_section(raw: dict, results_by_arm: dict) -> dict:
    spec = raw["experiment"]["spec"]
    page_a, page_b = (int(p) for p in spec["page_ids"])
    results = next(iter(results_by_arm.values()))
    by_page = results.get("funnel_by_page", {})
    rows = {}
    for page in (page_a, page_b):
        counts = by_page.get(str(page), {})
        rows[str(page)] = {**counts}
    rate_a = rows[str(page_a)].get("bounce_rate")
    rate_b = rows[str(page_b)].get("bounce_rate")
    return {
        "pages": rows,
        # bounce_delta = variant B − variant A (spec order): the violation
        # exhibit expects the violating page listed second and a positive delta
        "bounce_delta": (round(rate_b - rate_a, 5)
                         if rate_a is not None and rate_b is not None else None),
    }


def _pricing_section(raw: dict, results_by_arm: dict) -> dict:
    spec = raw.get("experiment", {}).get("spec", {})
    levels = sorted(float(x) for x in spec.get("discount_levels", ()))
    arms = {}
    for arm, results in results_by_arm.items():
        traj = results.get("reference_price_trajectory", [])
        means = [r["mean_reference_price"] for r in traj
                 if r.get("mean_reference_price") is not None]
        arms[arm] = {
            "reference_price_trajectory": traj,
            "first_mean_reference_price": means[0] if means else None,
            "last_mean_reference_price": means[-1] if means else None,
            "reference_price_drift": (round(means[-1] - means[0], 4)
                                      if len(means) >= 2 else None),
            "bought_total": _bought_total(results, arm),
            "revenue_total": results.get("revenue", {}).get("total"),
        }
    out: dict = {"arms": arms}
    if levels:
        # v3.6-draft ladder: name the depths and pick the revenue winner here,
        # so the verdict is computed once from engine data rather than
        # re-derived by every reader.
        ladder = [{"level": lv, "arm": f"d{round(lv * 100)}"} for lv in levels]
        for row in ladder:
            a = arms.get(row["arm"], {})
            row["revenue_total"] = a.get("revenue_total")
            row["bought_total"] = a.get("bought_total")
            row["reference_price_drift"] = a.get("reference_price_drift")
            # v3.7-draft: per-creative reaction, so "which ad survived the
            # discount best" is answerable. Everything here already exists in
            # the arm's results — no new engine state.
            res = results_by_arm.get(row["arm"], {})
            by_creative = res.get("funnel_by_creative", {})
            revenue_by = res.get("revenue", {}).get("by_creative", {})
            row["creatives"] = [
                {"creative": int(cid),
                 **{k: counts.get(k, 0) for k in
                    ("SAW", "CLICKED", "BROWSED", "CARTED", "BOUGHT")},
                 "ctr": _overall_ctr(counts),
                 "revenue": revenue_by.get(cid, 0.0)}
                for cid, counts in sorted(by_creative.items(), key=lambda kv: int(kv[0]))
            ]

        # every rung reads against the no-discount control, which the launcher
        # always includes — "how would these ads have done at full price"
        control = next((r for r in ladder if r["level"] == 0.0), None)
        if control is not None:
            base_rev = control.get("revenue_total")
            base_by = {c["creative"]: c for c in control["creatives"]}
            for row in ladder:
                rev, bought = row.get("revenue_total"), row.get("bought_total")
                row["vs_control"] = {
                    "control_arm": control["arm"],
                    "revenue_delta": (round(rev - base_rev, 2)
                                      if rev is not None and base_rev is not None else None),
                    "revenue_lift_pct": (round(100 * (rev / base_rev - 1), 1)
                                         if rev is not None and base_rev else None),
                    "bought_delta": (bought - control["bought_total"]
                                     if bought is not None
                                     and control.get("bought_total") is not None else None),
                    "by_creative": {
                        str(c["creative"]): {
                            "ctr_delta": (round(c["ctr"] - base_by[c["creative"]]["ctr"], 5)
                                          if c.get("ctr") is not None
                                          and base_by.get(c["creative"], {}).get("ctr") is not None
                                          else None),
                            "revenue_delta": round(
                                c["revenue"] - base_by.get(c["creative"], {}).get("revenue", 0.0), 2),
                            "bought_delta": (c["BOUGHT"]
                                             - base_by.get(c["creative"], {}).get("BOUGHT", 0)),
                        }
                        for c in row["creatives"]
                    },
                }

        earning = [r for r in ladder if r.get("revenue_total") is not None]
        best = max(earning, key=lambda r: r["revenue_total"]) if earning else None
        out["ladder"] = ladder
        out["control_level"] = 0.0 if control is not None else None
        out["best_level"] = best["level"] if best else None
        out["best_arm"] = best["arm"] if best else None
        out["best_vs_control"] = (best.get("vs_control") if best else None)
    return out


def _scenario_section(raw: dict, results_by_arm: dict) -> dict:
    return {"arms": {
        arm: {"goal_stats": results["goal_stats"],
              "bought_total": _bought_total(results, arm)}
        for arm, results in results_by_arm.items()
    }}


_SECTIONS = {
    "ad_test": _ad_section,
    "pricing": _pricing_section,
    "page_ab": _page_ab_section,
    "scenario": _scenario_section,
}


def build_comparison(raw: dict, results_by_arm: dict[str, dict]) -> dict:
    exp = raw.get("experiment", {})
    etype = exp.get("type", "unknown")
    merged_funnel: dict = {}
    for arm, results in results_by_arm.items():
        merged_funnel.update(results.get("funnel", {}))
    section = _SECTIONS.get(etype)
    return {
        "experiment": {"type": etype, "name": exp.get("name"),
                       "arms": sorted(results_by_arm)},
        "funnel": merged_funnel,
        "goal_stats": {arm: r.get("goal_stats") for arm, r in
                       sorted(results_by_arm.items())},
        etype: section(raw, results_by_arm) if section else {},
    }


def compare_dir(exp_dir: Path | str) -> dict:
    """Standalone compare: rebuild comparison.json for an already-run
    experiment dir from the runs registry (latest run per arm)."""
    exp_dir = Path(exp_dir)
    cfg = RunConfig.load(exp_dir / "run_config.json")
    store = RunStore(cfg.root)
    results_by_arm = {}
    for arm in cfg.arms:
        row = store.latest_for(cfg.label, arm.name)
        results_by_arm[arm.name] = json.loads(
            (Path(row["dir"]) / "results.json").read_text())
    return build_comparison(cfg.raw, results_by_arm)
