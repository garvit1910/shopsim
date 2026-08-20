"use client";

/** The market store: one clock, two data sources. The poller ingests real
 * engine output (events byte-tail, results-live, progress); the clock plays
 * days at the mock's cadence in BOTH modes (chase-replay): LIVE follows the
 * engine by playing already-simulated days continuously, holding at the
 * frontier until the next tick lands. Every frame is real data; frac only
 * paces the current day's draw-in (the D5 mock animation). */

import { create } from "zustand";
import { api } from "./api";
import type {
  CreativeCard,
  EnginePace,
  C3Results, EventRecord, Manifest, Population, Progress, RunConfigPayload,
} from "./types";

export type Mode = "live" | "replay";

export const DAY_MS = 1400; // one simulated day per 1.4s at ×1 (replay pace)

export interface MarketState {
  runId: string | null;
  mode: Mode;
  status: string;
  manifest: Manifest | null;
  config: RunConfigPayload | null;
  population: Population | null;
  /** the ads themselves: image, copy, and what perception read off them */
  cards: CreativeCard[] | null;
  /** starting = the engine is in prepare() and has no manifest yet */
  phase: "starting" | "live" | "replay" | "error";
  /** engine pace samples, for the ETA countdown */
  pace: EnginePace | null;
  /** transient poll failures — never the red box, which means "no such run" */
  warning: string | null;
  /** This run has no run_config.json. GET /runs/{id}/config resolves as
   * runs/experiments/<label>/run_config.json, so only orchestrator-launched
   * runs carry one — an eval scenario or a CLI run legitimately 404s. The
   * cockpit still renders (the event stream and results are enough for the
   * KPIs and the river) but the ad roster, the schedule and the population
   * are unavailable, and saying so beats a blank chart. */
  configMissing: boolean;
  /** prepare()-phase progress, for the preflight panel */
  bootProgress: Progress | null;
  /** events bucketed per completed tick; index = tick */
  eventsByTick: EventRecord[][];
  /** the in-flight tick's events so far (not rendered; kept for completeness) */
  partialEvents: EventRecord[];
  /** last fully completed tick, -1 before the first marker */
  headTick: number;
  results: C3Results | null;
  beliefAvg: Record<string, (number | null)[]>;
  error: string | null;
  // clock
  tick: number;
  frac: number;
  playing: boolean;
  speed: number;
  /** live only: chasing the engine frontier (LIVE badge); scrubbing clears it */
  followHead: boolean;
}

export const useMarket = create<MarketState>(() => ({
  runId: null, mode: "replay", status: "unknown",
  manifest: null, config: null, population: null, cards: null,
  phase: "starting", pace: null, warning: null, configMissing: false, bootProgress: null,
  eventsByTick: [], partialEvents: [], headTick: -1,
  results: null, beliefAvg: {}, error: null,
  tick: 0, frac: 0, playing: false, speed: 1, followHead: true,
}));

const set = useMarket.setState;
const get = useMarket.getState;

/* ---------------- event bucketing ---------------- */

function bucketRecords(
  records: EventRecord[],
  buckets: EventRecord[][],
  partial: EventRecord[],
): { buckets: EventRecord[][]; partial: EventRecord[]; head: number } {
  const out = buckets.map((b) => b);
  let cur = [...partial];
  for (const rec of records) {
    if (rec.type === "TICK_COMPLETE") {
      out[rec.tick ?? out.length] = cur;
      cur = [];
    } else {
      cur.push(rec);
    }
  }
  return { buckets: out, partial: cur, head: out.length - 1 };
}

/* ---------------- data pollers ---------------- */

let pollTimer: ReturnType<typeof setInterval> | null = null;
let cursor = 0;

function stopPoller() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
}

async function loadStatic(runId: string) {
  const manifest = await api.manifest(runId).catch(() => null);
  const [config, population, cards] = await Promise.all([
    api.config(runId).catch(() => null),
    api.population(runId).catch(() => null),
    api.creatives(runId).then((r) => r.creatives).catch(() => null),
  ]);
  // A null config is not a transient failure — it is a permanent property of
  // runs launched outside the orchestrator. Report it so the page can explain
  // the empty roster rather than rendering a cockpit around a hole.
  return { manifest, config, population, cards, configMissing: config === null };
}

async function refreshResults(runId: string) {
  try {
    const live = await api.resultsLive(runId);
    set({ results: live.results, beliefAvg: live.live_extras.belief_avg, status: live.status });
  } catch {
    /* tick 0 in flight — nothing yet */
  }
}

async function pumpEvents(runId: string): Promise<number> {
  let advanced = 0;
  for (;;) {
    // events.jsonl does not exist until the first tick writes — a 404 here is
    // "not yet", not a failure, and used to land in the red error box
    const page = await api.events(runId, cursor).catch(() => null);
    if (!page) return advanced;
    cursor = page.next < cursor ? 0 : page.next; // truncation reset
    if (page.records.length) {
      const s = get();
      const { buckets, partial, head } = bucketRecords(
        page.records, s.eventsByTick, s.partialEvents);
      if (head > s.headTick) advanced = head - s.headTick;
      set({ eventsByTick: buckets, partialEvents: partial, headTick: head });
    }
    if (page.eof || page.records.length === 0) return advanced;
  }
}

