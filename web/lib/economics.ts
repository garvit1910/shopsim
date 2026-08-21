/** The money layer: the ONE assumption the dashboard adds on top of the
 * simulation.
 *
 * The engine simulates impressions and real purchase amounts (BOUGHT.price),
 * but it has no cost model — nothing in the sim knows what an impression
 * costs to buy. SPEND and ROAS therefore rest on a single researched
 * constant, documented with its sources in eval/market-research.md §5.
 *
 * Why the Meta e-commerce median and not the ~$3 Display Network CPM: the
 * mind's P(CLICK|exposure) is calibrated to 0.5–2% (market-research.md §1),
 * which is the paid-social retail CTR band. Pricing social-grade clicks at
 * display-grade CPMs would flatter ROAS by roughly 4x.
 */

import type { RunConfigPayload } from "./types";
import { CALIBRATED_CLICK_BASE, CLICK_GATE_ACCELERATION, REAL_CTR_BAND, REAL_CTR_REFERENCE } from "./calibration";

/** Meta median CPM, e-commerce vertical, Jul 2025–Jul 2026. */
export const CPM_USD = 13.88;

export const CPM_SOURCE =
  "Meta e-commerce median CPM $13.88 (industry band $5–18) · see eval/market-research.md §5";

/** Impressions are simulated; the price of one is assumed. */
export const spendFor = (impressions: number): number =>
  Math.round((impressions * CPM_USD) / 10) / 100;

export const roasFor = (revenue: number, spend: number): number | null =>
  spend > 0 ? revenue / spend : null;

/** Money on this dashboard is sim-scale: a few hundred simulated shoppers,
 * not a campaign. Tiles carry this so nobody reads $400 as a media budget. */
export const SIM_SCALE_NOTE = "SIM-SCALE $";

export const fmtRoas = (n: number | null): string =>
  n == null ? "—" : n.toFixed(2) + "×";

/** Compact money for tiles: $1.2k above a thousand, cents below ten. */
export function fmtMoney(n: number | null | undefined): string {
  if (n == null) return "—";
  if (Math.abs(n) >= 10_000) return "$" + (n / 1000).toFixed(1) + "k";
  if (Math.abs(n) >= 100) return "$" + Math.round(n).toLocaleString("en-US");
  return "$" + n.toFixed(2);
}

/** THE adjusting factor: how far this run's click rate sits above what the
 * certified engine would produce, so every CTR and ROAS on the Market page can
 * be read at a human-scale rate. The headline is ALWAYS the adjusted number;
 * the raw rate, the factor and its source are always printed beside it.
 *
 * Sources, in priority order:
 *   "published" — the engine's `effective.click_gate.acceleration` (CONTRACT
 *                 v3.13-draft), or the same calibration.json table mirrored
 *                 in lib/calibration.ts keyed by the run's own CLICK base when
 *                 the engine serving us predates that field.
 *   "band"      — no published multiple for this run (no run_config at all,
 *                 or an untabulated base): normalise to the researched 1.25%
 *                 mid-point, i.e. factor = raw CTR / 0.0125. Only used when
 *                 the raw rate is above the 0.5–2% band with enough volume.
 *   "none"      — factor 1: the run is already at a human-scale rate.
 *
 * Only the click gate is ever accelerated (calibration.json: 1.0x on every
 * post-click metric), so CTR divides straight through, and ROAS — which
 * carries the same factor via revenue — divides through too, keeping the
 * run's own revenue per click. FIRST-ORDER: the published replay cannot model
 * the click->preference feedback loop. */
export interface Adjust {
  factor: number;
  source: "published" | "band" | "none";
  /** the run's CLICK base when known */
  base: number | null;
}

const MIN_IMPRESSIONS_FOR_BAND = 200;

export function ctrAdjust(
  config: RunConfigPayload | null | undefined,
  rawCtr: number | null | undefined,
  impressions: number,
): Adjust {
  const rawBase = (config?.raw as { calibration?: { stage_bases?: { CLICK?: unknown } } } | undefined)
    ?.calibration?.stage_bases?.CLICK;
  const base: number | null = config
    ? (typeof rawBase === "number" && Number.isFinite(rawBase) ? rawBase : CALIBRATED_CLICK_BASE)
    : null;

  // tier A — the engine states it
  const g = config?.effective?.click_gate;
  if (g && typeof g.acceleration === "number" && g.acceleration > 0) {
    return { factor: g.acceleration, source: g.acceleration > 1.0001 ? "published" : "none", base: g.base };
  }
  // tier B — the mirrored table, by the run's own base
  if (base != null) {
    const hit = Object.entries(CLICK_GATE_ACCELERATION)
      .find(([k]) => Math.abs(Number(k) - base) < 1e-6);
    if (hit) return { factor: hit[1], source: hit[1] > 1.0001 ? "published" : "none", base };
  }
  // tier C — band normalisation, last resort
  if (rawCtr != null && impressions > MIN_IMPRESSIONS_FOR_BAND && rawCtr > REAL_CTR_BAND[1]) {
    return { factor: rawCtr / REAL_CTR_REFERENCE, source: "band", base };
  }
  return { factor: 1, source: "none", base };
}

/** A raw rate read through the adjusting factor. */
export const adjusted = (v: number | null | undefined, a: Adjust): number | null =>
  v == null ? null : v / a.factor;

export const adjustedSeries = (data: (number | null)[], a: Adjust): (number | null)[] =>
  a.factor === 1 ? data : data.map((v) => adjusted(v, a));

export const isAdjusted = (a: Adjust): boolean => a.factor > 1.0001;

/** "÷31.0" — the factor as the tiles print it; "" when nothing is divided. */
export const fmtFactor = (a: Adjust): string => (isAdjusted(a) ? "÷" + a.factor.toFixed(1) : "");

/** "PUBLISHED" / "BAND-NORMALISED" — where the factor came from, for the sub line. */
export const factorSourceLabel = (a: Adjust): string =>
  a.source === "band" ? "BAND-NORMALISED" : "PUBLISHED";

/** One sentence a tooltip can carry about the factor. */
export function explainFactor(a: Adjust): string {
  if (!isAdjusted(a)) {
    return a.base != null
      ? `This run clicks at the calibrated CLICK gate (${a.base}); nothing is divided out.`
      : "Nothing is divided out.";
  }
  if (a.source === "published") {
    return `This run lowered the CLICK threshold to ${a.base} (calibrated ${CALIBRATED_CLICK_BASE}); `
      + `the published reference-trace replay (eval/results/calibration.json) puts that at ${a.factor.toFixed(1)}x on clicks, `
      + "so the raw rate is divided by it. First-order: the replay cannot model the click→preference feedback loop.";
  }
  return "The engine has no published acceleration for this run"
    + (a.base != null ? ` (CLICK base ${a.base})` : " (no run_config)")
    + `, so the raw rate is normalised to the researched 1.25% paid-social mid-point: factor = raw CTR ÷ 1.25% = ${a.factor.toFixed(1)}.`;
}
