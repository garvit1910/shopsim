"""CLI: python -m shopsim.eval <analytic|fit|scenarios|rank|report|all> ...

    analytic   [--profile P] [--seeds 7,11,...] [--size N]
    fit        --trace PATH [--from-profile P] [--out eval/profiles/X.json]
    scenarios  [--only F5,F9] [--profile P]
    rank       [--profile P] [--seeds ...]
    report     [--profile P]          assemble /eval from what is on disk
    all        [--profile P]          the `make eval` pipeline, in order

`analytic`, `rank` and `report` never touch the database. `scenarios` runs real
simulations and is the only slow command; it prints its own wall clock so a
`make eval` that takes an hour says why.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import calibrate, contexts, harness, laws, oracle, report, trace

RESULTS = "results"
PLOTS = "plots"

# scenario key -> (config stem, arms to run, branch arms)
SCENARIOS: dict[str, dict] = {
    "F5": {"config": "f5-violation", "arms": ["split"]},
    "F9": {"config": "f9-twin", "arms": ["need_on"], "branch": ["need_off"]},
    "F12": {"config": "f12-fatigue", "arms": ["same_concept", "rotation"]},
    "F7b": {"config": "f7b-exposure", "arms": ["exposure_only"]},
    "F4": {"config": "f4-promo", "arms": ["promo"]},
    "F11": {"config": "f11-quality", "arms": ["quality"], "quality_pair": True},
}


def _results_dir() -> Path:
    return report.eval_root() / RESULTS


def _plots_dir() -> Path:
    return report.eval_root() / PLOTS


def _load(name: str):
    p = _results_dir() / f"{name}.json"
    return json.loads(p.read_text()) if p.exists() else None


# ---------------------------------------------------------------------------


def cmd_analytic(args) -> int:
    profile = contexts.Profile.from_block(
        args.profile, harness.load_profile(args.profile) if args.profile else None)
    seeds = [int(s) for s in (args.seeds or "7,11,23").split(",")]
    view = contexts.catalog_view(args.catalog)

    per_seed, results = [], {}
    for seed in seeds:
        pop = contexts.population(seed, args.size, stage_bases=profile.stage_bases)
        stim = view.facts(args.stimulus)
        row = {"seed": seed,
               "funnel": {k: round(v, 6) for k, v in
                          contexts.funnel_mix(pop, stim, profile).items()}}
        for fn in (laws.analytic_f1_frequency_response, laws.analytic_f2_cold_gate,
                   laws.analytic_f3_discount_ordering, laws.analytic_f6_abstention):
            r = fn(pop, view, profile)
            row.setdefault("laws", {})[r.id] = r.passed
            results.setdefault(r.id, []).append(r)
        per_seed.append(row)

    # unit-level laws need no population at all
    for fn in (laws.analytic_f8_evidence_hierarchy, laws.analytic_f10_confidence_differential):
        r = fn()
        results.setdefault(r.id, []).append(r)

    # Report the FIRST seed's detail (for plots) but pass a law only if it holds
    # on every seed — a law that survives one lucky population is not a law.
    out = []
    for lid, runs in sorted(results.items()):
        head = runs[0]
        out.append({**head.to_dict(),
                    "passed": all(r.passed for r in runs),
                    "seeds_checked": len(runs),
                    "seeds_passed": sum(1 for r in runs if r.passed)})
    payload = {"profile": args.profile or "module defaults", "seeds": seeds,
               "population_size": args.size, "catalog": args.catalog,
               "per_seed": per_seed, "laws": out}
    report.write_json(_results_dir() / "analytic.json", payload)
    for r in out:
        print(f"  {'PASS' if r['passed'] else 'FAIL'}  {r['id']:<4} {r['name']} "
              f"({r['seeds_passed']}/{r['seeds_checked']} seeds)")
    return 0 if all(r["passed"] for r in out) else 1


def cmd_fit(args) -> int:
    header, rows = trace.load(args.trace)
    traced_bases = tuple(header["stage_bases"].items())
    if args.pref_half_life_days or args.violation_min_strength is not None:
        rows = trace.retrofit(
            rows,
            traced_pref_half_life_days=args.traced_pref_half_life_days,
            pref_half_life_days=args.pref_half_life_days,
            violation_min_strength=args.violation_min_strength)
    start = contexts.Profile.from_block(
        args.from_profile or "start",
        harness.load_profile(args.from_profile) if args.from_profile else None)
    before = calibrate.evaluate(rows, start, traced_bases)
    res = calibrate.fit(rows, start, traced_bases)
    block = calibrate.profile_block(res["profile"])
    print(json.dumps({"before": {k: round(v, 5) for k, v in before.items() if v is not None},
                      "after": {k: round(v, 5) for k, v in res["rates"].items() if v is not None},
                      "in_band": res["in_band"], "loss": res["loss"],
                      "block": block}, indent=1))
    if args.out:
        Path(args.out).write_text(json.dumps(
            {"name": Path(args.out).stem, "calibration": block}, indent=2) + "\n")
        print(f"written: {args.out}", file=sys.stderr)
    return 0


# The engine as it stood before Phase 7, for the before/after table. Two of the
# three changes are exactly reconstructible from a current trace (the recency
# half-life is invertible, the stage base is a parameter); the violation floor
# is NOT, because sub-threshold violations were never recorded once the floor
# existed. That asymmetry is reported rather than papered over.
PRE_PHASE7 = {"stage_bases_BUY": 3.2, "pref_half_life_days": 3.0}

# The pre-Phase-7 engine MEASURED, not reconstructed. Model-implied rates over
# the decision trace of the baseline reference run (r048-eval-reference, 300
# shoppers x 24 days, seed 101, 2026-08-20) on the engine as it stood before any
# Phase-7 change: 3-day preference recency, no violation floor, (w=0,E=0) cold
# start, stage_bases.BUY 3.2.
#
# These are hardcoded because they are a measurement of code that no longer
# exists — re-running cannot reproduce them, and a partial reconstruction from a
# current trace would be worse than a cited one: the violation floor in
# particular is NOT invertible, because sub-threshold violations stopped being
# recorded the moment the floor existed. Reconstructing anyway produced a
# "before" bounce rate of 0.518 against a real one of 0.599, i.e. it flattered
# the starting point by hiding the single largest fault.
BASELINE_MEASURED = {
    "run": "r048-eval-reference-reference",
    "measured_on": "2026-08-20",
    "engine": "pre-Phase-7: pref recency 3d (shared with fatigue), no violation "
              "floor, cold start (w=0, E=0), stage_bases.BUY 3.2",
    "rates": {"p_click": 0.007707, "bounce_rate": 0.599125,
              "p_cart_given_browse": 0.123359, "p_buy_given_cart": 0.175218,
              "visit_to_purchase": 0.008665},
    "context_health": {"pref_recency_mean": 0.230, "violation_share": 0.853,
                       "trust_share": 0.021},
}


def cmd_calibrate(args) -> int:
    """7.2 — the before/after table, from the reference run's own trace."""
    run_dir = Path(args.run) if args.run else _reference_run_dir()
    if run_dir is None or not (run_dir / trace.TRACE_FILENAME).exists():
        print("error: no traced reference run found — run "
              "`shopsim.runner run --config eval/configs/reference.json "
              "--trace-decisions` first", file=sys.stderr)
        return 2
    header, rows = trace.load(run_dir / trace.TRACE_FILENAME)
    traced_bases = tuple(header["stage_bases"].items())
    after_profile = contexts.Profile.from_block(
        args.profile, harness.load_profile(args.profile))

    before_profile = calibrate._with(
        after_profile, ("stage_bases", "BUY"), PRE_PHASE7["stage_bases_BUY"])
    before_rows = trace.retrofit(
        rows,
        traced_pref_half_life_days=header.get("pref_recency_half_life_s", 2_592_000) / 86_400,
        pref_half_life_days=PRE_PHASE7["pref_half_life_days"])

    reconstructed = calibrate.evaluate(before_rows, before_profile, traced_bases)
    before = dict(BASELINE_MEASURED["rates"])
    after = calibrate.evaluate(rows, after_profile, traced_bases)
    realised = trace.score(rows, appraisal_params=after_profile.appraisal,
                           choice_params=after_profile.choice,
                           stage_bases=after_profile.stage_bases,
                           traced_stage_bases=traced_bases)

    # the demo profile: solve its CLICK base for a STATED target, then publish
    # what that acceleration does to every metric, not just to CTR
    demo_block = harness.load_profile("demo")
    demo_profile = contexts.Profile.from_block("demo", demo_block)
    solved, solved_rate = calibrate.solve_stage_base(
        rows, after_profile, traced_bases, "CLICK", args.demo_ctr,
        metric="p_click")
    if solved is not None:
        demo_profile = calibrate._with(demo_profile, ("stage_bases", "CLICK"), solved)
    demo_rates = calibrate.evaluate(rows, demo_profile, traced_bases)

    payload = {
        "money": _money(run_dir),
        "reference_run_dir": str(run_dir),
        "reference_run_id": run_dir.name,
        "profile": args.profile,
        "before_after": calibrate.compare(before, after),
        "before": {k: round(v, 6) for k, v in before.items() if v is not None},
        "before_source": BASELINE_MEASURED,
        "before_reconstructed": {k: round(v, 6) for k, v in reconstructed.items()
                                 if v is not None},
        "after": {k: round(v, 6) for k, v in after.items() if v is not None},
        "realised": {k: round(v, 6) for k, v in realised["realised"].items()
                     if v is not None},
        "decisions": realised["n"],
        "in_band": calibrate.in_band(after),
        "loss": calibrate.loss(after)[0],
        "pre_phase7_reconstruction": {
            **PRE_PHASE7,
            "note": "A partial cross-check, NOT the before column. Two of the "
                    "three changes are invertible from a current trace (the "
                    "recency half-life, because recency = 2^(-age/half_life), "
                    "and the BUY stage base, because it is a parameter). The "
                    "violation floor is not: sub-threshold violations stopped "
                    "being recorded once the floor existed. Reconstruction "
                    "therefore understates how bad the starting point was — it "
                    "reports bounce 0.518 where the engine actually measured "
                    "0.599 — which is why `before` cites the measurement in "
                    "before_source instead."},
        "historical_runs": {
            "r027-market-demo": {"profile": "stage_bases.CLICK=6.0 (default)",
                                 "ctr": 0.0067, "bounce": 0.667,
                                 "cart_given_browse": 0.067, "bought": 0},
            "r039-market-20260819": {"profile": "stage_bases.CLICK=2.0 (old demo)",
                                     "ctr": 0.2797, "bounce": 0.636,
                                     "cart_given_browse": 0.1198, "bought": 25,
                                     "blended_roas": 46.4},
        },
        "demo_profile": {
            "target_ctr": args.demo_ctr,
            "solved_click_base": solved,
            "achieved_p_click": None if solved_rate is None else round(solved_rate, 6),
            "committed_click_base": demo_block.get("stage_bases", {}).get("CLICK"),
            "multiples": calibrate.acceleration_multiples(after, demo_rates),
            "note": "Only the CLICK threshold moves. BROWSE, CART and BUY stay at "
                    "their calibrated values, so everything below the click is "
                    "still the certified funnel.",
        },
    }
    report.write_json(_results_dir() / "calibration.json", payload)
    for row in payload["before_after"]:
        mark = "OK " if row["after_in_band"] else "OUT"
        print(f"  {mark} {row['metric']:<22} {row['before']} -> {row['after']}  "
              f"band {row['band']}")
    print(f"  loss {payload['loss']}  ({realised['n']['creative_decisions']} creative / "
          f"{realised['n']['page_decisions']} page decisions)")
    if solved is not None:
        print(f"  demo CLICK base solved to {solved} for a {args.demo_ctr:.0%} target CTR")
    return 0 if payload["loss"] == 0 else 1