/** Open a run. LIVE (chasing poller) for running runs, REPLAY for complete. */
export async function openRun(runId: string): Promise<void> {
  stopPoller();
  stopClock();
  cursor = 0;
  set({
    runId, eventsByTick: [], partialEvents: [], headTick: -1,
    results: null, beliefAvg: {}, error: null,
    tick: 0, frac: 0, playing: false, speed: 1, followHead: true,
  });
  try {
    api.pace().then((pace) => get().runId === runId && set({ pace })).catch(() => {});

    const { manifest, config, population, cards, configMissing } = await loadStatic(runId);
    set({ configMissing });
    let status = "complete";
    try {
      status = (await api.progress(runId)).status;
    } catch { /* progress may not exist for a moment after launch */ }

    // The registry row is published the instant the run dir is made, but
    // manifest.json lands only at the END of prepare() (population + graph
    // seeding). Opening the run in that window used to throw on the very
    // first await and skip everything after it — no poller, no clock, a red
    // box, and no recovery short of a reload. Now it simply waits.
    if (!manifest) {
      set({ runId, phase: "starting", status: status || "preparing",
            config, population, cards, error: null });
      bootPoll(runId);
      return;
    }

    const mode: Mode = status === "complete" ? "replay" : "live";
    set({ manifest, config, population, cards, status, mode,
          phase: mode === "live" ? "live" : "replay" });
    if (mode === "live") startLivePoller(runId);
    else {
      await refreshResults(runId);
      await pumpEvents(runId);
    }
    play(); // both modes: the chase-replay clock starts at day 1
  } catch (ex) {
    set({ phase: "error", error: ex instanceof Error ? ex.message : String(ex) });
  }
}

/** Wait out prepare(). Retries the manifest (and refreshes progress so the
 * preflight panel can name the phase) until the engine is ready, then falls
 * through to the normal open path. */
function bootPoll(runId: string) {
  stopPoller();
  stopClock();
  stopBoot();
  bootTimer = setInterval(async () => {
    if (get().runId !== runId) return stopBoot();
    try {
      const prog = await api.progress(runId).catch(() => null);
      if (prog) set({ status: prog.status, bootProgress: prog });
      const manifest = await api.manifest(runId).catch(() => null);
      if (!manifest) return;
      stopBoot();
      await openRun(runId);
    } catch { /* keep waiting: a preparing run answers 404 for a while */ }
  }, 1000);
}

function stopBoot() {
  if (bootTimer) { clearInterval(bootTimer); bootTimer = null; }
}

function startLivePoller(runId: string) {
  const poll = async () => {
    if (get().runId !== runId || get().mode !== "live") return;
    try {
      const advanced = await pumpEvents(runId);
      if (advanced > 0) await refreshResults(runId);
      const prog = await api.progress(runId).catch(() => null);
      if (prog) {
        set({ status: prog.status, bootProgress: prog, warning: null });
        if (prog.status === "complete") {
          stopPoller();
          await pumpEvents(runId);      // drain the final ticks
          await refreshResults(runId);
          // keep the chase playing through the remaining days, then stop
          set({ mode: "replay" });
        }
      }
    } catch (ex) {
      set({ error: ex instanceof Error ? ex.message : String(ex) });
    }
  };
  refreshResults(runId);
  poll();
  pollTimer = setInterval(poll, 2000);
}

/* ---------------- the chase-replay clock (both modes) ----------------
 * Interval-driven (not rAF): rAF starves in background tabs and headless
 * captures, and a market left open in another tab must keep playing. 50ms
 * steps are plenty smooth for the playhead glide. */

const CLOCK_STEP_MS = 50;
let clockTimer: ReturnType<typeof setInterval> | null = null;
let bootTimer: ReturnType<typeof setInterval> | null = null;

function stopClock() {
  if (clockTimer) clearInterval(clockTimer);
  clockTimer = null;
}

function clockLoop() {
  stopClock();
  let last = performance.now();
  clockTimer = setInterval(() => {
    const s = get();
    if (!s.playing || !s.runId) { stopClock(); return; }
    const now = performance.now();
    const dt = (now - last) * s.speed;
    last = now;
    if (s.headTick < 0) return; // nothing simulated yet — hold at day 1
    const maxTick = (s.manifest?.ticks ?? s.headTick + 1) - 1;
    const frontier = Math.min(maxTick, s.headTick);
    if (s.tick > frontier) { set({ tick: frontier, frac: 0 }); return; }
    const frac = s.frac + dt / DAY_MS;
    if (s.tick === frontier) {
      if (s.mode === "live") {
        // the engine hasn't simulated the next day yet — rest on the tick
        if (s.frac !== 0) set({ frac: 0 });
        return;
      }
      // replay: finish the final day's draw-in, then stop
      if (frac >= 1) { set({ playing: false, frac: 0 }); stopClock(); return; }
      set({ frac });
      return;
    }
    if (frac >= 1) set({ tick: s.tick + 1, frac: 0 });
    else set({ frac });
  }, CLOCK_STEP_MS);
}

export function play() {
  const s = get();
  if (s.mode === "replay") {
    const frontier = Math.min((s.manifest?.ticks ?? 1) - 1, Math.max(s.headTick, 0));
    if (s.tick >= frontier && s.frac === 0) set({ tick: 0 });
  }
  set({ playing: true });
  clockLoop();
}

export function pause() {
  set({ playing: false, frac: 0 });
}

export function toggle() {
  get().playing ? pause() : play();
}

/** Scrub: pause and detach from the chase (REPLAY badge). */
export function seek(tick: number) {
  const s = get();
  const frontier = Math.min((s.manifest?.ticks ?? 1) - 1, Math.max(s.headTick, 0));
  set({
    tick: Math.max(0, Math.min(frontier, Math.round(tick))),
    frac: 0, playing: false, followHead: false,
  });
}

export function setSpeed(speed: number) {
  set({ speed });
}

/** Resume the chase from the current position (catches up at ×speed). */
export function followHead() {
  set({ followHead: true });
  play();
}

export function closeRun() {
  stopPoller();
  stopClock();
  set({ runId: null });
}
