/** Detected market events: declared threshold rules over the real series.
 * The SAME code runs live and in replay; every event carries its rule text,
 * rendered in the UI — that is the honesty guarantee. */

import type { FatigueRow } from "./types";
import type { Derived } from "./selectors";

export type Severity = "info" | "warning" | "serious";

export interface DetectedEvent {
  tick: number;
  kind: string;
  severity: Severity;
  label: string;
  detail: string;
  rule: string;
}

export const DETECTOR_RULES = {
  driftDelta: 0.02,        // Δ mean PREFERS vs day 1
  trustDrop: -0.004,       // Δ avg trust over 2 ticks
  fatigueExposures: 4.2,   // mean top-creative exposures (fallback rule)
  fatigueCtrRatio: 0.85,   // CTR ratio, both the measured and fallback rules
  fatigueMinHigh: 3,       // decisions needed in the high cell to call it
  refPriceRatio: 0.95,     // mean reference price vs list
} as const;

const mean = (xs: (number | null)[]) => {
  const v = xs.filter((x): x is number => x != null);
  return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
};

/** Runs every detector over series sliced to [0..head]. Deterministic:
 * same series in, same events out. */
export function detectEvents(args: {
  head: number;
  driftSeries: { label: string; series: (number | null)[] }[];
  trust: (number | null)[];
  ctrLead: { label: string; series: (number | null)[] }[];
  fatigue: number[];
  /** CONTRACT v3.8-draft: the engine's own brand-message fatigue channel. When
   * present it REPLACES the CTR-decay heuristic below — it compares the CTR of
   * decisions the mind made under high fatigue against the rest, which is a
   * measurement, not an inference from a time series. */
  fatigueSplit?: FatigueRow[] | null;
  refPrice: (number | null)[];
  listPrice: number | null;
  d?: Derived;
}): DetectedEvent[] {
  const out: DetectedEvent[] = [];
  const R = DETECTOR_RULES;

  for (const { label, series } of args.driftSeries) {
    const base = series.find((v) => v != null);
    if (base == null) continue;
    for (let t = 1; t <= args.head; t++) {
      const v = series[t];
      if (v != null && v - base >= R.driftDelta) {
        out.push({
          tick: t, kind: "drift", severity: "info",
          label: `${label} preference climbing`,
          detail: `mean +${(v - base).toFixed(3)} since day 1 — behavior-earned, never from exposure`,
          rule: `Δ mean PREFERS ≥ ${R.driftDelta} vs day 1`,
        });
        break;
      }
    }
  }

  for (let t = 2; t <= args.head; t++) {
    const a = args.trust[t - 2], b = args.trust[t];
    if (a != null && b != null && b - a <= R.trustDrop) {
      out.push({
        tick: t, kind: "trust", severity: "serious",
        label: "Trust drop",
        detail: `avg brand trust ${a.toFixed(3)} → ${b.toFixed(3)}`,
        rule: `Δ avg trust ≤ ${R.trustDrop} over 2 ticks (population means move slowly)`,
      });
      break;
    }
  }

  const split = (args.fatigueSplit ?? []).filter((r) => r.tick <= args.head);
  const measured = split.find(
    (r) => r.high_n >= R.fatigueMinHigh && r.high_ctr != null && r.low_ctr != null
      && r.high_ctr < R.fatigueCtrRatio * r.low_ctr,
  );
  if (measured) {
    out.push({
      tick: measured.tick, kind: "fatigue", severity: "warning",
      label: "Message fatigue measured",
      detail: `CTR ${(100 * (measured.high_ctr ?? 0)).toFixed(1)}% among the ${measured.high_n} decisions made under high brand-message fatigue vs ${(100 * (measured.low_ctr ?? 0)).toFixed(1)}% among the other ${measured.low_n} — same day, same population`,
      rule: `fatigue_split.brand_msg: high-cell CTR < ${R.fatigueCtrRatio} × low-cell CTR with ≥ ${R.fatigueMinHigh} high decisions`,
    });
  }

  // With an engine channel in hand the heuristic below is not a second
  // opinion, it is a worse one — so it runs only for runs that have no channel.
  const ctrLead = split.length ? [] : args.ctrLead;
  for (const { label, series } of ctrLead) {
    const early = mean([series[1], series[2], series[3], series[4]]);
    if (early == null) continue;
    for (let t = 7; t <= args.head; t++) {
      const recent = mean([series[t - 2], series[t - 1], series[t]]);
      if (recent != null && (args.fatigue[t] ?? 0) >= R.fatigueExposures
          && recent < R.fatigueCtrRatio * early) {
        out.push({
          tick: t, kind: "fatigue", severity: "warning",
          label: "Message fatigue detected",
          detail: `${label} 3-day CTR mean ${(100 * recent).toFixed(1)}% vs ${(100 * early).toFixed(1)}% early-flight; mean top-creative exposures ${(args.fatigue[t] ?? 0).toFixed(1)}/shopper`,
          rule: `3-day CTR mean < ${R.fatigueCtrRatio} × days 2–5 mean AND mean exposures ≥ ${R.fatigueExposures}`,
        });
        break;
      }
    }
  }

  if (args.listPrice != null) {
    for (let t = 0; t <= args.head; t++) {
      const v = args.refPrice[t];
      if (v != null && v <= R.refPriceRatio * args.listPrice) {
        out.push({
          tick: t, kind: "promo", severity: "warning",
          label: "Reference price eroding",
          detail: `mean reference price $${v.toFixed(2)} — ${(100 - (100 * v) / args.listPrice).toFixed(1)}% under list`,
          rule: `mean REFERENCE_PRICE ≤ ${R.refPriceRatio} × list`,
        });
        break;
      }
    }
  }

  return out.sort((a, b) => a.tick - b.tick);
}