# web/lib/economics.ts — the ONE assumed number in the money layer, kept in
# sync here so the engine-side check and the dashboard price impressions the
# same way. Everything else (revenue, purchases) is simulated.
CPM_USD = 13.88
ROAS_BAND = (1.5, 4.0)


def _money(run_dir: Path) -> dict:
    """Blended ROAS — the consistency check that ties the funnel to the money.

    Reported, never fitted. It is fully determined by metrics already in band
    (impressions x CTR x conversion x basket), so hitting it independently would
    be double-counting; what makes it worth printing is that getting the RATES
    right drags ROAS from ~46x to the right order of magnitude on its own.

    Honest about its own noise: a correctly calibrated demo-scale run produces
    single-digit purchases, so this estimate has an enormous interval. It is
    evidence about the ORDER OF MAGNITUDE, not a measurement to two decimals.
    """
    path = run_dir / "results.json"
    if not path.exists():
        return {}
    res = json.loads(path.read_text())
    impressions = sum(c.get("SAW", 0) for segs in res.get("funnel", {}).values()
                      for c in segs.values())
    buys = sum(c.get("BOUGHT", 0) for segs in res.get("funnel", {}).values()
               for c in segs.values())
    revenue = (res.get("revenue") or {}).get("total", 0.0)
    spend = round(impressions * CPM_USD / 1000.0, 2)
    roas = round(revenue / spend, 3) if spend else None
    lo, hi = ROAS_BAND
    return {
        "impressions": impressions, "purchases": buys, "revenue": revenue,
        "cpm_usd": CPM_USD, "spend": spend, "blended_roas": roas,
        "band": [lo, hi],
        "in_band": bool(roas is not None and lo <= roas <= hi),
        "source": "market-research.md S5 — Meta e-commerce median CPM $13.88; "
                  "real-world blended e-commerce ROAS 1.5-4x",
        "note": f"Derived, not fitted. Based on {buys} simulated purchases, so "
                f"the interval is wide — read the order of magnitude, not the "
                f"decimals. The pre-Phase-7 demo profile put this at ~46x.",
    }


