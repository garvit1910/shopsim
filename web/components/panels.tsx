"use client";

/** Supporting panels: KPI tiles, funnel flow + movers, page A/B, events
 * ledger, small multiples. Every number is a slice of engine data at the
 * viewing tick. */

import { useEffect, useRef, useState } from "react";
import { useMarket } from "@/lib/market";
import {
  FUNNEL_STAGES, STAGE_NAMES, ctrSeries, derive, kpisAt, revenueAt, segmentOf,
  fatigueSeries,
} from "@/lib/selectors";
import type { DetectedEvent, ScheduledEvent } from "@/lib/detectors";
import type { CreativeCard } from "@/lib/types";
import { fmtInt, fmtPct, fmtUsd, fmtW, shopperLabel } from "@/lib/format";
import { adjusted, adjustedSeries, fmtFactor, isAdjusted } from "@/lib/economics";
import { runAdjust } from "./market";
import { LineChart, Spark, colorForCreative } from "./charts";

/** Identity for a creative on a chart. The optional fields come from the
 * creatives endpoint; every consumer works without them, so panels that only
 * need a name and a colour are unaffected. */
export interface CreativeInfo {
  id: number; name: string; color: string; start: number;
  headline?: string; brandName?: string; imageUrl?: string | null;
  card?: CreativeCard;
}

export function creativesFromConfig(
  schedule: { creative_id: number; start_tick: number }[] | undefined,
  names: Record<string, string> | undefined,
  cards?: CreativeCard[] | null,
  /** Creative ids observed in the run's own results, used only when there is
   * no schedule to read. A run launched outside the orchestrator has no
   * run_config, so `schedule` is undefined and this used to return [] — which
   * silently emptied the allocation river, the CTR small-multiples and the ad
   * roster even though the engine had published perfectly good per-creative
   * numbers. The ids the run actually served are the honest fallback. */
  observedIds?: number[],
): CreativeInfo[] {
  const byId = new Map((cards ?? []).map((c) => [c.creative_id, c]));
  const seen = new Map<number, number>();
  for (const row of schedule ?? []) {
    const cur = seen.get(row.creative_id);
    seen.set(row.creative_id, cur == null ? row.start_tick : Math.min(cur, row.start_tick));
  }
  if (!seen.size) {
    for (const id of observedIds ?? []) seen.set(id, 0);
  }
  return [...seen.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([id, start], i) => {
      const card = byId.get(id);
      return {
        id, start,
        name: card?.name ?? names?.[String(id)] ?? `Creative ${id}`,
        color: colorForCreative(i),
        headline: card?.headline,
        brandName: card?.brand_name,
        imageUrl: card?.image_url ?? null,
        card,
      };
    });
}

/** The closed Concept/Category vocabularies (contracts/enums.py, Law 11). */
export const CONCEPT_NAMES: Record<number, string> = {
  5000: "performance", 5001: "comfort", 5002: "durability", 5003: "eco_friendly",
  5004: "recycled_materials", 5005: "lightweight", 5006: "cushioning",
  5007: "breathable", 5008: "waterproof", 5009: "vegan", 5010: "premium",
  5011: "discount", 5012: "value_priced", 5013: "free_shipping",
  5014: "fast_shipping", 5015: "free_returns", 5016: "warranty", 5017: "style",
  5018: "innovative", 5019: "sustainable_packaging", 5020: "locally_made",
  5021: "handcrafted", 5022: "limited_edition", 5023: "award_winning",
  5024: "expert_endorsed", 5025: "wide_sizes", 5026: "arch_support",
  5027: "grip", 5028: "machine_washable", 5029: "other",
  5500: "casual_shoes", 5501: "trail_shoes", 5502: "sandals", 5503: "socks",
  5504: "running_shoes", 5505: "apparel", 5506: "accessories",
  5507: "fitness_equipment", 5508: "recovery", 5509: "outdoor_gear",
};
export const conceptName = (id: number) => CONCEPT_NAMES[id] ?? `concept ${id}`;