export interface ScheduledEvent {
  tick: number;
  kind: "flight" | "promo" | "wave" | "ab";
  label: string;
  detail: string;
}

/** Scheduled events straight from /config.effective — never invented. */
export function scheduledEvents(effective: {
  schedule: { creative_id: number; start_tick: number; page_ids: number[] | null }[];
  promo_windows: Record<string, [number, number, number][]>;
  goal_waves: { category_id: number; start_tick: number; end_tick: number; rate_multiplier: number }[];
} | null): ScheduledEvent[] {
  if (!effective) return [];
  const out: ScheduledEvent[] = [];
  for (const row of effective.schedule) {
    out.push({
      tick: row.start_tick, kind: "flight",
      label: `Creative ${row.creative_id} flight begins`,
      detail: row.page_ids
        ? `with a seeded ${row.page_ids.length}-way landing-page split`
        : "enters the exposure schedule",
    });
    if (row.page_ids) out.push({
      tick: row.start_tick, kind: "ab",
      label: `Page A/B live (creative ${row.creative_id})`,
      detail: `variants ${row.page_ids.join(" vs ")}, seeded 50/50`,
    });
  }
  let cycle = 0;
  for (const [product, windows] of Object.entries(effective.promo_windows)) {
    for (const [start, end, pct] of windows) {
      cycle += 1;
      out.push({
        tick: start, kind: "promo",
        label: `Promo cycle ${cycle}`,
        detail: `${(pct * 100).toFixed(0)}% off product ${product} (days ${start + 1}–${end + 1})`,
      });
    }
  }
  for (const w of effective.goal_waves) {
    out.push({
      tick: w.start_tick, kind: "wave",
      label: `Need wave × ${w.rate_multiplier}`,
      detail: `category ${w.category_id} arrivals × ${w.rate_multiplier} (days ${w.start_tick + 1}–${w.end_tick + 1})`,
    });
    out.push({
      tick: w.end_tick, kind: "wave",
      label: "Need wave ends",
      detail: `category ${w.category_id} arrivals back to baseline`,
    });
  }
  return out.sort((a, b) => a.tick - b.tick);
}
