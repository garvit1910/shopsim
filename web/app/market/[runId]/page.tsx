"use client";

/** 03 MARKET — the live simulated market.
 *
 * Above the fold there are exactly two things: the flight KPI row and the
 * allocation river. Everything the terminal used to shout at once now sits
 * below, in sections you open when you want them. LIVE is a chase-replay:
 * days play at demo pace and hold at the engine's frontier. */

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, use, useEffect, useMemo, useState } from "react";
import { followHead, openRun, seek, useMarket } from "@/lib/market";
import { ctrSeries, derive } from "@/lib/selectors";
import { detectEvents, scheduledEvents } from "@/lib/detectors";
import { api, proxied } from "@/lib/api";
import type { ExperimentDetail } from "@/lib/types";
import MasterTimeline from "@/components/MasterTimeline";
import Tape from "@/components/Tape";
import Inspector from "@/components/Inspector";
import StoryMode from "@/components/StoryMode";
import AllocationRiver, { type RiverSeries } from "@/components/AllocationRiver";
import { AdRoster } from "@/components/AdCard";
import Stepper, { pipelineSteps } from "@/components/Stepper";
import EnginePreflight, { EtaChip } from "@/components/EnginePreflight";
import { CtrSmallMultiples, FlightKpis } from "@/components/market";
import {
  ActivityPanel, CtrByDayPanel, EventsLedgerPanel, FunnelByCreativePanel,
  KpiTiles, PageAbPanel, SmallMultiples, creativesFromConfig,
} from "@/components/panels";