def _reference_run_dir():
    """The newest completed run of the reference config that carries a trace."""
    from ..runner.runstore import RunStore

    root = contexts.repo_root()
    try:
        rows = [r for r in RunStore(root).rows() if r["label"] == "eval-reference"]
    except Exception:  # noqa: BLE001 — no registry yet is not an error here
        rows = []
    for row in sorted(rows, key=lambda r: -int(r["run_index"])):
        d = Path(row["dir"])
        if (d / trace.TRACE_FILENAME).exists() and (d / "results.json").exists():
            return d
    return None


def cmd_rank(args) -> int:
    profile = contexts.Profile.from_block(
        args.profile, harness.load_profile(args.profile) if args.profile else None)
    seeds = tuple(int(s) for s in (args.seeds or "11,23,37,53,71").split(","))
    study = oracle.rank_agreement(seeds=seeds, size=args.size, profile=profile,
                                  catalog=args.catalog)
    report.write_json(_results_dir() / "rank_agreement.json", study)
    print(f"  spearman mean {study['mean_spearman']} worst {study['worst_spearman']} "
          f"over {len(seeds)} seeds — {'PASS' if study['passed'] else 'FAIL'}")
    return 0 if study["passed"] else 1


def cmd_scenarios(args) -> int:
    only = {s.strip() for s in args.only.split(",")} if args.only else set(SCENARIOS)
    specs = report.eval_root() / "specs"
    built = report.eval_root() / "configs" / "built"
    out = _load("scenarios") or {"runs": {}}
    started_all = time.perf_counter()

    for key in [k for k in SCENARIOS if k in only]:
        meta = SCENARIOS[key]
        cfg_src = specs / f"{meta['config']}.json"
        print(f"[{key}] {meta['config']}", flush=True)
        if meta.get("quality_pair"):
            harness.quality_catalogs(0.85, 0.35)
            for tag, catalog in (("good", "eval/fixtures/quality-good"),
                                 ("bad", "eval/fixtures/quality-bad")):
                cfg = harness.materialize(
                    cfg_src, args.profile, built,
                    label=f"{meta['config']}-{tag}",
                    overrides={"catalog_dir": catalog})
                o = harness.run_config(cfg, trace=args.trace)
                out["runs"][f"{key}:{tag}"] = _outcome(o)
                print(f"   {tag}: {o.run_id} in {o.wall_s}s", flush=True)
            continue

        cfg = harness.materialize(cfg_src, args.profile, built)
        for arm in meta["arms"]:
            o = harness.run_config(cfg, arm=arm, trace=args.trace)
            out["runs"][f"{key}:{arm}"] = _outcome(o)
            print(f"   {arm}: {o.run_id} in {o.wall_s}s", flush=True)
        for arm in meta.get("branch", ()):
            o = harness.branch_arm(cfg, arm)
            out["runs"][f"{key}:{arm}"] = _outcome(o)
            print(f"   {arm} (branch): {o.run_id} in {o.wall_s}s", flush=True)

    out["total_wall_s"] = round(time.perf_counter() - started_all, 1)
    report.write_json(_results_dir() / "scenarios.json", out)
    print(f"scenarios done in {out['total_wall_s']}s")
    return 0


