"use client";

/** The app shell: numbered sidebar sections + a topbar that names the run
 * you are looking at. The sidebar deep-links into the newest run/experiment
 * so "03 MARKET" always goes somewhere real. */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { RegistryRow } from "@/lib/types";

const BRAND = { name: "ShopSim", domain: "six-state shoppers on HydraDB" };

export default function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const [runs, setRuns] = useState<RegistryRow[]>([]);

  useEffect(() => {
    let alive = true;
    const tick = () => {
      api.runs().then((r) => alive && setRuns(r)).catch(() => {});
    };
    tick();
    const id = setInterval(tick, 5000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  const latestRun = runs.length ? runs[runs.length - 1] : null;
  const running = [...runs].reverse().find((r) => r.status === "running");
  const focus = running ?? latestRun;
  /** the run on screen, if the URL names one — /market/<id> or /runs/<id>/results */
  const pathRun = path.match(/^\/(?:market|runs)\/([^/]+)/)?.[1] ?? null;
  const reportRun = pathRun ?? focus?.run_id ?? null;

  const sections: { n: string; label: string; href: string; match: (p: string) => boolean }[] = [
    { n: "01", label: "Setup", href: "/", match: (p) => p === "/" },
    { n: "02", label: "Studio", href: "/studio", match: (p) => p.startsWith("/studio") || p.startsWith("/launch") },
    { n: "03", label: "Market", href: focus ? `/market/${focus.run_id}` : "/studio",
      match: (p) => p.startsWith("/market") },
    { n: "04", label: "Shoppers", href: focus ? `/market/${focus.run_id}#shoppers` : "/studio",
      match: () => false },
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
