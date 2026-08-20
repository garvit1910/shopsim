"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { ExperimentSummary, RegistryRow } from "@/lib/types";

export default function MarketFloorPage() {
  const [runs, setRuns] = useState<RegistryRow[] | null>(null);
  const [experiments, setExperiments] = useState<ExperimentSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let dead = false;
    const load = async () => {
      try {
        const [r, e] = await Promise.all([api.runs(), api.experiments()]);
        if (!dead) { setRuns(r.slice().reverse()); setExperiments(e.slice().reverse()); setError(null); }
      } catch (ex) {
        if (!dead) setError(ex instanceof Error ? ex.message : String(ex));
      }
    };
    load();
    const t = setInterval(load, 4000);
    return () => { dead = true; clearInterval(t); };
  }, []);

  return (
    <main className="wrap">
      <div className="runhead">
        <h1 style={{ fontSize: 22 }}>Market floor</h1>
        <Link className="btn primary" href="/launch">LAUNCH EXPERIMENT →</Link>
      </div>
      {error && (
        <div className="errbox" style={{ marginBottom: 12 }}>
          Engine API unreachable ({error}). Start it with{" "}
          <code>python -m shopsim.runner serve --config fixtures/run-configs/scripted-run-1.json</code>.
        </div>
      )}
      <div className="indexgrid">
        <section className="panel">
          <div className="ph">EXPERIMENTS</div>
          <div>
            {experiments?.length === 0 && <div className="note">No experiments yet — launch one.</div>}
            {experiments?.map((e) => {
              const running = e.runs.find((r) => r.status === "running");
              return (
                <Link key={e.name} className="rowlink" href={`/experiments/${encodeURIComponent(e.name)}`}>
                  <div className="t">
                    {e.name}
                    {running
                      ? <span className="chip running">RUNNING · {running.arm}</span>
                      : e.has_comparison
                        ? <span className="chip">COMPLETE</span>
                        : <span className="chip">{e.runs.length ? "PARTIAL" : "CREATED"}</span>}
                  </div>
                  <div className="m">{e.spec_type ?? "experiment"} · {e.arms.length} arm{e.arms.length === 1 ? "" : "s"} · {e.runs.length} run{e.runs.length === 1 ? "" : "s"}</div>
                </Link>
              );
            })}
          </div>
        </section>
        <section className="panel">
          <div className="ph">RUNS · NEWEST FIRST</div>
          <div>
            {runs?.length === 0 && <div className="note">No runs registered.</div>}
            {runs?.map((r) => (
              <Link key={r.run_id} className="rowlink" href={`/market/${r.run_id}`}>
                <div className="t">
                  {r.run_id}
                  <span className={`chip ${r.status === "running" ? "running" : ""}`}>{r.status.toUpperCase()}</span>
                </div>
                <div className="m">{r.label} · arm {r.arm} · seed {r.seed} · block {r.run_index}</div>
              </Link>
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}
