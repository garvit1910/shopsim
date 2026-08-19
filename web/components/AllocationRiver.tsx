"use client";

/** ALLOCATION RIVER — impressions per ad per day, stacked and centered.
 *
 * Every band's thickness is a real SAW count for that ad on that day. When
 * adaptive allocation is on, the engine reweights each ad's daily reach by
 * its trailing CTR, so the river visibly narrows toward the winners: the
 * chart is not a stylization of the market, it IS the market's budget.
 *
 * Reveal is driven by the MarketClock (t + frac), the same draw-in idiom the
 * rest of the terminal uses — nothing animates that isn't a real value.
 */

import { useRef, useState } from "react";

export interface RiverSeries {
  id: string;
  name: string;
  color: string;
  /** impressions on each simulated day; index === tick */
  perDay: number[];
  imageUrl?: string;
}

const W = 1000;
const PAD = { t: 14, r: 14, b: 26, l: 46 };

/** Midpoint-quadratic smoothing — flowing bands without overshoot. */
function smooth(pts: [number, number][]): string {
  if (!pts.length) return "";
  if (pts.length < 3) return pts.map((p, i) => `${i ? "L" : "M"}${p[0]} ${p[1]}`).join("");
  let d = `M${pts[0][0]} ${pts[0][1]}`;
  for (let i = 1; i < pts.length - 1; i++) {
    const [x, y] = pts[i];
    const [nx, ny] = pts[i + 1];
    d += `Q${x} ${y} ${(x + nx) / 2} ${(y + ny) / 2}`;
  }
  const last = pts[pts.length - 1];
  d += `L${last[0]} ${last[1]}`;
  return d;
}

