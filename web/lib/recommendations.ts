/** Grade-1 recommendations (PLAN 5.4): rules mined from the MetricsReport +
 * comparison — every card cites the numbers it was mined from. */

import type { C3Results } from "./types";
import type { DetectedEvent } from "./detectors";

export interface Recommendation {
  title: string;
  body: string;
  evidence: string;
  severity: "info" | "warning" | "serious";
}

export function mineRecommendations(args: {
  results: C3Results | null;
  detected: DetectedEvent[];
  creativeNames: Record<string, string>;
  fatigue: number[];
}): Recommendation[] {
  const out: Recommendation[] = [];
  const r = args.results;
  if (!r) return out;

  const gs = r.goal_stats;
  if (gs?.p_buy_need_on != null && gs.p_buy_need_off != null) {
    const mult = gs.p_buy_need_off > 0 ? gs.p_buy_need_on / gs.p_buy_need_off : null;
    out.push({
      title: "Schedule campaigns into need waves",
      body: mult == null
        ? "Only shoppers with a live need converted at all — demand capture needs demand present."
        : `Shoppers with a live need converted ×${mult.toFixed(1)} more — reach is cheap, timing is not.`,
      evidence: `P(buy | need) ${(100 * gs.p_buy_need_on).toFixed(1)}% vs P(buy | none) ${(100 * gs.p_buy_need_off).toFixed(1)}%`,
      severity: "info",
    });
  }

  const fat = args.detected.find((d) => d.kind === "fatigue");
  if (fat) {
    out.push({
      title: "Rotate creative concepts",
      body: "Same-message repetition is decaying clickthrough — rotate concepts rather than re-serving the same claim.",
      evidence: `${fat.detail} (day ${fat.tick + 1}; ${fat.rule})`,
      severity: "warning",
    });
  }

  const promo = args.detected.find((d) => d.kind === "promo");
  if (promo) {
    out.push({
      title: "Watch promo addiction",
      body: "Shoppers' reference prices are re-anchoring below list — each discount cycle makes full price feel like a markup.",
      evidence: `${promo.detail} (day ${promo.tick + 1})`,
      severity: "warning",
    });
  }

  const fc = r.funnel_by_creative;
  if (fc && Object.keys(fc).length >= 2) {
    const rows = Object.entries(fc).map(([id, counts]) => ({
      id,
      name: args.creativeNames[id] ?? `creative ${id}`,
      saw: counts.SAW ?? 0,
      bought: counts.BOUGHT ?? 0,
      rate: (counts.SAW ?? 0) > 0 ? (counts.BOUGHT ?? 0) / (counts.SAW ?? 1) : 0,
    })).sort((a, b) => b.rate - a.rate);
    const [win, next] = rows;
    if (win && next && win.bought > 0) {
      out.push({
        title: `Shift budget toward ${win.name}`,
        body: next.rate > 0
          ? `It converts ×${(win.rate / next.rate).toFixed(1)} the runner-up per impression.`
          : "It is the only creative producing purchases in this flight.",
        evidence: `${win.name}: ${win.bought} buys / ${win.saw} impressions vs ${next.name}: ${next.bought} / ${next.saw}`,
        severity: "info",
      });
    }
  }

  const fp = r.funnel_by_page;
  if (fp && Object.keys(fp).length >= 2) {
    const rates = Object.entries(fp).map(([page, row]) => {
      const v = row.VISITED ?? 0, b = row.BOUNCED ?? 0;
      return { page, rate: v + b ? b / (v + b) : null };
    }).filter((x): x is { page: string; rate: number } => x.rate != null);
    if (rates.length >= 2) {
      rates.sort((a, b) => b.rate - a.rate);
      const delta = rates[0].rate - rates[rates.length - 1].rate;
      if (delta > 0.05) {
        out.push({
          title: "Align the landing page with the ad's claims",
          body: "The violating variant bounces measurably more — expectation violations are read as broken promises.",
          evidence: `bounce ${(100 * rates[0].rate).toFixed(1)}% (page ${rates[0].page}) vs ${(100 * rates[rates.length - 1].rate).toFixed(1)}% (page ${rates[rates.length - 1].page}) — Δ ${(100 * delta).toFixed(1)}pp`,
          severity: "serious",
        });
      }
    }
  }

  const drift = args.detected.find((d) => d.kind === "drift");
  if (drift) {
    out.push({
      title: "Lean into what the population is learning",
      body: "Preference drift is behavior-earned (clicks, carts, purchases — never exposure). The market is teaching you its taste.",
      evidence: `${drift.label}: ${drift.detail}`,
      severity: "info",
    });
  }

  return out;
}
