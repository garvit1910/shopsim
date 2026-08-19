"use client";

/** What the engine is doing before day 1 exists.
 *
 * The registry publishes a run the moment its directory is made, but the
 * manifest only lands at the end of prepare() — population generation and
 * graph seeding, which can take tens of seconds. That gap used to render as a
 * red "manifest.json not found", which reads as a crash when nothing is
 * wrong. This names the phase and counts down instead.
 *
 * The countdown is deliberately honest about being an estimate: if it reaches
 * zero while the engine is still working it does not freeze at 0:00 or claim
 * failure — it adds a further two minutes and says it did.
 */

import { useEffect, useRef, useState } from "react";
import { useMarket } from "@/lib/market";
import { OVERRUN_EXTENSION_S, estimate, fmtDuration } from "@/lib/eta";

const PHASES: [string, string][] = [
  ["population", "generating shoppers"],
  ["perception", "reading the ads"],
  ["catalog", "loading the catalog"],
  ["stimuli", "writing ads to the graph"],
  ["seed_population", "seeding shopper memory"],
  ["manifest", "sealing the manifest"],
];

/** A countdown that survives being wrong: it re-estimates as real timing
 * arrives, and rolls forward rather than stalling at zero. */
export function useCountdown(remainingS: number | null, done: boolean) {
  const [now, setNow] = useState(() => Date.now());
  const deadline = useRef<number | null>(null);
  const [extensions, setExtensions] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    if (done || remainingS == null) return;
    const proposed = Date.now() + remainingS * 1000;
    const cur = deadline.current;
    // only move the target on a meaningful change, so the number does not
    // jitter down-then-up every poll
    if (cur == null || proposed > cur || Math.abs(proposed - cur) > 0.1 * (cur - Date.now())) {
      deadline.current = proposed;
    }
  }, [remainingS, done]);

  useEffect(() => {
    if (done || deadline.current == null) return;
    if (now >= deadline.current) {
      deadline.current = now + OVERRUN_EXTENSION_S * 1000;
      setExtensions((n) => n + 1);
    }
  }, [now, done]);

  if (done || deadline.current == null) return { left: null, extensions };
  return { left: Math.max(0, (deadline.current - now) / 1000), extensions };
}

export default function EnginePreflight() {
  const s = useMarket();
  const prog = s.bootProgress;
  const population = prog?.population_size
    ?? s.config?.effective.population_size ?? 0;
  const ticks = prog?.ticks ?? s.config?.effective.ticks ?? 0;

  const eta = estimate({ pace: s.pace, population, ticks, progress: prog });
  const { left, extensions } = useCountdown(eta.remainingS, false);

  const active = prog?.phase ?? "population";
  const activeIdx = Math.max(0, PHASES.findIndex(([k]) => k === active));

  return (
    <div className="panel preflight">
      <div className="ph">
        STARTING ENGINE
        <span className="phnote">
          the run exists; day 1 appears once the graph is seeded
        </span>
      </div>
      <div className="pc">
        <div className="pfclock">
          <div className="pfbig">{fmtDuration(left)}</div>
          <div className="pfsub">
            {extensions > 0
              ? `still working — added ${OVERRUN_EXTENSION_S / 60}:00 to the estimate (×${extensions})`
              : eta.measured
                ? `estimated · ~${eta.perTickS?.toFixed(1)}s per simulated day`
                : `estimated from recent runs on this machine · ${population} shoppers × ${ticks} days`}
          </div>
        </div>
        <ol className="pfphases">
          {PHASES.map(([key, label], i) => (
            <li key={key} className={i < activeIdx ? "done" : i === activeIdx ? "on" : ""}>
              <i />{label}
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}

/** The same countdown, inline, for a run that is already ticking. */
export function EtaChip() {
  const s = useMarket();
  const prog = s.bootProgress;
  const done = s.status === "complete";
  const population = prog?.population_size ?? s.config?.effective.population_size ?? 0;
  const ticks = prog?.ticks ?? s.manifest?.ticks ?? 0;
  const eta = estimate({ pace: s.pace, population, ticks, progress: prog });
  const { left, extensions } = useCountdown(eta.remainingS, done);

  if (done) return <span className="etachip done">RUN COMPLETE</span>;
  if (left == null) return null;
  return (
    <span className="etachip" title={eta.measured
      ? `measured at about ${eta.perTickS?.toFixed(1)}s per simulated day on this machine`
      : "estimated from recent runs on this machine"}>
      ETA {fmtDuration(left)}
      {extensions > 0 && <em> +{OVERRUN_EXTENSION_S / 60}:00</em>}
    </span>
  );
}
