"use client";

/** Full C3 results (5.6) — the same series the live view renders, at the
 * final tick, plus the segment heatmap, motif stats, and the Grade-1
 * recommendations mined from the MetricsReport. */

import Link from "next/link";
import { use, useEffect, useMemo } from "react";
import { openRun, useMarket } from "@/lib/market";
import { ctrSeries, derive } from "@/lib/selectors";
import { detectEvents, scheduledEvents } from "@/lib/detectors";
import { mineRecommendations } from "@/lib/recommendations";
import {
  ConfidencePanel, KpiTiles, PageAbPanel, SmallMultiples, conceptName,
  creativesFromConfig,
} from "@/components/panels";
import { LineChart } from "@/components/charts";
import { fmtPct } from "@/lib/format";

const STAGES = ["SAW", "CLICKED", "BROWSED", "CARTED", "BOUGHT"];

export default function ResultsPage({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = use(params);
  const s = useMarket();
  useEffect(() => { openRun(runId); }, [runId]);

  const ticks = s.manifest?.ticks ?? 1;
  const t = Math.max(0, Math.min(ticks - 1, s.headTick));
  const d = derive(s.eventsByTick);
  const creatives = useMemo(
    () => creativesFromConfig(s.config?.effective.schedule, s.config?.effective.creative_names),
    [s.config],
  );
  const scheduled = useMemo(() => scheduledEvents(s.config?.effective ?? null), [s.config]);
  const detected = useMemo(() => {
    const trustKey = Object.keys(s.beliefAvg).find((x) => x.endsWith(":all"));
    const traj = s.results?.reference_price_trajectory ?? [];
    const lead = creatives[0];
    return detectEvents({
      head: t,
      driftSeries: [],
      trust: trustKey ? s.beliefAvg[trustKey] : [],
      ctrLead: lead ? [{ label: lead.name, series: ctrSeries(s.results, String(lead.id), ticks) }] : [],
      fatigue: d.fatigue,
      fatigueSplit: s.results?.fatigue_split?.brand_msg ?? null,
      refPrice: traj.map((r) => r.mean_reference_price),
      listPrice: traj.length ? Math.max(...traj.map((r) => r.current_price ?? 0)) || null : null,
    });
  }, [s.results, s.beliefAvg, t, d.fatigue, creatives, ticks]);

  const recs = useMemo(
    () => mineRecommendations({
      results: s.results, detected,
      creativeNames: s.config?.effective.creative_names ?? {},
      fatigue: d.fatigue,
    }),
    [s.results, detected, s.config, d.fatigue],
  );

  const funnel = s.results?.funnel ?? {};
  const armName = s.config?.effective.arm ?? Object.keys(funnel)[0];
  const segFunnel = funnel[armName] ?? {};
  const segIds = Object.keys(segFunnel).sort();
  const maxCount = Math.max(1, ...segIds.flatMap((seg) => STAGES.map((st) => segFunnel[seg]?.[st] ?? 0)));
  const segName = (id: string) =>
    s.population?.segments.find((x) => String(x.segment_id) === id)?.name ?? `segment ${id}`;

  return (
    <main className="wrap">
      <div className="runhead">
        <div className="runlabel"><b>{runId}</b> · full results (C3)</div>
        <span className={`statuschip ${s.status === "complete" ? "done" : ""}`}>{s.status.toUpperCase()}</span>
        <Link className="btn" href={`/market/${runId}`}>← REPLAY THIS RUN LIVE</Link>
      </div>
      {s.error && <div className="errbox" style={{ marginBottom: 12 }}>{s.error}</div>}
      <KpiTiles t={t} />
      <ConfidencePanel />

      <div className="panel" style={{ marginBottom: 12 }}>
        <div className="ph">RECOMMENDATIONS · GRADE 1 · MINED FROM THE METRICSREPORT — EVERY CARD CITES ITS NUMBERS</div>
        <div className="pc" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 10, padding: 12 }}>
          {recs.length === 0 && <div className="note">Not enough signal yet for confident recommendations.</div>}
          {recs.map((r, i) => (
            <div key={i} className="panel" style={{ padding: "10px 14px", background: "var(--card)" }}>
              <div style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
                <span className={`evk ${r.severity === "info" ? "info" : r.severity}`}>{r.severity.toUpperCase()}</span>
                <b style={{ fontSize: 13.5 }}>{r.title}</b>
              </div>
              <div style={{ fontSize: 12.5, color: "var(--ink-2)", margin: "6px 0" }}>{r.body}</div>
              <div className="mono" style={{ fontSize: 10.5, color: "var(--muted)" }}>{r.evidence}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="herorow" style={{ gridTemplateColumns: "1.2fr 1fr" }}>
        <div className="panel">
          <div className="ph">FUNNEL HEATMAP · SEGMENT × STAGE · ARM {armName}</div>
          <div className="pc" style={{ overflowX: "auto" }}>
            <table className="term">
              <thead>
                <tr><th>Segment</th>{STAGES.map((st) => <th key={st}>{st}</th>)}</tr>
              </thead>
              <tbody>
                {segIds.map((seg) => (
                  <tr key={seg}>
                    <td className="mono" style={{ fontSize: 10.5 }}>{segName(seg)}</td>
                    {STAGES.map((st) => {
                      const v = segFunnel[seg]?.[st] ?? 0;
                      const alpha = v === 0 ? 0 : 0.12 + 0.75 * (v / maxCount);
                      return (
                        <td key={st} className="num"
                          style={{ background: `rgba(42,120,214,${alpha.toFixed(2)})`, color: alpha > 0.5 ? "#fff" : "var(--ink)" }}>
                          {v}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        <div className="panel">
          <div className="ph">CTR BY DAY · PER CREATIVE</div>
          <div className="pc">
            <LineChart ticks={ticks} upto={t} h={230} min={0} yFmt={(v) => fmtPct(v, 1)}
              aria="CTR by day per creative"
              series={creatives.map((c) => ({
                data: ctrSeries(s.results, String(c.id), ticks),
                color: c.color,
                label: c.name.slice(0, 10),
              }))} />
          </div>
          <div className="ph">MOTIF STATS · PREVALENCE BY OUTCOME</div>
          <div className="pc" style={{ overflowX: "auto" }}>
            <table className="term">
              <thead><tr><th>Motif</th><th>Mean strength</th><th>Outcomes</th></tr></thead>
              <tbody>
                {Object.entries(s.results?.motif_stats ?? {}).map(([m, row]) => (
                  <tr key={m}>
                    <td className="mono">{m}</td>
                    <td className="num">{row.mean_strength?.toFixed(3) ?? "—"}</td>
                    <td className="mono" style={{ fontSize: 10 }}>
                      {Object.entries(row.prevalence_by_outcome).map(([k, v]) => `${k}:${v}`).join(" ")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div className="row3" style={{ gridTemplateColumns: "1fr 1fr" }}>
        <PageAbPanel />
        <div className="panel">
          <div className="ph">PREFERENCE DRIFT · CONCEPT × SEGMENT SERIES (C3)</div>
          <div className="pc" style={{ overflow: "auto", maxHeight: 260 }}>
            <table className="term">
              <thead><tr><th>Concept</th><th>Segment</th><th>Start → end</th><th>Δ</th></tr></thead>
              <tbody>
                {(s.results?.preference_drift ?? []).map((row, i) => {
                  const vals = row.series.filter((v): v is number => v != null);
                  if (vals.length < 2) return null;
                  const delta = vals[vals.length - 1] - vals[0];
                  return (
                    <tr key={i}>
                      <td className="mono">{conceptName(row.concept)}</td>
                      <td className="mono">{segName(String(row.segment))}</td>
                      <td className="num">{vals[0].toFixed(3)} → {vals[vals.length - 1].toFixed(3)}</td>
                      <td className="num" style={{ color: delta >= 0 ? "var(--good)" : "var(--bad)" }}>
                        {delta >= 0 ? "+" : ""}{delta.toFixed(3)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <SmallMultiples t={t} />
    </main>
  );
}
