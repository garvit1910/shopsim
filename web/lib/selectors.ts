/** Derived per-tick tables, computed from the real event stream only.
 * One pass over the buckets, cached by array identity — re-derived exactly
 * when new real events arrive. */

import type { C3Results, EventRecord, Population } from "./types";

export const FUNNEL_STAGES = ["SAW", "CLICKED", "BROWSED", "CARTED", "BOUGHT"] as const;
export const STAGE_RANK: Record<string, number> = {
  SAW: 1, CLICKED: 2, VISITED: 3, BROWSED: 3, CARTED: 4, BOUGHT: 5,
};
export const STAGE_NAMES = ["unexposed", "saw", "clicked", "browsed", "carted", "bought"];

export interface Derived {
  /** running count of live needs after each completed tick */
  needsCount: number[];
  /** per completed tick: offset -> deepest funnel stage so far (0..5) */
  stageByTick: Map<number, number>[];
  /** per completed tick: cumulative event counts per creative per stage */
  funnelCum: Record<string, Record<string, number>>[];
  /** per completed tick: mean exposures to each shopper's most-seen creative */
  fatigue: number[];
  /** offsets that advanced a stage in tick t, with the new stage */
  movers: { offset: number; stage: number }[][];
  /** per completed tick: THAT DAY's impressions per creative (not cumulative)
   * — the allocation river's bands are these values */
  sawPerTick: Record<string, number>[];
}

const cache = new WeakMap<EventRecord[][], Derived>();

const offsetOf = (rec: EventRecord) =>
  rec.shopper_id != null ? rec.shopper_id % 100_000 : -1;

export function derive(eventsByTick: EventRecord[][]): Derived {
  const hit = cache.get(eventsByTick);
  if (hit) return hit;

  const needsCount: number[] = [];
  const stageByTick: Map<number, number>[] = [];
  const funnelCum: Record<string, Record<string, number>>[] = [];
  const fatigue: number[] = [];
  const movers: { offset: number; stage: number }[][] = [];
  const sawPerTick: Record<string, number>[] = [];

  let liveNeeds = 0;
  const stage = new Map<number, number>();
  const exposures = new Map<number, Map<number, number>>(); // offset -> creative -> n
  const cum: Record<string, Record<string, number>> = {};

  for (let t = 0; t < eventsByTick.length; t++) {
    const moved = new Map<number, number>();
    const sawToday: Record<string, number> = {};
    for (const rec of eventsByTick[t] ?? []) {
      const off = offsetOf(rec);
      if (rec.type === "NEED_ACTIVATED") liveNeeds++;
      else if (rec.type === "NEED_EXPIRED" || rec.type === "NEED_SATISFIED") liveNeeds--;
      const rank = STAGE_RANK[rec.type];
      if (rank != null && off >= 0) {
        const prev = stage.get(off) ?? 0;
        if (rank > prev) {
          stage.set(off, rank);
          moved.set(off, rank);
        }
      }
      if (rec.type === "SAW" && off >= 0 && rec.subject != null) {
        let per = exposures.get(off);
        if (!per) exposures.set(off, (per = new Map()));
        per.set(rec.subject, (per.get(rec.subject) ?? 0) + 1);
        sawToday[rec.subject] = (sawToday[rec.subject] ?? 0) + 1;
      }
      // per-creative cumulative funnel (subject for SAW/CLICKED, cause for deeper)
      let creative: number | undefined;
      if (rec.type === "SAW" || rec.type === "CLICKED") creative = rec.subject;
      else if (rec.cause_creative) creative = rec.cause_creative;
      if (creative != null && (FUNNEL_STAGES as readonly string[]).includes(rec.type)) {
        const row = (cum[creative] ??= {});
        row[rec.type] = (row[rec.type] ?? 0) + 1;
      }
    }
    needsCount.push(liveNeeds);
    stageByTick.push(new Map(stage));
    funnelCum.push(structuredClone(cum));
    let expSum = 0;
    for (const per of exposures.values()) expSum += Math.max(0, ...per.values());
    fatigue.push(exposures.size ? expSum / exposures.size : 0);
    movers.push([...moved.entries()]
      .map(([offset, st]) => ({ offset, stage: st }))
      .sort((a, b) => b.stage - a.stage));
    sawPerTick.push(sawToday);
  }

  const out = { needsCount, stageByTick, funnelCum, fatigue, movers, sawPerTick };
  cache.set(eventsByTick, out);
  return out;
}

