"use client";

/** The Market page's own furniture: the six-tile KPI row (with the flight
 * transport built into the first tile) and the CTR-by-ad small multiples.
 *
 * Money tiles: revenue is simulated (BOUGHT.price), spend is impressions
 * priced at a researched CPM — see lib/economics.ts. */

import { pause, play, seek, setSpeed, useMarket } from "@/lib/market";
import { derive, kpisAt, ctrSeries, revenueAt } from "@/lib/selectors";
import { CPM_SOURCE, fmtMoney, fmtRoas, roasFor, spendFor } from "@/lib/economics";
import { fmtInt, fmtPct } from "@/lib/format";
import type { CreativeInfo } from "./panels";
import { AdThumb } from "./AdCard";
import { LineChart } from "./charts";

/** Mid-point of the researched real-world CTR band (0.5-2%), used only to
 * tell the viewer how far an accelerated run sits from reality. */
const REAL_CTR_REFERENCE = 0.0125;
/** The calibrated CLICK threshold (minds/calibration.py DEFAULT_STAGE_BASES).
 * A run that lowers it has deliberately made clicking easier; a run that does
 * not, but still clicks above band, is simply a differently-calibrated run.
 * Calling both "ACCELERATED" put a demo-only word on eval runs that never
 * asked for one. */
const CALIBRATED_CLICK_BASE = 6.0;

export function FlightKpis({ t, ticks }: { t: number; ticks: number }) {
  const s = useMarket();
  const d = derive(s.eventsByTick);
  const k = kpisAt(d, s.results, t);
  const revenue = revenueAt(s.eventsByTick, t);
  const spend = spendFor(k.imp);
  const roas = roasFor(revenue, spend);
  // computed from this run's own measured CTR, so the disclosure can never
  // drift from what the run actually did
  const ctrMultiple = k.ctr && k.imp > 200 ? k.ctr / REAL_CTR_REFERENCE : null;
  // Did this run actually ask to be accelerated? Only then is that the word.
  const clickBase = (s.config?.raw as { calibration?: { stage_bases?: { CLICK?: number } } } | undefined)
    ?.calibration?.stage_bases?.CLICK;
  const accelerated = typeof clickBase === "number" && clickBase < CALIBRATED_CLICK_BASE;
  const overBandLabel = accelerated ? "ACCELERATED" : "ABOVE BAND";

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
      <Tile label="BLENDED ROAS" value={fmtRoas(roas)}
        tone={ctrMultiple != null && ctrMultiple > 2 ? "warn"
          : roas != null && roas >= 1 ? "good" : roas != null ? "bad" : undefined}
        note={ctrMultiple != null && ctrMultiple > 2 && roas != null
          ? `Clicks above band inflate revenue but not per-impression spend, so ROAS carries the same ~${ctrMultiple.toFixed(0)}x. At real-world click rates this run would be nearer ${fmtRoas(roas / ctrMultiple)}.`
          : "revenue is simulated; spend is impressions priced at a researched CPM"}
        sub={ctrMultiple != null && ctrMultiple > 2 && roas != null
          ? `~${fmtRoas(roas / ctrMultiple)} AT REAL CTR`
          : roas != null ? (roas >= 1 ? "PROFITABLE" : "UNDERWATER") : " "} />
      <Tile label="BLENDED CTR" value={fmtPct(k.ctr)}
        tone={ctrMultiple != null && ctrMultiple > 2 ? "warn" : undefined}
        note={ctrMultiple != null
          ? `real-world paid-social CTR is 0.5-2%; this run is running about ${ctrMultiple.toFixed(0)}x that`
            + (accelerated
                ? ` — deliberately, this run lowers the CLICK threshold to ${clickBase}`
                : " — this run does not lower the CLICK threshold, so that is its own calibration")
          : undefined}
        sub={ctrMultiple != null && ctrMultiple > 2
          ? `${overBandLabel} ~${ctrMultiple.toFixed(0)}x`
          : `${fmtInt(k.clicks)} CLICKS`} />
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
  const series = creatives.map((c) => ({
    ...c, data: ctrSeries(s.results, String(c.id), ticks),
  }));
  const vis = series.flatMap((x) => x.data).filter((v): v is number => v != null);
  const hi = Math.max(0.005, ...vis) * 1.12;

  if (!creatives.length) return null;
  return (
    <div className="panel">
      <div className="ph">CTR BY AD · DAILY, SHARED SCALE</div>
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
