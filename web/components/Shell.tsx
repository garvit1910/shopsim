"use client";

/** The app shell: numbered sidebar sections + a topbar that names the run
 * you are looking at. The sidebar deep-links into the newest run/experiment
 * so "03 MARKET" always goes somewhere real. */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { ExperimentSummary, RegistryRow, SocialRunRow } from "@/lib/types";

const BRAND = { name: "ShopSim", domain: "six-state shoppers on HydraDB" };

export default function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const [runs, setRuns] = useState<RegistryRow[]>([]);
  const [social, setSocial] = useState<SocialRunRow[]>([]);
  const [experiments, setExperiments] = useState<ExperimentSummary[]>([]);

  useEffect(() => {
    let alive = true;
    const tick = () => {
      api.runs().then((r) => alive && setRuns(r)).catch(() => {});
      api.socialRuns().then((r) => alive && setSocial(r)).catch(() => {});
      api.experiments().then((r) => alive && setExperiments(r)).catch(() => {});
    };
    tick();
    const id = setInterval(tick, 5000);
    return () => { alive = false; clearInterval(id); };
  }, []);

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
  /** 04 GRAPH needs a run that actually carries TRUSTS_PERSON edges — a run
   * without the social layer has nothing social to draw. Prefer the newest
   * one that does; fall back to the focus run so the link still goes
   * somewhere real, and let the page explain why it is empty. */
  const latestSocial = social.length ? social[social.length - 1] : null;

  const sections: { n: string; label: string; href: string; match: (p: string) => boolean }[] = [
    { n: "01", label: "Setup", href: "/", match: (p) => p === "/" },
    { n: "02", label: "Studio", href: "/studio", match: (p) => p.startsWith("/studio") || p.startsWith("/launch") },
    { n: "03", label: "Market", href: focus ? `/market/${focus.run_id}` : "/studio",
      match: (p) => p.startsWith("/market") },
    { n: "04", label: "Graph", href: latestSocial ? `/graph/${latestSocial.run_id}`
        : (focus ? `/graph/${focus.run_id}` : "/studio"),
      match: (p) => p.startsWith("/graph") },
    { n: "05", label: "Learnings", href: reportRun ? `/runs/${reportRun}/results` : "/",
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