def _outcome(o) -> dict:
    m = o.results.get("run_manifest", {})
    return {"label": o.label, "arm": o.arm, "run_id": o.run_id, "dir": str(o.run_dir),
            "wall_s": o.wall_s, "ticks": m.get("ticks"), "seed": m.get("seed")}


def cmd_report(args) -> int:
    analytic = _load("analytic") or {}
    scenarios = _load("scenarios") or {"runs": {}}
    rank = _load("rank_agreement") or {}
    plots_dir = _plots_dir()
    plots: list[str] = []

    law_rows = list(analytic.get("laws") or [])
    not_run: list[dict] = []

    # rebuild the analytic LawResults we need for plots
    profile = contexts.Profile.from_block(
        args.profile, harness.load_profile(args.profile) if args.profile else None)
    pop = contexts.population(int((analytic.get("seeds") or [7])[0]),
                              int(analytic.get("population_size") or 300),
                              stage_bases=profile.stage_bases)
    view = contexts.catalog_view(analytic.get("catalog") or "fixtures/demo-brand")
    f1 = laws.analytic_f1_frequency_response(pop, view, profile)
    f3 = laws.analytic_f3_discount_ordering(pop, view, profile)
    f6 = laws.analytic_f6_abstention(pop, view, profile)
    f8 = laws.analytic_f8_evidence_hierarchy()
    for path in (report.plot_frequency_response(f1, plots_dir / "f1_frequency_response.svg"),
                 report.plot_discount_ladder(f3, plots_dir / "f3_discount_ladder.svg"),
                 report.plot_abstention(f6, plots_dir / "f6_abstention.svg"),
                 report.plot_evidence_hierarchy(f8, plots_dir / "f8_evidence_hierarchy.svg")):
        if path:
            plots.append(f"{PLOTS}/{path.name}")

    runs, results_by_key = [], {}
    for key, row in sorted(scenarios.get("runs", {}).items()):
        rdir = Path(row["dir"])
        if not (rdir / "results.json").exists():
            not_run.append({"id": key.split(":")[0], "reason": f"no results.json in {row['run_id']}"})
            continue
        results_by_key[key] = harness.load_results(rdir)
        # population size is not a manifest field; the run's own progress
        # snapshot is the authority for the shape it actually ran at
        pop = None
        prog = rdir / "progress.json"
        if prog.exists():
            try:
                pop = json.loads(prog.read_text()).get("population_size")
            except (OSError, ValueError):
                pop = None
        runs.append({**row, "population": pop})

    law_rows += _scenario_laws(results_by_key, scenarios, not_run, plots, plots_dir)

    # F7a audits every run the suite produced, plus the committed golden
    audited = dict(results_by_key)
    golden = contexts.repo_root() / "fixtures" / "golden-run" / "results.json"
    if golden.exists():
        audited["golden-run"] = json.loads(golden.read_text())
    law_rows.append(laws.audit_f7a_no_learning_from_exposure(audited).to_dict())

    cal = _load("calibration") or {}
    if cal.get("before_after"):
        p = report.plot_calibration_before_after(
            cal["before_after"], plots_dir / "calibration_before_after.svg")
        if p:
            plots.append(f"{PLOTS}/{p.name}")
        if cal.get("after"):
            p = report.plot_funnel(cal["after"], plots_dir / "funnel_reference.svg",
                                   title="Reference profile · funnel against published bands")
            if p:
                plots.append(f"{PLOTS}/{p.name}")
    ref_results = cal.get("reference_run_dir")
    if ref_results and (Path(ref_results) / "results.json").exists():
        res = harness.load_results(ref_results)
        p = report.plot_ctr_by_day(res, plots_dir / "ctr_by_day_reference.svg",
                                   title="Reference profile · CTR by simulated day")
        if p:
            plots.append(f"{PLOTS}/{p.name}")

    if rank:
        p = report.plot_rank_agreement(rank, plots_dir / "rank_agreement.svg")
        if p:
            plots.append(f"{PLOTS}/{p.name}")

    order = {lid: i for i, lid in enumerate(
        ["F1", "F2", "F3", "F4", "F5", "F6", "F7a", "F7b", "F8", "F9", "F10", "F11", "F12"])}
    law_rows.sort(key=lambda x: order.get(x["id"], 99))

    payload = {"laws": law_rows, "laws_not_run": not_run, "calibration": cal,
               "rank_agreement": rank, "plots": sorted(plots), "runs": runs,
               "profile": args.profile}
    report.write_json(_results_dir() / "eval_report.json", payload)
    (report.eval_root() / "README.md").write_text(report.render_markdown(payload))
    ok = sum(1 for x in law_rows if x["passed"])
    print(f"\n{ok}/{len(law_rows)} laws passing; {len(plots)} plots; "
          f"eval/README.md + eval/results/eval_report.json written")
    for x in law_rows:
        if not x["passed"]:
            print(f"  FAIL {x['id']} {x['name']}"
                  + ("  (NEVER-DROP)" if x.get("never_drop") else ""))
    return 0 if all(x["passed"] for x in law_rows) else 1


