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
    funnel_by_creative row for its own creative IS the creative's funnel."""
    table = []
    for spec_row in raw["experiment"]["spec"].get("creatives", ()):
        cid = spec_row["creative_id"]
        arm = f"c{cid}"
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
            "funnel_by_segment": results["funnel"].get(arm, {}),
        })
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
        }
    return {"arms": arms}


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