export function KpiTiles({ t }: { t: number }) {
  const s = useMarket();
  const d = derive(s.eventsByTick);
  if (s.headTick < 0) return null;
  const k = kpisAt(d, s.results, t);
  const kPrev = t > 0 ? kpisAt(d, s.results, t - 1) : null;
  // human-scale CTR (v3.13-draft), the same adjusting factor as the flight row
  const a = runAdjust(s, s.manifest?.ticks ?? Math.max(1, s.headTick + 1));
  const trustKey = Object.keys(s.beliefAvg).find((x) => x.endsWith(":all"));
  const trust = trustKey ? s.beliefAvg[trustKey] : [];
  const delta = (cur: number, prev: number | null | undefined, fm: (n: number) => string) =>
    prev == null ? "" : cur === prev ? "— flat" : `${cur > prev ? "▲ +" : "▼ "}${fm(Math.abs(cur - prev))} today`;
  const tiles: [string, string, React.ReactNode][] = [
    ["IMPRESSIONS", fmtInt(k.imp), delta(k.imp, kPrev?.imp, fmtInt)],
    ["CLICKS", fmtInt(k.clicks), delta(k.clicks, kPrev?.clicks, fmtInt)],
    ["REAL CTR", fmtPct(adjusted(k.ctr, a)),
      <Spark key="s" data={adjustedSeries(s.results?.ctr_by_day.map((r) => r.ctr) ?? [], a)} upto={t} color="var(--info)" />],
    ["CARTS", fmtInt(k.carts), delta(k.carts, kPrev?.carts, fmtInt)],
    ["BUYS", fmtInt(k.buys), delta(k.buys, kPrev?.buys, fmtInt)],
    ["REVENUE", fmtUsd(revenueAt(s.eventsByTick, t)), ""],
    ["ACTIVE NEEDS", fmtInt(k.needs), <Spark key="s" data={d.needsCount} upto={t} color="var(--accent)" min={0} />],
    ["AVG TRUST", fmtW(trust[t] ?? null), <Spark key="s" data={trust} upto={t} color="var(--info)" />],
  ];
  return (
    <div className="tiles">
      {tiles.map(([l, v, extra]) => (
        <div className="panel tile" key={l}>
          <div className="l">{l}</div>
          <div className="v">{v}</div>
          <div className={`d ${typeof extra === "string" && extra.startsWith("▼") ? "dn" : ""}`}>{extra || " "}</div>
        </div>
      ))}
    </div>
  );
}

/** CTR BY DAY · PER CREATIVE — the D5 panel, container-measured like the
 * mock's lineChart (legend row, 5 gridlines, fill on the first series). */
