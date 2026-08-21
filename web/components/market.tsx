"use client";

/** The Market page's own furniture: the six-tile KPI row (with the flight
 * transport built into the first tile) and the CTR-by-ad small multiples.
 *
 * Money tiles: revenue is simulated (BOUGHT.price), spend is impressions
 * priced at a researched CPM — see lib/economics.ts. */

import { pause, play, seek, setSpeed, useMarket, type MarketState } from "@/lib/market";
import { derive, kpisAt, ctrSeries, revenueAt } from "@/lib/selectors";
import {
  CPM_SOURCE, adjusted, adjustedSeries, ctrAdjust, explainFactor, factorSourceLabel, fmtFactor,
  fmtMoney, fmtRoas, isAdjusted, roasFor, spendFor,
} from "@/lib/economics";
import { REAL_CTR_BAND } from "@/lib/calibration";
import { fmtInt, fmtPct } from "@/lib/format";
import type { CreativeInfo } from "./panels";
import { AdThumb } from "./AdCard";
import { LineChart } from "./charts";

const inBand = (v: number | null) => v != null && v >= REAL_CTR_BAND[0] && v <= REAL_CTR_BAND[1];

/** The adjusting factor for a run, from its WHOLE-run CTR so the headline and
 * every chart share one constant that does not wobble with the scrubber.
 * (The published tiers are constants anyway; this only matters for the band
 * fallback.) */
export function runAdjust(s: MarketState, ticks: number) {
  const d = derive(s.eventsByTick);
  const whole = kpisAt(d, s.results, Math.max(0, Math.min(ticks, s.headTick + 1) - 1));
  return ctrAdjust(s.config, whole.ctr, whole.imp);
}

export function FlightKpis({ t, ticks }: { t: number; ticks: number }) {
  const s = useMarket();
  const d = derive(s.eventsByTick);
  const k = kpisAt(d, s.results, t);
  const revenue = revenueAt(s.eventsByTick, t);
  const spend = spendFor(k.imp);
  const roas = roasFor(revenue, spend);

  // The headline CTR and ROAS are ALWAYS human-scale: raw ÷ the adjusting
  // factor (lib/economics.ts ctrAdjust — engine-published, mirrored table, or
  // band normalisation, in that order). The raw rate and the factor are
  // printed beside them, never hidden. A raw 35% on the retired 2.0 base reads
  // ~1.1% here; a run on the calibrated base is shown exactly as measured.
  const a = runAdjust(s, ticks);
  const realCtr = adjusted(k.ctr, a);
  const realRoas = adjusted(roas, a);
  const why = explainFactor(a);

  return (
    <div className="kpirow">
      <div className="panel tile flight">
        <div className="l">SIMULATED FLIGHT</div>
        <div className="v">
          DAY <b>{Math.min(t + 1, ticks)}</b>
          <span className="of">/{ticks}</span>
        </div>
        <div className="transport">
          <button onClick={() => (s.playing ? pause() : play())}
            aria-label={s.playing ? "Pause" : "Play"}>
            {s.playing ? "PAUSE" : "PLAY"}
          </button>
          {[1, 2, 4, 8].map((x) => (
            <button key={x} className={s.speed === x ? "on" : ""}
              onClick={() => setSpeed(x)}>×{x}</button>
          ))}
          <input type="range" min={0} max={Math.max(0, ticks - 1)} value={t}
            aria-label="Scrub day" onChange={(e) => seek(Number(e.target.value))} />
        </div>
      </div>

      <Tile label="CUM SPEND" value={fmtMoney(spend)} note={CPM_SOURCE} sub="SIM-SCALE $" />
      <Tile label="REVENUE" value={fmtMoney(revenue)} sub="SIM-SCALE $" />
      <Tile label="ROAS AT REAL CTR" value={fmtRoas(realRoas)}
        tone={realRoas != null ? (realRoas >= 1 ? "good" : "bad") : undefined}
        note={(isAdjusted(a)
          ? `Extra clicks inflate revenue but not per-impression spend, so the blended ${fmtRoas(roas)} carries the same ${a.factor.toFixed(1)}x as the click rate — shown divided back out, with this run's own revenue per click (everything below the click gate is at its calibrated value). `
          : "This is the blended ROAS; the run clicks at a human-scale rate. ")
          + why + " Real-world blended e-commerce ROAS is 1.5–4×. Revenue is simulated; spend is impressions priced at a researched CPM."}
        sub={isAdjusted(a) && roas != null
          ? `BLENDED ${fmtRoas(roas)} ${fmtFactor(a)}`
          : realRoas != null ? (realRoas >= 1 ? "PROFITABLE" : "UNDERWATER") : " "} />
      <Tile label="REAL CTR" value={fmtPct(realCtr)}
        tone={realCtr != null && k.imp > 200 && !inBand(realCtr) ? "warn" : undefined}
        note={why + " Real-world paid-social CTR is 0.5–2%."}
        sub={isAdjusted(a)
          ? `RAW ${fmtPct(k.ctr)} ${fmtFactor(a)} · ${factorSourceLabel(a)}`
          : `${fmtInt(k.clicks)} CLICKS · CALIBRATED GATE`} />
      <Tile label="IMPRESSIONS" value={fmtInt(k.imp)} sub={`${fmtInt(k.buys)} PURCHASES`} />
    </div>
  );
}

