"use client";

/** Hand-rolled SVG chart primitives (ported from the approved design mock).
 * Thin marks, recessive grid, last-point emphasis, direct labels. */

export const CREATIVE_COLORS = ["#1baf7a", "#2a78d6", "#eb6834", "#e87ba4", "#c98500", "#4a3aa7"];

export function colorForCreative(index: number): string {
  return CREATIVE_COLORS[index % CREATIVE_COLORS.length];
}

export function Spark({ data, upto, color, w = 96, h = 20, min }: {
  data: (number | null)[]; upto: number; color: string; w?: number; h?: number; min?: number;
}) {
  const vis = data.slice(0, upto + 1).filter((v): v is number => v != null);
  if (!vis.length) return <svg width={w} height={h} aria-hidden />;
  let lo = min ?? Math.min(...vis);
  let hi = Math.max(...vis);
  if (hi - lo < 1e-9) hi = lo + 1;
  const X = (i: number) => 2 + (w - 4) * (i / Math.max(1, data.length - 1));
  const Y = (v: number) => 2 + (h - 4) * (1 - (v - lo) / (hi - lo));
  let d = "";
  let started = false;
  let last: [number, number] | null = null;
  data.forEach((v, i) => {
    if (i > upto || v == null) return;
    d += `${started ? "L" : "M"}${X(i).toFixed(1)} ${Y(v).toFixed(1)}`;
    started = true;
    last = [X(i), Y(v)];
  });
  return (
    <svg width={w} height={h} aria-hidden>
      <path d={d} fill="none" stroke={color} strokeWidth={1.6} strokeLinecap="round" />
      {last && <circle cx={last[0]} cy={last[1]} r={2.4} fill={color} />}
    </svg>
  );
}

export interface LineSeries {
  data: (number | null)[];
  color: string;
  label?: string;
  fill?: boolean;
  dash?: string;
}

export function LineChart({ series, upto, ticks, h = 110, min, max, yFmt, bands, aria }: {
  series: LineSeries[]; upto: number; ticks: number; h?: number;
  min?: number; max?: number; yFmt?: (v: number) => string;
  bands?: [number, number, string][]; aria?: string;
}) {
  const w = 340;
  const p = { t: 8, r: 10, b: 16, l: 38 };
  const iw = w - p.l - p.r, ih = h - p.t - p.b;
  const vis = series.flatMap((s) => s.data.slice(0, upto + 1)).filter((v): v is number => v != null);
  let lo = min ?? (vis.length ? Math.min(...vis) : 0);
  let hi = max ?? (vis.length ? Math.max(...vis) : 1);
  if (hi - lo < 1e-9) hi = lo + 1;
  if (min == null) lo -= (hi - lo) * 0.08;
  if (max == null) hi += (hi - lo) * 0.08;
  const X = (i: number) => p.l + iw * (i / Math.max(1, ticks - 1));
  const Y = (v: number) => p.t + ih * (1 - (v - lo) / (hi - lo));
  const fmt = yFmt ?? ((v: number) => v.toFixed(2));
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width="100%" height={h} role="img" aria-label={aria ?? "chart"}>
      {bands?.map(([a, b, c], i) => (
        <rect key={i} x={X(a)} y={p.t} width={X(Math.min(b, ticks - 1)) - X(a)} height={ih} fill={c} opacity={0.5} />
      ))}
      {[0, 1, 2].map((i) => {
        const y = p.t + (ih * i) / 2;
        const v = hi - ((hi - lo) * i) / 2;
        return (
          <g key={i}>
            <line x1={p.l} x2={w - p.r} y1={y} y2={y} stroke="var(--grid)" />
            <text x={p.l - 5} y={y + 3.5} textAnchor="end" fontSize={9} fill="var(--muted)" fontFamily="var(--mono)">{fmt(v)}</text>
          </g>
        );
      })}
      {[0, Math.floor((ticks - 1) / 2), ticks - 1].map((i) => (
        <text key={i} x={X(i)} y={h - 4} textAnchor="middle" fontSize={9} fill="var(--muted)" fontFamily="var(--mono)">d{i + 1}</text>
      ))}
      {series.map((s, si) => {
        let d = "";
        let started = false;
        let last: [number, number] | null = null;
        let first: [number, number] | null = null;
        s.data.forEach((v, i) => {
          if (i > upto || v == null) return;
          d += `${started ? "L" : "M"}${X(i).toFixed(1)} ${Y(v).toFixed(1)}`;
          if (!started) first = [X(i), Y(v)];
          started = true;
          last = [X(i), Y(v)];
        });
        if (!started || !last || !first) return null;
        const lastPt = last as [number, number];
        const firstPt = first as [number, number];
        return (
          <g key={si}>
            {s.fill && (
              <path d={`${d} L ${lastPt[0]} ${p.t + ih} L ${firstPt[0]} ${p.t + ih} Z`} fill={s.color} opacity={0.08} />
            )}
            <path d={d} fill="none" stroke={s.color} strokeWidth={2}
              strokeLinejoin="round" strokeLinecap="round"
              strokeDasharray={s.dash} />
            <circle cx={lastPt[0]} cy={lastPt[1]} r={3} fill={s.color} />
            {s.label && (
              <text x={Math.min(lastPt[0] + 5, w - 4)} y={lastPt[1] - 5} fontSize={9.5} fontWeight={700}
                fill={s.color} fontFamily="var(--mono)"
                textAnchor={lastPt[0] > w - 56 ? "end" : "start"}>{s.label}</text>
            )}
          </g>
        );
      })}
    </svg>
  );
}
