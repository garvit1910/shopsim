/** How long is this run going to take?
 *
 * Per-tick cost is dominated by HydraDB consolidation and grows with the
 * store, so a hardcoded constant goes stale within a day (measured on this
 * repo: the same 200x60 shape ran at 18.5 s/tick on a fresh store and 112
 * s/tick on a loaded one). The estimate therefore comes from `/engine/pace`,
 * which reports what recent runs on THIS machine actually did.
 */

import type { EnginePace, Progress } from "./types";

/** Fallback when no run has ever completed here: measured fresh-store pace. */
const FALLBACK_S_PER_TICK_PER_100 = 5.5;
/** prepare() — population generation + graph seeding — before day 1 exists. */
const PREPARE_S_PER_100 = 12;

export interface Eta {
  /** seconds still to go, or null when it cannot be estimated yet */
  remainingS: number | null;
  perTickS: number | null;
  /** true once the run has produced at least one tick of real timing */
  measured: boolean;
}

const perTickFrom = (pace: EnginePace | null, population: number) =>
  ((pace?.per_tick_s_per_100_shoppers ?? FALLBACK_S_PER_TICK_PER_100) * population) / 100;

export function estimate(
  { pace, population, ticks, progress }: {
    pace: EnginePace | null;
    population: number;
    ticks: number;
    progress: Progress | null;
  },
  prev?: { tick: number; wall: number } | null,
): Eta {
  if (!ticks || !population) return { remainingS: null, perTickS: null, measured: false };

  const tick = progress?.tick ?? -1;
  const wall = progress?.total_wall_s ?? 0;

  // still preparing: nothing measured yet, so price the whole flight from
  // recent runs and add the seeding cost
  if (tick < 0 || !wall) {
    const perTick = perTickFrom(pace, population);
    return {
      remainingS: perTick * ticks + (PREPARE_S_PER_100 * population) / 100,
      perTickS: perTick,
      measured: false,
    };
  }

  const avg = wall / (tick + 1);
  // Per-tick cost RISES within a run as the graph grows, so the trailing
  // average under-predicts. Lean on the marginal cost of the most recent
  // ticks when we have two samples, and pad for continued growth.
  const marginal = prev && tick > prev.tick && wall > prev.wall
    ? (wall - prev.wall) / (tick - prev.tick)
    : avg;
  const perTick = 0.35 * avg + 0.65 * marginal;
  const remaining = Math.max(0, ticks - 1 - tick);
  return { remainingS: perTick * remaining * 1.15, perTickS: perTick, measured: true };
}

export const fmtDuration = (s: number | null): string => {
  if (s == null || !Number.isFinite(s)) return "—";
  const total = Math.max(0, Math.round(s));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const sec = total % 60;
  if (h) return `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
  return `${m}:${String(sec).padStart(2, "0")}`;
};

/** How long a countdown gets extended when it runs out but the engine has
 * not finished — deliberately a round, honest "a bit longer" rather than a
 * fake-precise new number. */
export const OVERRUN_EXTENSION_S = 120;
