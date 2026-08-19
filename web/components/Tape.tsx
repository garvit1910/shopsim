"use client";

/** THE TAPE — time-and-sales for the market. Every line is a real event from
 * events.jsonl; alerts are the scheduled/detected market events for the
 * visible days. CARTED/BOUGHT lines are enriched with the shopper's real
 * cause-stamped preference delta (≤8 history fetches per tick, cached). */

import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useMarket } from "@/lib/market";
import { segmentOf } from "@/lib/selectors";
import type { DetectedEvent, ScheduledEvent } from "@/lib/detectors";
import type { EventRecord, PrefVersion } from "@/lib/types";
import { fmtUsd, shopperLabel } from "@/lib/format";
import { conceptName } from "./panels";

const SHOW = new Set(["CLICKED", "CARTED", "BOUGHT", "BOUNCED", "EXPERIENCED",
  "NEED_ACTIVATED", "NEED_SATISFIED", "NEED_EXPIRED"]);

interface Enriched { concept: number; before: number; after: number; cause: string }
const histCache = new Map<string, Enriched | null>();

export default function Tape({ t, driftConcept, onInspect, scheduled, detected }: {
  t: number;
  driftConcept: number | null;
  onInspect: (offset: number) => void;
  scheduled: ScheduledEvent[];
  detected: DetectedEvent[];
}) {
  const s = useMarket();
  const [, bump] = useState(0);

  const lines = useMemo(() => {
    // strictly ≤ the viewing day — the chase clock owns pacing (D5 behavior)
    const out: { day: number; rec: EventRecord }[] = [];
    for (let d = t; d >= Math.max(0, t - 2); d--) {
      for (const rec of [...(s.eventsByTick[d] ?? [])].reverse())
        if (SHOW.has(rec.type)) out.push({ day: d, rec });
    }
    return out.slice(0, 44);
  }, [s.eventsByTick, t]);

  // enrich purchases/carts with the real preference receipt (bounded)
  useEffect(() => {
    if (!s.runId || driftConcept == null) return;
    let budget = 8;
    const jobs: Promise<unknown>[] = [];
    for (const { rec } of lines) {
      if (budget <= 0) break;
      if (rec.type !== "BOUGHT" && rec.type !== "CARTED") continue;
      const offset = (rec.shopper_id ?? 0) % 100_000;
      const key = `${s.runId}:${offset}:${driftConcept}`;
      if (histCache.has(key)) continue;
      budget -= 1;
      histCache.set(key, null);
      jobs.push(
        api.preferenceHistory(s.runId, offset, driftConcept).then((chain: PrefVersion[]) => {
          if (chain.length >= 2) {
            const last = chain[chain.length - 1], prev = chain[chain.length - 2];
            histCache.set(key, {
              concept: driftConcept, before: prev.w, after: last.w,
              cause: `${last.cause_kind} ${last.cause_id || ""}`.trim(),
            });
          }
        }).catch(() => histCache.delete(key)),
      );
    }
    if (jobs.length) Promise.all(jobs).then(() => bump((n) => n + 1));
  }, [lines, s.runId, driftConcept]);

  const alerts = [
    ...detected.filter((e) => e.tick <= t && e.tick >= t - 2),
    ...scheduled.filter((e) => e.tick <= t && e.tick >= t - 2).map((e) => ({ ...e, severity: "sched" as const, rule: null })),
  ].sort((a, b) => b.tick - a.tick);

  const describe = (rec: EventRecord): { text: string; cls: string } => {
    switch (rec.type) {
      case "BOUGHT": return { text: `● BOUGHT ${fmtUsd(rec.price)}`, cls: "up" };
      case "CARTED": return { text: "▲ carted", cls: "up" };
      case "CLICKED": return { text: "clicked", cls: "" };
      case "BOUNCED": return { text: "▼ bounced", cls: "dn" };
      case "EXPERIENCED":
        return rec.sat != null && rec.sat < 0.5
          ? { text: `▼ rough delivery (sat ${rec.sat.toFixed(2)})`, cls: "dn" }
          : { text: `▲ delivery landed (sat ${rec.sat?.toFixed(2) ?? "—"})`, cls: "up" };
      case "NEED_ACTIVATED": return { text: `needs · strength ${rec.strength?.toFixed(2) ?? "—"}`, cls: "up" };
      case "NEED_SATISFIED": return { text: "need closed by purchase", cls: "up" };
      case "NEED_EXPIRED": return { text: "need expired unmet", cls: "dn" };
      default: return { text: rec.type.toLowerCase(), cls: "" };
    }
  };

  let lastDay: number | null = null;
  return (
    <div className="panel" style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
      <div className="ph">THE TAPE · EVERY LINE IS A REAL EVENT</div>
      <div className="tape" style={{ maxHeight: 520 }}>
        {alerts.map((a, i) => (
          <span key={`a${i}`} className={`alert ${"severity" in a ? a.severity : ""}`}>
            <span className="ah">DAY {a.tick + 1} · {a.severity === "sched" ? "SCHEDULED" : "DETECTED"}</span>
            <span className="an">{a.label}</span>
            <span className="ad">{a.detail}</span>
            {"rule" in a && a.rule && <span className="rule">rule: {a.rule}</span>}
          </span>
        ))}
        {lines.map(({ day, rec }, i) => {
          const offset = (rec.shopper_id ?? 0) % 100_000;
          const { text, cls } = describe(rec);
          const sep = lastDay != null && day !== lastDay;
          lastDay = day;
          const key = `${s.runId}:${offset}:${driftConcept}`;
          const enriched = (rec.type === "BOUGHT" || rec.type === "CARTED") ? histCache.get(key) : null;
          return (
            <span key={i} style={{ display: "block" }}>
              {sep && <span className="line sep">── day {day + 1} ──</span>}
              <button className="line" onClick={() => onInspect(offset)}>
                <span className="d">d{day + 1}</span>
                <span className="who">{shopperLabel(offset).toUpperCase()}</span>{" "}
                <span className={cls}>{text}</span>
                {enriched && (
                  <span style={{ color: "var(--muted)" }}>
                    {" · "}{conceptName(enriched.concept)} {enriched.before.toFixed(3)}→{enriched.after.toFixed(3)}
                    <span className={enriched.after >= enriched.before ? "up" : "dn"}>
                      {enriched.after >= enriched.before ? " ▲" : " ▼"}
                    </span>
                  </span>
                )}
                <span style={{ color: "var(--muted)" }}> · {segmentOf(s.population, offset)}</span>
              </button>
            </span>
          );
        })}
        {lines.length === 0 && <span className="line sep">quiet tape — waiting for events…</span>}
      </div>
    </div>
  );
}