export function CtrByDayPanel({ t, creatives }: { t: number; creatives: CreativeInfo[] }) {
  const s = useMarket();
  const ref = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(620);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setW(Math.max(280, el.clientWidth || 620)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const ticks = s.manifest?.ticks ?? Math.max(1, s.headTick + 1);
  const h = 150, p = { t: 8, r: 10, b: 18, l: 40 };
  const iw = w - p.l - p.r, ih = h - p.t - p.b;
  const a = runAdjust(s, ticks);
  const series = creatives.map((c) => ({
    ...c, data: adjustedSeries(ctrSeries(s.results, String(c.id), ticks), a),
  }));
  const vis = series.flatMap((sr) => sr.data.slice(0, t + 1)).filter((v): v is number => v != null);
  const hi = Math.max(0.002, ...vis) * 1.1;
  const X = (i: number) => p.l + (iw * i) / Math.max(1, ticks - 1);
  const Y = (v: number) => p.t + ih * (1 - v / hi);
  return (
    <div className="panel">
      <div className="ph">
        CTR BY DAY · PER CREATIVE
        {isAdjusted(a) && <span className="phnote">AT REAL CTR · RAW {fmtFactor(a)}</span>}
      </div>
      <div className="legend">
        {series.map((sr) => (
          <span key={sr.id}><i style={{ background: sr.color }} />{sr.name}</span>
        ))}
      </div>
      <div className="pc" ref={ref}>
        <svg viewBox={`0 0 ${w} ${h}`} width="100%" height={h} role="img" aria-label="CTR by day per creative">
          {[0, 1, 2, 3, 4].map((i) => {
            const y = p.t + (ih * i) / 4, v = hi * (1 - i / 4);
            return (
              <g key={i}>
                <line x1={p.l} x2={w - p.r} y1={y} y2={y} stroke="var(--grid)" />
                <text x={p.l - 5} y={y + 3.5} textAnchor="end" fontSize={9} fill="var(--muted)" fontFamily="var(--mono)">{fmtPct(v, 1)}</text>
              </g>
            );
          })}
          {[0, Math.floor((ticks - 1) / 2), ticks - 1].map((i) => (
            <text key={i} x={X(i)} y={h - 4} textAnchor="middle" fontSize={9} fill="var(--muted)" fontFamily="var(--mono)">d{i + 1}</text>
          ))}
          {series.map((sr, si) => {
            let d = "";
            let started = false;
            const pts: [number, number][] = [];
            sr.data.forEach((v, i) => {
              if (i > t || v == null) return;
              d += `${started ? "L" : "M"}${X(i).toFixed(1)} ${Y(v).toFixed(1)}`;
              started = true;
              pts.push([i, v]);
            });
            if (!started) return null;
            const last = pts[pts.length - 1], first = pts[0];
            return (
              <g key={sr.id}>
                {si === 0 && (
                  <path d={`${d} L ${X(last[0])} ${p.t + ih} L ${X(first[0])} ${p.t + ih} Z`} fill={sr.color} opacity={0.08} />
                )}
                <path d={d} fill="none" stroke={sr.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
                <circle cx={X(last[0])} cy={Y(last[1])} r={3} fill={sr.color} />
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}

/** FUNNEL BY CREATIVE · CUMULATIVE — the D5 panel: per-creative section
 * headers + five stage bars scaled to the shared SAW max. */
export function FunnelByCreativePanel({ t, creatives }: { t: number; creatives: CreativeInfo[] }) {
  const s = useMarket();
  const d = derive(s.eventsByTick);
  const cum = d.funnelCum[t] ?? {};
  const mx = Math.max(1, ...creatives.map((c) => cum[c.id]?.SAW ?? 0));
  const opacity = [0.45, 0.65, 0.8, 1, 1];
  return (
    <div className="panel">
      <div className="ph">FUNNEL BY CREATIVE · CUMULATIVE</div>
      <div className="pc">
        {creatives.map((c) => (
          <div key={c.id}>
            <div className="creativehdr" style={{ color: c.color }}>{c.name.toUpperCase()}</div>
            {FUNNEL_STAGES.map((st, si) => (
              <div className="fbar" key={st}>
                <div className="fl">{st}</div>
                <div className="ft">
                  <i style={{
                    width: `${((100 * (cum[c.id]?.[st] ?? 0)) / mx).toFixed(2)}%`,
                    background: c.color, opacity: opacity[si],
                  }} />
                </div>
                <div className="fv num">{cum[c.id]?.[st] ?? 0}</div>
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

const ACTIVITY_TYPES = new Set(["CLICKED", "BROWSED", "CARTED", "BOUGHT", "BOUNCED",
  "EXPERIENCED", "NEED_ACTIVATED", "NEED_SATISFIED"]);

/** ACTIVITY — the D5 table: recent real events, rows clickable → inspector. */
export function ActivityPanel({ t, onInspect }: { t: number; onInspect: (offset: number) => void }) {
  const s = useMarket();
  const rows: { day: number; offset: number; type: string; detail: string }[] = [];
  for (let day = t; day >= Math.max(0, t - 1) && rows.length < 14; day--) {
    const evs = s.eventsByTick[day] ?? [];
    for (let i = evs.length - 1; i >= 0 && rows.length < 14; i--) {
      const rec = evs[i];
      if (!ACTIVITY_TYPES.has(rec.type)) continue;
      rows.push({
        day, offset: (rec.shopper_id ?? 0) % 100_000, type: rec.type,
        detail: rec.type === "BOUGHT" && rec.price ? `$${rec.price.toFixed(2)}`
          : rec.type === "EXPERIENCED" && rec.sat != null ? `sat ${rec.sat.toFixed(2)}`
          : rec.type === "NEED_ACTIVATED" ? `strength ${rec.strength ?? "—"}`
          : String(rec.subject ?? ""),
      });
    }
  }
  return (
    <div className="panel">
      <div className="ph">ACTIVITY · CLICK A ROW TO INSPECT</div>
      <div className="pc" style={{ overflow: "auto", maxHeight: 300 }}>
        <table className="term">
          <thead><tr><th>Day</th><th>Shopper</th><th>Segment</th><th>Action</th><th>Detail</th></tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="click" onClick={() => onInspect(r.offset)}>
                <td className="num">d{r.day + 1}</td>
                <td><b>{shopperLabel(r.offset)}</b></td>
                <td style={{ color: "var(--ink-2)", fontSize: 11 }}>{segmentOf(s.population, r.offset)}</td>
                <td className="mono" style={{ fontSize: 10.5 }}>{r.type}</td>
                <td style={{ color: "var(--ink-2)" }}>{r.detail}</td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={5} style={{ color: "var(--muted)" }}>nothing yet</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function FunnelFlowPanel({ t, creatives, onInspect }: {
  t: number; creatives: CreativeInfo[]; onInspect: (offset: number) => void;
}) {
  const s = useMarket();
  const d = derive(s.eventsByTick);
  const cum = d.funnelCum[t] ?? {};
  const totalSaw = Math.max(1, creatives.reduce((a, c) => a + (cum[c.id]?.SAW ?? 0), 0));
  const today = s.eventsByTick[t] ?? [];
  const todayCount = (stage: string) => today.filter((e) => e.type === stage).length;
  const movers = (d.movers[t] ?? []).filter((m) => m.stage >= 2).slice(0, 12);
  const opacity = [0.45, 0.62, 0.78, 0.9, 1];
  return (
    <div className="panel">
      <div className="ph">FUNNEL FLOW · WIDTHS = CUMULATIVE COUNTS · SEGMENTS = CREATIVES</div>
      <div className="flow">
        {FUNNEL_STAGES.map((stage, si) => {
          const stageTotal = creatives.reduce((a, c) => a + (cum[c.id]?.[stage] ?? 0), 0);
          const n = todayCount(stage);
          return (
            <div className="frow" key={stage}>
              <div className="fl">{stage}</div>
              <div className="ftrack">
                {creatives.map((c) => (
                  <div key={c.id} className="fseg" style={{
                    width: `${((100 * (cum[c.id]?.[stage] ?? 0)) / totalSaw).toFixed(2)}%`,
                    background: c.color, opacity: opacity[si],
                  }} />
                ))}
              </div>
              <div className="fnum num">{stageTotal}</div>
              <div className={`fdelta ${n > 0 ? "on" : ""}`}>{n > 0 ? `+${n} today` : ""}</div>
            </div>
          );
        })}
      </div>
      <div className="movers">
        <div className="mh">MOVED TODAY · REAL SHOPPERS WHO ADVANCED · CLICK TO INSPECT</div>
        <div className="mchips">
          {movers.length === 0 && <span className="mono" style={{ fontSize: 10.5, color: "var(--muted)" }}>no stage advances yet today</span>}
          {movers.map((m) => (
            <button key={m.offset} className="mchip" onClick={() => onInspect(m.offset)}
              title={segmentOf(s.population, m.offset)}>
              <b>{shopperLabel(m.offset)}</b>
              <span className={`st ${m.stage === 5 ? "buy" : ""}`}>→ {STAGE_NAMES[m.stage].toUpperCase()}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

export function PageAbPanel() {
  const s = useMarket();
  const pages = s.results?.funnel_by_page;
  const entries = Object.entries(pages ?? {});
  return (
    <div className="panel">
      <div className="ph">PAGE A/B · BOUNCE RATE · CUMULATIVE</div>
      <div className="pc">
        {entries.length === 0 && <div className="note">No page-variant traffic in this run.</div>}
        {entries.map(([page, row]) => {
          const visited = row.VISITED ?? 0, bounced = row.BOUNCED ?? 0;
          const rate = visited + bounced ? bounced / (visited + bounced) : null;
          return (
            <div key={page} style={{ margin: "12px 0" }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontFamily: "var(--mono)", fontSize: 10.5, color: "var(--ink-2)" }}>
                <span>page {page}</span><b style={{ color: "var(--ink)" }}>{fmtPct(rate, 1)}</b>
              </div>
              <div className="bar" style={{ marginTop: 4 }}>
                <i style={{ width: `${rate == null ? 0 : (100 * rate).toFixed(1)}%`, background: Number(page) % 2 ? "var(--info)" : "var(--bad)" }} />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function EventsLedgerPanel({ t, scheduled, detected }: {
  t: number; scheduled: ScheduledEvent[]; detected: DetectedEvent[];
}) {
  const rows = [
    ...scheduled.filter((e) => e.tick <= t).map((e) => ({ t: e.tick, k: "sched", kl: "SCHED", l: e.label, d: e.detail })),
    ...detected.filter((e) => e.tick <= t).map((e) => ({ t: e.tick, k: e.severity, kl: "DETECT", l: e.label, d: `${e.detail} · rule: ${e.rule}` })),
  ].sort((a, b) => b.t - a.t);
  return (
    <div className="panel">
      <div className="ph">MARKET EVENTS · SCHEDULED + DETECTED</div>
      <div className="pc" style={{ overflow: "auto", maxHeight: 260 }}>
        <table className="term">
          <thead><tr><th>Day</th><th>Kind</th><th>Event</th></tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} title={r.d}>
                <td className="num">d{r.t + 1}</td>
                <td><span className={`evk ${r.k}`}>{r.kl}</span></td>
                <td><b>{r.l}</b></td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={3} style={{ color: "var(--muted)" }}>nothing yet</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function SmallMultiples({ t }: { t: number }) {
  const s = useMarket();
  const d = derive(s.eventsByTick);
  const ticks = s.manifest?.ticks ?? Math.max(1, s.headTick + 1);
  const drift = s.results?.preference_drift ?? [];
  // aggregate concept series across segments (mean of segment means per tick)
  const concepts = new Map<number, (number | null)[][]>();
  for (const row of drift) {
    const list = concepts.get(row.concept) ?? [];
    list.push(row.series);
    concepts.set(row.concept, list);
  }
  const conceptSeries = [...concepts.entries()].map(([concept, seriesList]) => {
    const out: (number | null)[] = [];
    for (let i = 0; i < ticks; i++) {
      const vals = seriesList.map((sr) => sr[i]).filter((v): v is number => v != null);
      out.push(vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null);
    }
    const first = out.find((v) => v != null) ?? 0;
    const last = [...out].reverse().find((v) => v != null) ?? 0;
    return { concept, series: out, delta: Math.abs((last ?? 0) - (first ?? 0)) };
  }).sort((a, b) => b.delta - a.delta);
  const top = conceptSeries.slice(0, 3);
  const trustKey = Object.keys(s.beliefAvg).find((x) => x.endsWith(":all"));
  const trust = trustKey ? s.beliefAvg[trustKey] : [];
  // CONTRACT v3.8-draft: the engine's own fatigue channels when the run has
  // them, the client-side derivation when it does not (never both at once).
  const brandFatigue = fatigueSeries(s.results, "brand_msg", ticks);
  const assetFatigue = fatigueSeries(s.results, "asset", ticks);
  const traj = s.results?.reference_price_trajectory ?? [];
  const refSeries = Array.from({ length: ticks }, (_, i) => traj[i]?.mean_reference_price ?? null);
  const shelfSeries = Array.from({ length: ticks }, (_, i) => traj[i]?.current_price ?? null);
  const colors = ["#1baf7a", "#2a78d6", "#eb6834"];
  return (
    <div className="sm">
      <div className="panel">
        <div className="ph">PREFERENCE DRIFT · POPULATION MEAN · TOP CONCEPTS</div>
        <div className="pc">
          <LineChart ticks={ticks} upto={t} h={110} yFmt={(v) => v.toFixed(2)}
            aria="preference drift"
            series={top.map((c, i) => ({ data: c.series, color: colors[i], label: conceptName(c.concept) }))} />
        </div>
      </div>
      <div className="panel">
        <div className="ph">AVG BRAND TRUST · LIVE BELIEFS</div>
        <div className="pc">
          {trust.length
            ? <LineChart ticks={ticks} upto={t} h={110} yFmt={(v) => v.toFixed(2)} aria="average brand trust"
                series={[{ data: trust, color: "var(--info)", fill: true }]} />
            : <div className="note">belief_avg lands with the v3.5 sweep — older runs have no live trust series.</div>}
        </div>
      </div>
      <div className="panel">
        <div className="ph">ACTIVE NEEDS · LIVE COUNT</div>
        <div className="pc">
          <LineChart ticks={ticks} upto={t} h={110} min={0} yFmt={(v) => v.toFixed(0)} aria="active needs"
            series={[{ data: d.needsCount, color: "#1baf7a", fill: true }]} />
        </div>
      </div>
      <div className="panel">
        <div className="ph">REFERENCE PRICE vs SHELF · HERO PRODUCT</div>
        <div className="pc">
          <LineChart ticks={ticks} upto={t} h={110} yFmt={(v) => "$" + v.toFixed(0)} aria="reference price vs shelf"
            series={[
              { data: shelfSeries, color: "#898781", dash: "3 3" },
              { data: refSeries, color: "#c98500", fill: true, label: "reference" },
            ]} />
        </div>
      </div>
      <div className="panel">
        <div className="ph">
          {brandFatigue
            ? "MESSAGE FATIGUE · ENGINE CHANNELS (C3 fatigue_split)"
            : "MESSAGE FATIGUE · MEAN TOP-CREATIVE EXPOSURES (DERIVED)"}
        </div>
        <div className="pc">
          {brandFatigue
            ? <LineChart ticks={ticks} upto={t} h={110} min={0} max={1}
                yFmt={(v) => v.toFixed(2)} aria="message fatigue channels"
                series={[
                  { data: brandFatigue, color: "#eb6834", fill: true, label: "brand msg" },
                  { data: assetFatigue ?? [], color: "#c98500", label: "asset wearout" },
                ]} />
            : <LineChart ticks={ticks} upto={t} h={110} min={0} yFmt={(v) => v.toFixed(1)} aria="message fatigue"
                series={[{ data: d.fatigue, color: "#eb6834", fill: true }]} />}
        </div>
        {!brandFatigue && (
          <div className="note" style={{ padding: "0 14px 10px" }}>
            derived from the event stream — fatigue_split lands with the Phase-6
            report, so runs recorded before it have no engine channel.
          </div>
        )}
      </div>
      <div className="panel">
        <div className="ph">GOAL CONVERSION · P(BUY | NEED) SPLIT</div>
        <div className="pc" style={{ padding: "10px 14px" }}>
          {(() => {
            const gs = s.results?.goal_stats;
            const on = gs?.p_buy_need_on ?? null, off = gs?.p_buy_need_off ?? null;
            return (
              <div style={{ fontFamily: "var(--mono)", fontSize: 12 }}>
                <div style={{ display: "flex", justifyContent: "space-between", margin: "8px 0" }}>
                  <span>need ON</span><b>{fmtPct(on, 1)}</b></div>
                <div className="bar"><i style={{ width: `${(100 * (on ?? 0)).toFixed(1)}%`, background: "#1baf7a" }} /></div>
                <div style={{ display: "flex", justifyContent: "space-between", margin: "10px 0 0" }}>
                  <span>need OFF</span><b>{fmtPct(off, 1)}</b></div>
                <div className="bar" style={{ marginTop: 4 }}><i style={{ width: `${(100 * (off ?? 0)).toFixed(1)}%`, background: "#c3c2b7" }} /></div>
                {on != null && off != null && off > 0 && (
                  <div style={{ marginTop: 8, color: "var(--good)" }}>needs multiply buying ×{(on / off).toFixed(1)}</div>
                )}
              </div>
            );
          })()}
        </div>
      </div>
    </div>
  );
}


/** Phase 6 (CONTRACT v3.8-draft): the statistical half of the MetricsReport.
 * Every figure here is the engine's, not the dashboard's — the intervals are
 * bootstrap replicates over SHOPPERS (a person's events are one correlated
 * story, so the shopper is the independent unit) and the coverage line is a
 * sweep of the graph's own receipts. A run recorded before Phase 6 shows the
 * absence plainly rather than a blank panel. */
export function ConfidencePanel() {
  const s = useMarket();
  const r = s.results;
  const ci = r?.ci ?? {};
  const pc = r?.provenance_coverage ?? null;
  const ltv = (r?.repeat_ltv_by_arm ?? [])[0];
  const social = r?.social_lift ?? null;

  const rows: { label: string; point: number | null; key: string }[] = [];
  const totals: Record<string, number> = {};
  for (const segments of Object.values(r?.funnel ?? {}))
    for (const counts of Object.values(segments))
      for (const [k, v] of Object.entries(counts)) totals[k] = (totals[k] ?? 0) + v;
  const ratio = (a: string, b: string) => (totals[b] ? totals[a] / totals[b] : null);
  rows.push({ label: "CTR", point: ratio("CLICKED", "SAW"), key: "ctr" });
  rows.push({ label: "browse | click", point: ratio("BROWSED", "CLICKED"), key: "browse_rate" });
  rows.push({ label: "cart | browse", point: ratio("CARTED", "BROWSED"), key: "cart_rate" });
  rows.push({ label: "buy | cart", point: ratio("BOUGHT", "CARTED"), key: "buy_rate" });
  rows.push({ label: "P(buy | need)", point: r?.goal_stats?.p_buy_need_on ?? null, key: "p_buy_need_on" });
  rows.push({ label: "P(buy | no need)", point: r?.goal_stats?.p_buy_need_off ?? null, key: "p_buy_need_off" });

  const hasCi = Object.keys(ci).length > 0;
  return (
    <div className="panel" style={{ marginBottom: 12 }}>
      <div className="ph">CONFIDENCE &amp; RECEIPTS · C3 ci / provenance_coverage · 95% BOOTSTRAP OVER SHOPPERS</div>
      <div className="pc" style={{ overflowX: "auto" }}>
        <table className="term">
          <thead><tr><th>Rate</th><th>Point</th><th>95% interval</th></tr></thead>
          <tbody>
            {rows.map((row) => {
              const span = ci[row.key];
              return (
                <tr key={row.key}>
                  <td className="mono">{row.label}</td>
                  <td className="num">{row.point == null ? "—" : fmtPct(row.point, 2)}</td>
                  <td className="num mono" style={{ fontSize: 11 }}>
                    {span ? `${fmtPct(span[0], 2)} – ${fmtPct(span[1], 2)}` : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {!hasCi && (
          <div className="note" style={{ paddingTop: 8 }}>
            No intervals: this run carries no per-shopper counts, which land with
            the Phase-6 report. The point estimates above are still the engine&apos;s.
          </div>
        )}
        {pc && (
          <div style={{ marginTop: 10, fontSize: 12.5 }}>
            <b>{fmtPct(pc.coverage, 1)}</b> of subjective versions carry a cause —{" "}
            <span className="mono" style={{ fontSize: 11, color: "var(--ink-2)" }}>
              learned PREFERS {pc.prefers.with_cause}/{pc.prefers.learned_versions},
              live beliefs {pc.beliefs.with_provenance}/{pc.beliefs.versions};
              causes {Object.entries(pc.prefers.cause_kinds).map(([k, v]) => `${k}:${v}`).join(" ") || "—"}
            </span>
            <div className="note" style={{ marginTop: 4 }}>
              SAW never appears among the causes — exposure teaches expectations, not taste (Law 14).
            </div>
          </div>
        )}
        {ltv?.buyers ? (
          <div style={{ marginTop: 8, fontSize: 12.5 }}>
            <b>{ltv.buyers}</b> buyers, {ltv.buys} purchases,{" "}
            repeat rate <b>{fmtPct(ltv.repeat_rate, 1)}</b>,{" "}
            {fmtUsd(ltv.revenue_per_buyer ?? 0)} per buyer
            <span className="note"> (realized over the simulated window — no projection)</span>
          </div>
        ) : null}
        {social && (
          <div style={{ marginTop: 8, fontSize: 12.5 }}>
            Social proof: P(buy) {fmtPct(social.p_buy_social_on, 2)} with a trusted peer&apos;s
            purchase behind the decision vs {fmtPct(social.p_buy_social_off, 2)} without
            <span className="note"> — {social.note}</span>
          </div>
        )}
      </div>
    </div>
  );
}
