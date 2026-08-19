"use client";

/** MASTER TIMELINE — faithful port of the D5 mock's timeline band: day
 * ticks, promo/wave spans from real config, scheduled ▼ and detected ●
 * markers, a playhead that glides with the clock's frac, click to scrub. */

import { useEffect, useRef, useState } from "react";
import { seek, useMarket } from "@/lib/market";
import type { DetectedEvent, ScheduledEvent } from "@/lib/detectors";

const SEV_COLOR: Record<string, string> = { warning: "var(--gold)", serious: "var(--bad)", info: "var(--good)" };

function spans(scheduled: ScheduledEvent[], kind: "promo" | "wave"): [number, number][] {
  const out: [number, number][] = [];
  for (const ev of scheduled) {
    if (ev.kind !== kind || ev.label.includes("ends")) continue;
    const m = ev.detail.match(/days (\d+)–(\d+)/);
    if (m) out.push([Number(m[1]) - 1, Number(m[2]) - 1]);
  }
  return out;
}

export default function MasterTimeline({ scheduled, detected }: {
  scheduled: ScheduledEvent[]; detected: DetectedEvent[];
}) {
  const s = useMarket();
  const ref = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(1200);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setW(el.clientWidth || 1200));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const ticks = s.manifest?.ticks ?? Math.max(1, s.headTick + 1);
  const t = Math.max(0, Math.min(s.tick, Math.max(0, s.headTick)));
  const h = 56, x0 = 14, x1 = w - 14;
  const X = (d: number) => x0 + ((x1 - x0) * d) / Math.max(1, ticks - 1);
  const px = s.playing && t < ticks - 1 ? X(t) + (X(t + 1) - X(t)) * s.frac : X(t);

  const onScrub = (e: React.MouseEvent) => {
    const r = ref.current!.getBoundingClientRect();
    const f = (e.clientX - r.left - 14) / (r.width - 28);
    seek(Math.round(f * (ticks - 1)));
  };

  return (
    <div className="panel tlpanel" role="slider" aria-label="Simulation timeline" tabIndex={0}>
      <div className="tlcap">
        <span>MASTER TIMELINE — CLICK TO SCRUB · ▮ PROMO · ▨ NEED WAVE · ● DETECTED · ▼ SCHEDULED</span>
        <span className="num" style={{ color: "var(--ink)" }}>
          DAY {t + 1} / {ticks}{s.status === "complete" && t >= ticks - 1 && !s.playing ? " · RUN COMPLETE" : ""}
        </span>
      </div>
      <div ref={ref} onClick={onScrub} style={{ cursor: "pointer" }}>
        <svg viewBox={`0 0 ${w} ${h}`} width="100%" height={h}>
          <line x1={x0} x2={x1} y1={34} y2={34} stroke="var(--line)" strokeWidth={1.5} />
          {spans(scheduled, "promo").map(([a, b], i) => (
            <rect key={`p${i}`} x={X(a) - 6} y={24} width={X(Math.min(b, ticks - 1)) - X(a) + 12} height={20} fill="var(--tint-warn)" rx={3} />
          ))}
          {spans(scheduled, "wave").map(([a, b], i) => (
            <rect key={`w${i}`} x={X(a) - 6} y={24} width={X(Math.min(b, ticks - 1)) - X(a) + 12} height={20} fill="var(--tint-good)" rx={3} opacity={0.8} />
          ))}
          {Array.from({ length: ticks }, (_, d) => (
            <g key={d}>
              <line x1={X(d)} x2={X(d)} y1={30} y2={38}
                stroke={d <= t ? "var(--info)" : "var(--line)"} strokeWidth={d <= t ? 2 : 1} />
              <text x={X(d)} y={52} fontSize={9} textAnchor="middle" fontFamily="var(--mono)"
                fill={d === t ? "var(--ink)" : "var(--muted)"} fontWeight={d === t ? 700 : 400}>{d + 1}</text>
            </g>
          ))}
          {scheduled.map((ev, i) => (
            <path key={`s${i}`} d={`M ${X(ev.tick) - 4} 14 L ${X(ev.tick) + 4} 14 L ${X(ev.tick)} 21 Z`} fill="var(--info)">
              <title>d{ev.tick + 1} · {ev.label} — {ev.detail}</title>
            </path>
          ))}
          {detected.map((ev, i) => (
            <circle key={`d${i}`} cx={X(ev.tick)} cy={8} r={4} fill={ev.tick <= t ? SEV_COLOR[ev.severity] : "var(--line)"}>
              <title>d{ev.tick + 1} · {ev.label} — rule: {ev.rule}</title>
            </circle>
          ))}
          <line x1={px} x2={px} y1={4} y2={46} stroke="var(--ink)" strokeWidth={1.5} />
          <circle cx={px} cy={4} r={3} fill="var(--ink)" />
        </svg>
      </div>
    </div>
  );
}