/** CTR series per creative from the C3 results (sliceable by tick).
 * `ctr_by_creative_by_day` is a flat list of {creative, tick, ctr} rows. */
export function ctrSeries(results: C3Results | null, creative: string, ticks: number): (number | null)[] {
  const out: (number | null)[] = Array.from({ length: ticks }, () => null);
  const rows = results?.ctr_by_creative_by_day;
  if (!Array.isArray(rows)) return out;
  const id = Number(creative);
  for (const row of rows) {
    if (row.creative === id && row.tick < ticks) out[row.tick] = row.ctr;
  }
  return out;
}

/** One fatigue channel as a per-tick series, straight from the engine's
 * MetricsReport (CONTRACT v3.8-draft `fatigue_split`). Returns null when the
 * run predates Phase 6, which is the caller's cue to fall back to the
 * client-side derivation in `derive().fatigue` and say so on screen. */
export function fatigueSeries(
  results: C3Results | null, channel: "asset" | "brand_msg" | "concept", ticks: number,
): (number | null)[] | null {
  const rows = results?.fatigue_split?.[channel];
  if (!Array.isArray(rows) || rows.length === 0) return null;
  const out: (number | null)[] = Array.from({ length: ticks }, () => null);
  for (const row of rows) if (row.tick < ticks) out[row.tick] = row.mean;
  return out;
}

/** Provisional today-so-far CTR per creative from the in-flight bucket. */
export function provisionalCtr(partial: EventRecord[]): Record<string, { exposures: number; clicks: number; ctr: number | null }> {
  const out: Record<string, { exposures: number; clicks: number; ctr: number | null }> = {};
  for (const rec of partial) {
    if (rec.subject == null) continue;
    if (rec.type === "SAW" || rec.type === "CLICKED") {
      const row = (out[rec.subject] ??= { exposures: 0, clicks: 0, ctr: null });
      if (rec.type === "SAW") row.exposures++;
      else row.clicks++;
    }
  }
  for (const row of Object.values(out)) row.ctr = row.exposures ? row.clicks / row.exposures : null;
  return out;
}

/** Cumulative KPIs at tick t from the derived tables + results slices. */
export function kpisAt(d: Derived, results: C3Results | null, t: number) {
  const totals: Record<string, number> = {};
  for (const row of Object.values(d.funnelCum[t] ?? {}))
    for (const [k, v] of Object.entries(row)) totals[k] = (totals[k] ?? 0) + v;
  return {
    imp: totals.SAW ?? 0,
    clicks: totals.CLICKED ?? 0,
    browses: totals.BROWSED ?? 0,
    carts: totals.CARTED ?? 0,
    buys: totals.BOUGHT ?? 0,
    ctr: totals.SAW ? (totals.CLICKED ?? 0) / totals.SAW : null,
    needs: d.needsCount[t] ?? 0,
    fatigue: d.fatigue[t] ?? 0,
  };
}

/** Revenue up to tick t straight from BOUGHT event prices. */
export function revenueAt(eventsByTick: EventRecord[][], t: number): number {
  let out = 0;
  for (let i = 0; i <= t && i < eventsByTick.length; i++)
    for (const rec of eventsByTick[i])
      if (rec.type === "BOUGHT" && rec.price) out += rec.price;
  return Math.round(out * 100) / 100;
}

export function segmentOf(pop: Population | null, offset: number): string {
  if (!pop) return "";
  const sh = pop.shoppers[offset];
  if (!sh) return "";
  return pop.segments.find((s) => s.segment_id === sh.segment_id)?.name ?? "";
}