def _scenario_laws(res: dict, scenarios: dict, not_run: list, plots: list,
                   plots_dir: Path) -> list[dict]:
    rows = []

    def need(*keys):
        missing = [k for k in keys if k not in res]
        return None if missing else [res[k] for k in keys]

    got = need("F5:split")
    if got:
        rows.append(laws.scenario_f5_violation_bounce(
            got[0], page_a=4000001, page_b=4000002).to_dict())
    else:
        not_run.append({"id": "F5", "reason": "no f5-violation run on disk"})

    got = need("F9:need_on", "F9:need_off")
    if got:
        law = laws.scenario_f9_maya_law(got[0], got[1], arm_on="need_on", arm_off="need_off")
        rows.append(law.to_dict())
        p = report.plot_twin(law, plots_dir / "f9_twin.svg")
        if p:
            plots.append(f"{PLOTS}/{p.name}")
    else:
        not_run.append({"id": "F9", "reason": "twin pair incomplete (needs both arms)"})

    got = need("F12:same_concept", "F12:rotation")
    if got:
        law = laws.scenario_f12_fatigue_separation(got[0], got[1])
        rows.append(law.to_dict())
        p = report.plot_fatigue_separation(law, plots_dir / "f12_fatigue_separation.svg")
        if p:
            plots.append(f"{PLOTS}/{p.name}")
    else:
        not_run.append({"id": "F12", "reason": "needs both fatigue arms"})

    got = need("F7b:exposure_only")
    if got:
        rows.append(laws.scenario_f7b_heavy_exposure(got[0]).to_dict())
    else:
        not_run.append({"id": "F7b", "reason": "no heavy-exposure run on disk"})

    got = need("F11:good", "F11:bad")
    if got:
        rows.append(laws.scenario_f11_experience_loop(got[0], got[1]).to_dict())
    else:
        not_run.append({"id": "F11", "reason": "needs both latent-quality arms"})

    got = need("F4:promo")
    if got:
        row = scenarios["runs"]["F4:promo"]
        cycles = _promo_cycles()
        rows.append(laws.scenario_f4_promo_addiction(
            got[0], cycles,
            buys=laws.buys_by_tick(Path(row["dir"]) / "events.jsonl")).to_dict())
    else:
        not_run.append({"id": "F4", "reason": "no promo run on disk"})
    return rows


