"""Phase-6 finalize: the blocks that need a segment map or a graph read, plus
the post-hoc assembly behind `python -m shopsim.analytics report`.

Split from metrics.py because everything here touches the outside world —
HydraDB for the belief provenance sweep, the run directory for a post-hoc
rebuild. metrics.py stays pure so the golden test can assert its arithmetic
without a database.

Degradation is deliberate and loud: a missing graph, a missing segment map or
a pre-Phase-6 snapshot each drop exactly one block and add a note naming what
could not be computed. Nothing is ever invented to fill a key.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..contracts import evidence
from ..hydramem import cypher, schema
from ..runner.results import BY_SHOPPER_FIELDS, ResultsAccumulator, validate_results
from . import metrics

ASPECT_NAME = {v: k for k, v in schema.ASPECT_IDS.items()}

# PREFERS versions whose cause is a real behavioral receipt. "SEED" is the
# prior the population factory writes and "SAW" must never appear at all
# (Law 14: exposure never teaches taste — F7 audits exactly this).
CAUSE_KINDS = ("CLICKED", "BROWSED", "CARTED", "BOUGHT", "EXPERIENCED")

CONF_BINS = 10
GROUP_CHUNK = 500  # shoppers per run_grouped fan-out


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


# ---------------------------------------------------------------------------
# the belief / provenance sweep (read-only)
# ---------------------------------------------------------------------------


def belief_metrics(client, shopper_ids: list[int], now: int) -> dict:
    """`belief_confidence_dist` + `provenance_coverage` from one read sweep.

    Cost: two statements per shopper plus one per LIVE belief, fanned out by
    run_grouped — sub-second at demo scale, because reads are ~0.3ms (it is
    writes that are serialized at ~200/s).

    Scope, stated in the payload rather than hidden: PREFERS is swept over its
    FULL version history (one statement returns the whole supersession chain),
    beliefs over the LIVE versions only. Sweeping every historical belief
    version costs one statement per version — tens of thousands on a 60-tick
    run — and the live set already answers the question the metric exists for:
    does every belief a shopper currently holds carry its receipts.
    """
    conf_by_aspect: dict[str, list[float]] = {}
    pref_versions = pref_learned = pref_caused = 0
    cause_kinds: dict[str, int] = {}
    belief_versions = belief_with_prov = 0

    for chunk in _chunks(sorted(shopper_ids), GROUP_CHUNK):
        rows = client.run_grouped({sid: [
            cypher.live_holds(sid, now),
            cypher.all_edges("PREFERS", sid, ("source", "cause_kind")),
        ] for sid in chunk})
        derived_plan: dict[tuple[int, int], list] = {}
        for sid in chunk:
            holds, prefers = rows[sid]
            for r in prefers:
                pref_versions += 1
                if r.get("source") != "learned":
                    continue
                pref_learned += 1
                kind = r.get("cause_kind") or "none"
                cause_kinds[kind] = cause_kinds.get(kind, 0) + 1
                if kind in CAUSE_KINDS:
                    pref_caused += 1
            for b in holds:
                belief_versions += 1
                aspect = ASPECT_NAME.get(b["that_id"], str(b["that_id"]))
                conf_by_aspect.setdefault(aspect, []).append(
                    evidence.confidence(b["evidence"]))
                derived_plan[(sid, b["dst"])] = [
                    cypher.all_edges("DERIVED_FROM", b["dst"], ("kind",))]
        if derived_plan:
            for _key, res in client.run_grouped(derived_plan).items():
                if res[0]:
                    belief_with_prov += 1

    dist = []
    width = 1.0 / CONF_BINS
    for aspect in sorted(conf_by_aspect):
        values = conf_by_aspect[aspect]
        counts = [0] * CONF_BINS
        for c in values:
            counts[min(CONF_BINS - 1, int(c / width))] += 1
        for i, n in enumerate(counts):
            dist.append({"aspect": aspect, "bin_lo": round(i * width, 2),
                         "bin_hi": round((i + 1) * width, 2), "count": n})

    should = pref_learned + belief_versions
    carried = pref_caused + belief_with_prov
    return {
        "belief_confidence_dist": dist,
        "provenance_coverage": {
            "coverage": (round(carried / should, 5) if should else None),
            "prefers": {
                "versions": pref_versions,
                "learned_versions": pref_learned,
                "with_cause": pref_caused,
                "coverage": (round(pref_caused / pref_learned, 5) if pref_learned else None),
                "cause_kinds": dict(sorted(cause_kinds.items())),
            },
            "beliefs": {
                "versions": belief_versions,
                "with_provenance": belief_with_prov,
                "coverage": (round(belief_with_prov / belief_versions, 5)
                             if belief_versions else None),
            },
            "belief_scope": "live",
        },
    }


# ---------------------------------------------------------------------------
# finalize
# ---------------------------------------------------------------------------


def finalize_extras(acc: ResultsAccumulator, *, seed: int, mem=None, now: int | None = None,
                    offsets: list[int] | None = None,
                    n_boot: int = metrics.N_BOOT) -> tuple[dict, list[str]]:
    extras: dict = {}
    notes: list[str] = []

    if acc.by_shopper:
        if not acc.segment_by_offset:
            notes.append("ci: arm-level only — no segment map available "
                         "(per-segment intervals need the run_config)")
        extras["ci"] = metrics.funnel_ci(
            acc.by_shopper, BY_SHOPPER_FIELDS, acc.segment_by_offset, seed, n_boot=n_boot)
    else:
        notes.append("ci: skipped — this run carries no per-shopper counts "
                     "(results_state predates CONTRACT v3.8-draft)")

    if mem is None:
        notes.append("belief metrics: skipped — no graph read was made "
                     "(belief_confidence_dist / provenance_coverage stay empty)")
        return extras, notes

    ids = offsets if offsets is not None else [int(o) for o in acc.by_shopper]
    if not ids:
        notes.append("belief metrics: skipped — no shopper offsets to sweep")
        return extras, notes
    from ..contracts.ids import shopper_id as make_sid
    try:
        extras.update(belief_metrics(
            mem.client, [make_sid(mem.run_index, o) for o in ids],
            now if now is not None else mem._now))
    except Exception as ex:  # noqa: BLE001 — a down store must never fail a run
        notes.append(f"belief metrics: unavailable ({type(ex).__name__}: {ex})")
    return extras, notes


def finalize_results(acc: ResultsAccumulator, manifest: dict, *, mem=None,
                     now: int | None = None, offsets: list[int] | None = None,
                     n_boot: int = metrics.N_BOOT) -> tuple[dict, list[str]]:
    """The full C3 MetricsReport + the notes naming anything left empty."""
    extras, notes = finalize_extras(
        acc, seed=int(manifest["seed"]), mem=mem, now=now, offsets=offsets, n_boot=n_boot)
    return acc.results(manifest, extras), notes


# ---------------------------------------------------------------------------
# post-hoc: rebuild a report from a run directory
# ---------------------------------------------------------------------------


def latest_state(run_dir: Path) -> dict | None:
    snaps = sorted(run_dir.glob("results_state_*.json"),
                   key=lambda p: int(p.stem.rsplit("_", 1)[1]))
    for p in reversed(snaps):
        try:
            return json.loads(p.read_text())
        except (FileNotFoundError, ValueError):
            continue
    return None


def offsets_from_log(run_dir: Path) -> list[int]:
    """Distinct shopper OFFSETS seen in the event log — the fallback sweep set
    for a run whose accumulator state predates the per-shopper vector."""
    path = run_dir / "events.jsonl"
    if not path.exists():
        return []
    seen = set()
    with path.open() as fh:
        for line in fh:
            if '"shopper_id"' not in line:
                continue
            try:
                sid = json.loads(line).get("shopper_id")
            except ValueError:
                continue
            if sid is not None:
                seen.add(int(sid) % 100_000)
    return sorted(seen)


def report_for_run(run_dir: Path, *, run_index: int, use_graph: bool = True,
                   segment_by_offset: dict | None = None,
                   n_boot: int = metrics.N_BOOT) -> tuple[dict, list[str]]:
    run_dir = Path(run_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text())
    snap = latest_state(run_dir)
    notes: list[str] = []
    if snap is None:
        raise FileNotFoundError(
            f"{run_dir.name}: no results_state_*.json — nothing to recompute from")
    acc = ResultsAccumulator.from_state(
        snap["state"], segment_by_offset=segment_by_offset or {},
        drift_concepts=[], hero_product=None)

    mem = None
    if use_graph:
        try:
            from ..hydramem.real import HydraMem
            mem = HydraMem(run_index=run_index)
        except Exception as ex:  # noqa: BLE001
            notes.append(f"graph unreachable ({type(ex).__name__}: {ex})")
    tick = int(snap["tick"])
    now = int(manifest["t0"]) + tick * int(manifest["tick_seconds"])
    offsets = [int(o) for o in acc.by_shopper] or offsets_from_log(run_dir)
    try:
        results, more = finalize_results(acc, manifest, mem=mem, now=now,
                                         offsets=offsets, n_boot=n_boot)
    finally:
        if mem is not None:
            mem.close()
    if tick < int(manifest["ticks"]) - 1:
        more.append(f"rebuilt from tick {tick} of {manifest['ticks']} — the run "
                    "did not complete, or its later snapshots were pruned")
    return results, notes + more


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------


def _span(ci: dict, key: str) -> str:
    v = ci.get(key)
    return f"  [{v[0]:.4f}, {v[1]:.4f}]" if v else ""


def render(results: dict, notes: list[str]) -> str:
    m = results["run_manifest"]
    out = [f"run  {m.get('label')} / arm {m.get('arm')}  "
           f"seed {m.get('seed')}  ticks {m.get('ticks')}  block {m.get('run_index')}"]

    totals: dict[str, int] = {}
    for segments in results["funnel"].values():
        for counts in segments.values():
            for k, v in counts.items():
                totals[k] = totals.get(k, 0) + v
    out.append("\nFUNNEL   " + "  ".join(
        f"{k} {totals.get(k, 0)}" for k in
        ("SAW", "CLICKED", "BROWSED", "BOUNCED", "CARTED", "BOUGHT", "EXPERIENCED")))

    ci = results.get("ci") or {}
    out.append("\nRATES (95% bootstrap CI over shoppers)")
    for name, num, den in metrics.CI_RATIOS + metrics.CI_DECISION_RATIOS:
        if name.startswith("p_buy_need"):
            point = results["goal_stats"].get(name)
        else:
            d = totals.get(den, 0)
            point = totals.get(num, 0) / d if d else None
        if point is None and name not in ci:
            continue
        shown = f"{point:.4f}" if point is not None else "   n/a"
        out.append(f"  {name:<18} {shown}{_span(ci, name)}")

    fs = results.get("fatigue_split") or {}
    out.append("\nFATIGUE SPLIT (mean level, then CTR high vs low)")
    for channel in ("asset", "brand_msg", "concept"):
        rows = fs.get(channel) or []
        if not rows:
            out.append(f"  {channel:<10} no creative decisions recorded")
            continue
        last = rows[-1]
        hi = f"{last['high_ctr']:.4f}" if last["high_ctr"] is not None else "n/a"
        lo = f"{last['low_ctr']:.4f}" if last["low_ctr"] is not None else "n/a"
        first, final = rows[0]["mean"], last["mean"]
        out.append(f"  {channel:<10} mean {first:.3f} -> {final:.3f}   "
                   f"CTR high {hi} (n={last['high_n']}) vs low {lo} (n={last['low_n']})")

    dist = results.get("belief_confidence_dist") or []
    if dist:
        out.append("\nBELIEF CONFIDENCE")
        for aspect in sorted({r["aspect"] for r in dist}):
            rows = [r for r in dist if r["aspect"] == aspect]
            n = sum(r["count"] for r in rows)
            mean = (sum(r["count"] * (r["bin_lo"] + r["bin_hi"]) / 2 for r in rows) / n
                    if n else 0.0)
            bars = "".join("_.:-=+*#%@"[min(9, r["count"])] for r in rows)
            out.append(f"  {aspect:<8} n={n:<5} mean~{mean:.2f}  0|{bars}|1")

    pc = results.get("provenance_coverage")
    if pc:
        out.append(
            "\nPROVENANCE  {:.1%} of subjective versions carry a cause "
            "(learned PREFERS {}/{}, live beliefs {}/{})".format(
                pc["coverage"] or 0.0, pc["prefers"]["with_cause"],
                pc["prefers"]["learned_versions"], pc["beliefs"]["with_provenance"],
                pc["beliefs"]["versions"]))
        kinds = pc["prefers"].get("cause_kinds") or {}
        if kinds:
            out.append("            causes: " + ", ".join(
                f"{k} {v}" for k, v in kinds.items()))

    gs = results["goal_stats"]
    on, off = gs.get("p_buy_need_on"), gs.get("p_buy_need_off")
    if on is not None and off:
        out.append(f"\nGOAL LIFT   P(buy | need) {on:.4f} vs {off:.4f} "
                   f"= x{on / off:.1f}")

    ltv = (results.get("repeat_ltv_by_arm") or [{}])[0]
    if ltv.get("buyers"):
        out.append(f"\nREPEAT/LTV  {ltv['buyers']} buyers, {ltv['buys']} purchases, "
                   f"repeat rate {ltv['repeat_rate']:.3f}, "
                   f"${ltv['revenue_per_buyer']:.2f} per buyer")
    sl = results.get("social_lift")
    if sl:
        out.append(f"SOCIAL      lift x{sl['lift'] if sl['lift'] is not None else 'n/a'} "
                   f"({'causal' if sl['causal'] else 'correlational'}: {sl['note']})")

    bd = results["violations"].get("bounce_delta")
    out.append(f"\nVIOLATIONS  {results['violations']['count']} sighted; "
               f"within-run bounce delta "
               f"{f'{bd:+.4f}' if bd is not None else 'n/a (no page split in this run)'}")

    problems = validate_results(results)
    out.append("\nC3          " + ("valid" if not problems
                                   else "INVALID: " + "; ".join(problems)))
    for n in notes:
        out.append(f"note        {n}")
    return "\n".join(out)