export default function AllocationRiver({
  series, ticks, t, frac, h = 300, allocated = true,
}: {
  series: RiverSeries[];
  ticks: number;
  t: number;
  frac: number;
  h?: number;
  allocated?: boolean;
}) {
  const ref = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<number | null>(null);

  const iw = W - PAD.l - PAD.r;
  const ih = h - PAD.t - PAD.b;

  // available days = the longest series we actually have data for
  const have = Math.max(0, ...series.map((s) => s.perDay.length));
  const dayTotals = Array.from({ length: have }, (_, i) =>
    series.reduce((sum, s) => sum + (s.perDay[i] ?? 0), 0));
  const peak = Math.max(1, ...dayTotals);

  // reveal edge: whole days to t, plus the in-flight fraction of the next
  const edge = Math.min(have - 1 + 1e-9, t + (t + 1 < have ? frac : 0));
  const X = (day: number) => PAD.l + iw * (day / Math.max(1, ticks - 1));
  const Yc = PAD.t + ih / 2;
  const scale = (v: number) => (v / peak) * ih;

  /** value of a series on a fractional day (linear between whole days) */
  const at = (s: RiverSeries, day: number) => {
    const lo = Math.floor(day);
    const hi = Math.min(have - 1, lo + 1);
    const f = day - lo;
    return (s.perDay[lo] ?? 0) * (1 - f) + (s.perDay[hi] ?? 0) * f;
  };

  const days: number[] = [];
  for (let i = 0; i <= Math.floor(edge); i++) days.push(i);
  if (edge > days[days.length - 1]) days.push(edge);

  // stack bottom-up, centered on Yc
  const bands = series.map(() => ({ top: [] as [number, number][], bot: [] as [number, number][] }));
  for (const day of days) {
    const total = series.reduce((sum, s) => sum + at(s, day), 0);
    let cum = -total / 2;
    series.forEach((s, si) => {
      const v = at(s, day);
      const x = X(day);
      bands[si].bot.push([x, Yc + scale(cum)]);
      cum += v;
      bands[si].top.push([x, Yc + scale(cum)]);
    });
  }

  const hoverDay = hover != null ? Math.max(0, Math.min(Math.floor(edge), hover)) : null;
  const hoverTotal = hoverDay != null ? (dayTotals[hoverDay] ?? 0) : 0;

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = ref.current?.getBoundingClientRect();
    if (!rect) return;
    const px = ((e.clientX - rect.left) / rect.width) * W;
    const day = Math.round(((px - PAD.l) / iw) * Math.max(1, ticks - 1));
    setHover(day >= 0 && day <= Math.floor(edge) ? day : null);
  };

  const gridDays = ticks <= 14
    ? Array.from({ length: ticks }, (_, i) => i)
    : [0, Math.floor((ticks - 1) / 4), Math.floor((ticks - 1) / 2),
       Math.floor((3 * (ticks - 1)) / 4), ticks - 1];

  return (
    <div className="river">
      <svg ref={ref} viewBox={`0 0 ${W} ${h}`} width="100%" height={h}
        role="img" preserveAspectRatio="xMidYMid meet"
        aria-label={`Impressions per ad per day across ${ticks} simulated days`}
        onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
        {/* y guides: peak/day at the extremes of the centered stack */}
        {[0.5, 0, -0.5].map((f, i) => (
          <g key={i}>
            <line x1={PAD.l} x2={W - PAD.r} y1={Yc + f * ih} y2={Yc + f * ih}
              stroke="var(--grid)" strokeDasharray={i === 1 ? undefined : "2 3"} />
            <text x={PAD.l - 6} y={Yc + f * ih + 3.5} textAnchor="end" fontSize={10}
              fill="var(--muted)" fontFamily="var(--mono)">
              {/* the stack is centred, so the extremes are +/- half the peak day */}
              {i === 1 ? "0" : `${i === 2 ? "" : "-"}${Math.round(peak / 2).toLocaleString()}`}
            </text>
          </g>
        ))}
        {gridDays.map((i) => (
          <text key={i} x={X(i)} y={h - 7} textAnchor="middle" fontSize={10}
            fill="var(--muted)" fontFamily="var(--mono)">{i + 1}</text>
        ))}

        {bands.map((b, si) => (
          <path key={series[si].id}
            d={`${smooth(b.top)}L${smooth([...b.bot].reverse()).slice(1)}Z`}
            fill={series[si].color} opacity={0.86}>
            <title>{series[si].name}</title>
          </path>
        ))}

        {/* the live edge */}
        {edge > 0 && (
          <line x1={X(edge)} x2={X(edge)} y1={PAD.t} y2={PAD.t + ih}
            stroke="var(--ink)" strokeWidth={1} opacity={0.35} />
        )}
        {hoverDay != null && (
          <line x1={X(hoverDay)} x2={X(hoverDay)} y1={PAD.t} y2={PAD.t + ih}
            stroke="var(--ink)" strokeWidth={1} opacity={0.55} />
        )}
      </svg>

      <div className="riverlegend">
        {series.map((s) => {
          const dayV = hoverDay != null ? (s.perDay[hoverDay] ?? 0) : (s.perDay[Math.floor(edge)] ?? 0);
          const dayT = hoverDay != null ? hoverTotal : (dayTotals[Math.floor(edge)] ?? 0);
          const share = dayT > 0 ? (dayV / dayT) * 100 : 0;
          return (
            <span className="rchip" key={s.id} title={`${s.name} · ${dayV.toLocaleString()} impressions`}>
              <i style={{ background: s.color }} />
              {s.imageUrl && <img src={s.imageUrl} alt="" />}
              <b>{s.name}</b>
              <em>{share.toFixed(0)}%</em>
            </span>
          );
        })}
        <span className="rnote">
          {hoverDay != null
            ? `DAY ${hoverDay + 1} · ${hoverTotal.toLocaleString()} IMPRESSIONS`
            : allocated
              ? "BUDGET REALLOCATES DAILY BY TRAILING CTR"
              : "FIXED REACH PER AD"}
        </span>
      </div>
    </div>
  );
}