def _promo_cycles():
    raw = json.loads((contexts.repo_root() / "fixtures" / "demo-brand" /
                      "promo_schedule.json").read_text())
    out = []
    for promo in raw["product_promos"]:
        for c in promo["cycles"]:
            out.append((c["cycle"], c["start_tick"], c["end_tick"], c["discount_pct"]))
    return out


def cmd_all(args) -> int:
    rc = 0
    print("== analytic tier ==")
    rc |= cmd_analytic(args)
    print("== calibration (7.2) ==")
    rc |= cmd_calibrate(args)
    print("== rank agreement ==")
    rc |= cmd_rank(args)
    print("== scenario tier (real runs; this is the slow part) ==")
    rc |= cmd_scenarios(args)
    print("== report ==")
    rc |= cmd_report(args)
    return rc


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="shopsim.eval")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--profile", default="reference")
        sp.add_argument("--seeds")
        sp.add_argument("--size", type=int, default=300)
        sp.add_argument("--catalog", default="fixtures/demo-brand")
        sp.add_argument("--stimulus", type=int, default=2000003)

    for name, fn in (("analytic", cmd_analytic), ("rank", cmd_rank),
                     ("calibrate", cmd_calibrate),
                     ("report", cmd_report), ("all", cmd_all)):
        sp = sub.add_parser(name)
        common(sp)
        sp.add_argument("--run", help="traced reference run dir (default: newest)")
        sp.add_argument("--demo-ctr", type=float, default=0.05,
                        help="target CTR the demo profile is solved for")
        if name in ("scenarios", "all"):
            sp.add_argument("--only")
            sp.add_argument("--trace", action="store_true")
        sp.set_defaults(fn=fn)

    sp = sub.add_parser("scenarios")
    common(sp)
    sp.add_argument("--only")
    sp.add_argument("--trace", action="store_true")
    sp.set_defaults(fn=cmd_scenarios)

    sp = sub.add_parser("fit")
    sp.add_argument("--trace", required=True)
    sp.add_argument("--from-profile")
    sp.add_argument("--out")
    sp.add_argument("--pref-half-life-days", type=float)
    sp.add_argument("--traced-pref-half-life-days", type=float, default=3.0)
    sp.add_argument("--violation-min-strength", type=float)
    sp.set_defaults(fn=cmd_fit)

    args = p.parse_args(argv)
    for attr, default in (("only", None), ("trace", False)):
        if not hasattr(args, attr):
            setattr(args, attr, default)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