function Tile({ label, value, sub, note, tone }: {
  label: string; value: string; sub?: string; note?: string;
  tone?: "good" | "bad" | "warn";
}) {
  return (
    <div className="panel tile" title={note}>
      <div className="l">{label}</div>
      <div className={`v ${tone ?? ""}`}>{value}</div>
      <div className={`d ${tone === "warn" ? "warn" : ""}`}>{sub ?? " "}</div>
    </div>
  );
}

/** CTR BY AD · DAILY, SHARED SCALE — one small chart per ad, all on the same
 * y-axis so the comparison is honest at a glance. */
export function CtrSmallMultiples({ t, creatives, ticks }: {
  t: number; creatives: CreativeInfo[]; ticks: number;
}) {
  const s = useMarket();
  const a = runAdjust(s, ticks);
  const series = creatives.map((c) => ({
    ...c, data: adjustedSeries(ctrSeries(s.results, String(c.id), ticks), a),
  }));
  const vis = series.flatMap((x) => x.data).filter((v): v is number => v != null);
  const hi = Math.max(0.005, ...vis) * 1.12;

  if (!creatives.length) return null;
  return (
    <div className="panel">
      <div className="ph">
        CTR BY AD · DAILY, SHARED SCALE
        {isAdjusted(a) && (
          <span className="phnote" title={`raw daily CTR ${fmtFactor(a)} (${factorSourceLabel(a).toLowerCase()}); ratios between ads are unchanged`}>
            AT REAL CTR · RAW {fmtFactor(a)}
          </span>
        )}
      </div>
      <div className="pc sm">
        {series.map((c) => {
          const seen = c.data.slice(0, t + 1).filter((v): v is number => v != null);
          const last = seen.length ? seen[seen.length - 1] : null;
          return (
            <div className="smcell" key={c.id}>
              <div className="smhead">
                {c.card?.image_url
                  ? <AdThumb card={c.card} size={18} />
                  : <span className="dot" style={{ background: c.color }} />}
                <span className="nm" title={c.headline || c.name}>{c.name}</span>
                <span className="val" style={{ color: c.color }}>{fmtPct(last)}</span>
              </div>
              <LineChart series={[{ data: c.data, color: c.color, fill: true }]}
                upto={t} ticks={ticks} h={78} min={0} max={hi}
                yFmt={(v) => (100 * v).toFixed(1) + "%"}
                aria={`Daily CTR for ${c.name}`} />
            </div>
          );
        })}
      </div>
    </div>
  );
}
