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
