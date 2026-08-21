"use client";

/** The app shell: numbered sidebar sections + a topbar that names the run
 * you are looking at. The sidebar deep-links into the newest run/experiment
 * so "03 MARKET" always goes somewhere real. The landing page at / opts out
 * of the whole thing — see `bare` below. */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { ExperimentSummary, RegistryRow, SocialRunRow } from "@/lib/types";

const BRAND = { name: "ShopSim", domain: "six-state shoppers on HydraDB" };

export default function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const [runs, setRuns] = useState<RegistryRow[]>([]);
  const [experiments, setExperiments] = useState<ExperimentSummary[]>([]);

  /** The landing page is the product's front door, not part of the cockpit:
   * no run to name, no chrome to hang, and it has to open with the engine
   * down. Gating the poller is the load-bearing half — without it / would sit
   * there firing two failing requests every five seconds behind the hero. */
  const bare = path === "/";

  useEffect(() => {
    if (bare) return;
    let alive = true;
    const tick = () => {
      api.runs().then((r) => alive && setRuns(r)).catch(() => {});
      api.experiments().then((r) => alive && setExperiments(r)).catch(() => {});
    };
    tick();
    const id = setInterval(tick, 5000);
    return () => { alive = false; clearInterval(id); };
  }, [bare]);

  // After every hook, before the derived state none of which / needs.
  if (bare) return <>{children}</>;

  /** 03 MARKET must only ever point at a run the cockpit can actually draw.
   * Everything config-derived there (the ad roster, the allocation river, the
   * schedule) comes from GET /runs/{id}/config, which resolves as
   * runs/experiments/<label>/run_config.json — so a run launched outside the
   * orchestrator (an eval scenario, a CLI run) 404s and the page renders an
   * empty cockpit. Picking `running ?? latestRun` off the raw registry is how
   * `make eval`'s f12-fatigue run ended up on screen as if it were the user's:
   * it was simply the newest thing running on the box. Restrict the candidates
   * to runs that belong to an experiment, which is exactly the set that
   * carries a run_config. */
  const renderable = new Set(experiments.flatMap((x) => x.runs.map((r) => r.run_id)));
  const marketRuns = runs.filter((r) => renderable.has(r.run_id));
  const latestRun = marketRuns.length ? marketRuns[marketRuns.length - 1] : null;
  const running = [...marketRuns].reverse().find((r) => r.status === "running");
  const focus = running ?? latestRun;
  /** Anything live at all, experiment or not — the topbar says so, because
   * "the engine is busy with something that is not yours" is the single most
   * useful thing to know when a launch is refused. */
  const anyRunning = [...runs].reverse().find((r) => r.status === "running") ?? null;
  const foreignRun = anyRunning && !renderable.has(anyRunning.run_id) ? anyRunning : null;
  /** the run on screen, if the URL names one — /market/<id> or /runs/<id>/results */
  const pathRun = path.match(/^\/(?:market|runs)\/([^/]+)/)?.[1] ?? null;
  const reportRun = pathRun ?? focus?.run_id ?? null;

  const sections: { n: string; label: string; href: string; match: (p: string) => boolean }[] = [
    { n: "01", label: "Setup", href: "/setup", match: (p) => p.startsWith("/setup") },
    { n: "02", label: "Studio", href: "/studio", match: (p) => p.startsWith("/studio") || p.startsWith("/launch") },
    { n: "03", label: "Market", href: focus ? `/market/${focus.run_id}` : "/studio",
      match: (p) => p.startsWith("/market") },
    // 04 GRAPH is a fixed, committed capture — it does not follow the focused
    // run, so unlike the others this link needs no run id to point at.
    { n: "04", label: "Graph", href: "/graph",
      match: (p) => p.startsWith("/graph") },
    // 05 MIND is the same kind of thing one page over: the pinned shopper's
    // frozen capture (v3.12-draft), independent of whatever is running.
    { n: "05", label: "Mind", href: "/mind",
      match: (p) => p.startsWith("/mind") },
    { n: "06", label: "Learnings", href: reportRun ? `/runs/${reportRun}/results` : "/setup",
      match: (p) => p.startsWith("/experiments") || p.includes("/results") },
  ];

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="sidebrand"><i />SHOPSIM</div>
        <nav className="sidenav">
          {sections.map((s) => (
            <Link key={s.n} href={s.href} className={s.match(path) ? "on" : ""}>
              <span className="n">{s.n}</span>{s.label}
            </Link>
          ))}
        </nav>
      </aside>
      <div>
        <header className="topbar">
          <Link href="/" className="brand">{BRAND.name}<span>·</span>market</Link>
          <span className="dom">{BRAND.domain}</span>
          {focus && <span className="runchip">{focus.run_id}</span>}
          <div className="spacer" />
          {foreignRun && (
            <span className="statuschip busy" title={
              `${foreignRun.run_id} was started outside the dashboard (label `
              + `"${foreignRun.label}"). Launches are serialized, so Studio will `
              + `refuse until it finishes.`}>
              ENGINE BUSY · {foreignRun.label}
            </span>
          )}
          {focus && (
            <span className={`statuschip ${focus.status === "complete" ? "done" : ""}`}>
              {focus.status === "running" ? "RUN LIVE" : focus.status.toUpperCase()}
            </span>
          )}
        </header>
        {children}
      </div>
    </div>
  );
}