function MarketInner({ runId }: { runId: string }) {
  const s = useMarket();
  const router = useRouter();
  const search = useSearchParams();
  const [story, setStory] = useState(() => search.get("story") === "1");
  const [experiment, setExperiment] = useState<ExperimentDetail | null>(null);

  useEffect(() => { openRun(runId); }, [runId]);
  useEffect(() => {
    if (!s.config) return;
    if (s.config.effective.arms.length > 1) {
      api.experiment(s.config.effective.label).then(setExperiment).catch(() => {});
    }
  }, [s.config]);

  const inspected = search.get("shopper");
  const openInspector = (offset: number) => router.replace(`?shopper=${offset}`, { scroll: false });
  const closeInspector = () => router.replace("?", { scroll: false });

  const ticks = s.manifest?.ticks ?? Math.max(1, s.headTick + 1);
  const t = Math.max(0, Math.min(s.tick, Math.max(0, s.headTick)));
  const d = derive(s.eventsByTick);

  const creatives = useMemo(
    () => creativesFromConfig(s.config?.effective.schedule, s.config?.effective.creative_names, s.cards),
    [s.config, s.cards],
  );
  const scheduled = useMemo(() => scheduledEvents(s.config?.effective ?? null), [s.config]);

  /** river bands: THIS day's impressions per ad, straight from the events */
  const river: RiverSeries[] = useMemo(() => creatives.map((c) => ({
    id: String(c.id),
    name: c.name,
    color: c.color,
    imageUrl: c.imageUrl ? proxied(c.imageUrl) : undefined,
    perDay: d.sawPerTick.map((row) => row[String(c.id)] ?? 0),
  })), [creatives, d.sawPerTick]);

  /** today's share + CTR per ad, for the roster cards */
  const adStats = useMemo(() => {
    const today = d.sawPerTick[t] ?? {};
    const total = Object.values(today).reduce((a, b) => a + b, 0) || 1;
    const cum = d.funnelCum[t] ?? {};
    return Object.fromEntries(creatives.map((c) => {
      const row = cum[String(c.id)] ?? {};
      const saw = row.SAW ?? 0;
      const ctr = saw ? (row.CLICKED ?? 0) / saw : null;
      return [c.id, (
        <>
          <b>{Math.round((100 * (today[String(c.id)] ?? 0)) / total)}%</b> of today
          {" · "}CTR {ctr == null ? "—" : `${(100 * ctr).toFixed(1)}%`}
        </>
      )];
    }));
  }, [creatives, d.sawPerTick, d.funnelCum, t]);

  const allocated = Boolean(
    (s.config?.raw as { exposure?: { allocation?: { enabled?: boolean } } })
      ?.exposure?.allocation?.enabled);

  const drift = s.results?.preference_drift ?? [];
  const driftConcept = useMemo(() => {
    let best: number | null = null, bestDelta = 0;
    for (const row of drift) {
      const vals = row.series.filter((v): v is number => v != null);
      if (vals.length >= 2 && Math.abs(vals[vals.length - 1] - vals[0]) > bestDelta) {
        bestDelta = Math.abs(vals[vals.length - 1] - vals[0]);
        best = row.concept;
      }
    }
    return best;
  }, [drift]);

  const detected = useMemo(() => {
    const trustKey = Object.keys(s.beliefAvg).find((x) => x.endsWith(":all"));
    const traj = s.results?.reference_price_trajectory ?? [];
    const byConcept = new Map<number, (number | null)[]>();
    for (const row of drift) {
      const agg = byConcept.get(row.concept) ?? Array.from({ length: ticks }, () => null as number | null);
      row.series.forEach((v, i) => { if (v != null && i < ticks) agg[i] = agg[i] == null ? v : (agg[i]! + v) / 2; });
      byConcept.set(row.concept, agg);
    }
    const lead = creatives[0];
    return detectEvents({
      head: Math.max(0, s.headTick),
      driftSeries: [...byConcept.entries()].slice(0, 3).map(([c, series]) => ({ label: `concept ${c}`, series })),
      trust: trustKey ? s.beliefAvg[trustKey] : [],
      ctrLead: lead ? [{ label: lead.name, series: ctrSeries(s.results, String(lead.id), ticks) }] : [],
      fatigue: d.fatigue,
      fatigueSplit: s.results?.fatigue_split?.brand_msg ?? null,
      refPrice: traj.map((r) => r.mean_reference_price),
      listPrice: traj.length ? Math.max(...traj.map((r) => r.current_price ?? 0)) || null : null,
    });
  }, [s.results, s.beliefAvg, s.headTick, d.fatigue, creatives, drift, ticks]);

  const armInfo = experiment
    ? {
        idx: experiment.arm_runs.findIndex((r) => r.run_id === runId) + 1,
        total: experiment.arm_runs.length,
        running: experiment.arm_runs.find((r) => r.status === "running" && r.run_id !== runId),
      }
    : null;
  const live = s.mode === "live" && s.followHead;

  return (
    <>
      <Stepper steps={pipelineSteps({
        hasAds: true, perceived: true, launched: true,
        runStatus: s.status, tick: s.headTick, ticks,
        hasResults: s.status === "complete",
        hasComparison: Boolean(experiment?.comparison),
      })} />
      <main className="wrap">
      <div className="sechead">
        <h1>Simulated market</h1>
        <div className="secmeta">
          {s.config?.effective.population_size ?? s.population?.shoppers.length ?? "—"} shoppers
          {" · seed "}{s.manifest?.seed ?? "—"}
          {" · arm "}{s.config?.effective.arm ?? "—"}
          {armInfo && ` (${armInfo.idx}/${armInfo.total})`}
          {allocated && " · adaptive allocation ON"}
        </div>
        <div className="secactions">
          {armInfo?.running && (
            <span className="statuschip">
              ARM {armInfo.running.arm} RUNNING —{" "}
              <Link href={`/market/${armInfo.running.run_id}`}>watch</Link>
            </span>
          )}
          <button className={`storybtn ${story ? "on" : ""}`} onClick={() => setStory(!story)}
            aria-pressed={story}>STORY {story ? "▪" : "▸"}</button>
          <EtaChip />
          <div className="modetoggle" role="group" aria-label="Playback mode">
            <button className={!live ? "on" : ""}
              onClick={() => seek(t)} aria-pressed={!live}>REPLAY</button>
            <button className={live ? "on" : ""} onClick={followHead}
              aria-pressed={live} disabled={s.mode !== "live"}>LIVE</button>
          </div>
        </div>
      </div>
      {s.error && <div className="errbox" style={{ marginBottom: 12 }}>{s.error}</div>}
      {s.warning && <div className="warnbox" style={{ marginBottom: 12 }}>{s.warning}</div>}

      {s.phase === "starting" ? <EnginePreflight /> : (
        <>
      <FlightKpis t={t} ticks={ticks} />

      <div className="panel hero">
        <div className="ph">
          ALLOCATION RIVER · IMPRESSIONS / AD / DAY
          <span className="phnote">
            engine day {s.headTick + 1}/{ticks} simulated
          </span>
        </div>
        <AllocationRiver series={river} ticks={ticks} t={t} frac={s.frac}
          allocated={allocated} />
        {live && s.status !== "complete" && t >= s.headTick && (
          <div className="pc">
            <span className="waitpill">
              WAITING FOR ENGINE · SIMULATING DAY {s.headTick + 2}
              <span className="bar"><i style={{ width: `${Math.round(s.frac * 100)}%` }} /></span>
            </span>
          </div>
        )}
      </div>

      <AdRoster cards={s.cards ?? []} stats={adStats} />

      <MasterTimeline scheduled={scheduled} detected={detected} />

      <CtrSmallMultiples t={t} creatives={creatives} ticks={ticks} />
        </>
      )}

      <details className="drawer-sec">
        <summary>TERMINAL PANELS · funnel, page A/B, market state, the tape</summary>
        <div className="drawer-body">
          <KpiTiles t={t} />
          <div className="row3" style={{ gridTemplateColumns: "1.4fr 1fr 0.8fr" }}>
            <CtrByDayPanel t={t} creatives={creatives} />
            <FunnelByCreativePanel t={t} creatives={creatives} />
            <PageAbPanel />
          </div>
          <SmallMultiples t={t} />
          <div className="row3" style={{ gridTemplateColumns: "1fr 1.2fr 1fr" }}>
            <EventsLedgerPanel t={t} scheduled={scheduled} detected={detected} />
            <ActivityPanel t={t} onInspect={openInspector} />
            <Tape t={t} driftConcept={driftConcept} onInspect={openInspector}
              scheduled={scheduled} detected={detected} />
          </div>
        </div>
      </details>

      <div className="panel note" style={{ fontFamily: "var(--mono)", fontSize: 11 }}>
        run {runId} · block {s.manifest?.run_index ?? "—"} · every series is engine truth —
        the view plays simulated days at demo pace ·{" "}
        <Link href={`/runs/${runId}/results`}>full results →</Link>
      </div>

      {story && (
        <StoryMode t={t} onClose={() => setStory(false)}
          onInspect={(o) => { setStory(false); openInspector(o); }}
          scheduled={scheduled} detected={detected} />
      )}
      {inspected != null && (
        <Inspector offset={Number(inspected)} viewTick={t} creatives={creatives} onClose={closeInspector} />
      )}
      </main>
    </>
  );
}

export default function MarketPage({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = use(params);
  return (
    <Suspense fallback={<main className="wrap"><div className="panel note">loading…</div></main>}>
      <MarketInner runId={runId} />
    </Suspense>
  );
}
