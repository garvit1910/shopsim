"use client";

/** STORY mode — the demo toggle. The analyst terminal stays default; this
 * overlay auto-directs the day's top real story (ranked from the actual
 * event stream) with the day's market-event banner. */

import { useMemo } from "react";
import { useMarket } from "@/lib/market";
import { segmentOf } from "@/lib/selectors";
import type { DetectedEvent, ScheduledEvent } from "@/lib/detectors";
import type { EventRecord } from "@/lib/types";
import { fmtUsd, shopperLabel } from "@/lib/format";

const SCORE: Record<string, number> = {
  BOUGHT: 5, NEED_SATISFIED: 4, CARTED: 3.5, EXPERIENCED: 3, NEED_ACTIVATED: 2.5, BOUNCED: 1.5,
};

function headline(rec: EventRecord): { title: string; line: string } {
  switch (rec.type) {
    case "BOUGHT": return { title: "Purchase", line: `bought at ${fmtUsd(rec.price)}` };
    case "NEED_SATISFIED": return { title: "Need closed", line: "an active need ended in a purchase" };
    case "CARTED": return { title: "Carted", line: "moved the product into the cart" };
    case "EXPERIENCED": return rec.sat != null && rec.sat < 0.5
      ? { title: "Rough delivery", line: `satisfaction ${rec.sat.toFixed(2)} — trust takes the hit` }
      : { title: "Delivery landed", line: `satisfaction ${rec.sat?.toFixed(2) ?? "—"} — trust evidence accumulates` };
    case "NEED_ACTIVATED": return { title: "New need", line: `strength ${rec.strength?.toFixed(2) ?? "—"} — the market just got a motivated shopper` };
    default: return { title: rec.type, line: "" };
  }
}

export default function StoryMode({ t, onClose, onInspect, scheduled, detected }: {
  t: number; onClose: () => void; onInspect: (offset: number) => void;
  scheduled: ScheduledEvent[]; detected: DetectedEvent[];
}) {
  const s = useMarket();
  const stories = useMemo(() => {
    const evs = (s.eventsByTick[t] ?? []).filter((e) => SCORE[e.type]);
    return evs.sort((a, b) => (SCORE[b.type] ?? 0) - (SCORE[a.type] ?? 0)).slice(0, 3);
  }, [s.eventsByTick, t]);
  const idx = Math.min(stories.length - 1, Math.floor(s.frac * 3));
  const banner = [...detected, ...scheduled.map((e) => ({ ...e, severity: null as null }))]
    .filter((e) => e.tick === t)[0];

  const story = stories[Math.max(0, idx)];
  const offset = story ? (story.shopper_id ?? 0) % 100_000 : null;

  return (
    <div className="story" role="dialog" aria-label="Story mode">
      <div className="scard">
        <button className="sx" onClick={onClose} aria-label="Close story mode">×</button>
        {banner && (
          <div className="se" style={{ marginBottom: 8, color: "var(--bad)" }}>
            DAY {t + 1} — {banner.label.toUpperCase()}
          </div>
        )}
        {!story ? (
          <>
            <div className="se">DAY {t + 1} · MARKET DESK</div>
            <h2>A quiet tick</h2>
            <div className="ss">{(s.eventsByTick[t] ?? []).length} events landed without a standout state change.</div>
          </>
        ) : (
          <>
            <div className="se">DAY {t + 1} · TOP STORY · {segmentOf(s.population, offset!).replace(/_/g, " ").toUpperCase()}</div>
            <h2>{headline(story).title}: {shopperLabel(offset!)}</h2>
            <div className="ss">shopper {story.shopper_id} — {headline(story).line}</div>
            <div className="scause">
              &ldquo;Every beat here is an events.jsonl record — open the profile for the receipts.&rdquo;
            </div>
            <button className="btn" style={{ marginTop: 14 }} onClick={() => onInspect(offset!)}>
              OPEN FULL PROFILE →
            </button>
          </>
        )}
      </div>
    </div>
  );
}
