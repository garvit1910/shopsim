"use client";

/** Experiment overview (5.6): arm runs with live progress, the cross-arm
 * comparison.json when all arms finish, orchestrator health. Arms run
 * sequentially and share the seed — paired populations by construction. */

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { ExperimentDetail } from "@/lib/types";
import { fmtPct } from "@/lib/format";

interface CreativeRow {
  arm: string; creative: number; ctr: number | null;
  SAW?: number; CLICKED?: number; BROWSED?: number; CARTED?: number; BOUGHT?: number;
  [k: string]: unknown;
}

interface RungCreative {
  creative: number; SAW: number; CLICKED: number; BOUGHT: number;
  ctr: number | null; revenue: number;
}

interface LadderRung {
  level: number; arm: string;
  revenue_total: number | null;
  bought_total: number | null;
  reference_price_drift: number | null;
  creatives?: RungCreative[];
  vs_control?: {
    control_arm: string;
    revenue_delta: number | null;
    revenue_lift_pct: number | null;
    bought_delta: number | null;
    by_creative: Record<string, {
      ctr_delta: number | null; revenue_delta: number; bought_delta: number }>;
  };
}

interface PricingSection {
  arms?: Record<string, Record<string, unknown>>;
  ladder?: LadderRung[];
  control_level?: number | null;
  best_level?: number | null;
  best_arm?: string | null;
}

/** How much reference-price erosion counts as "you taught them a lower
 * price" — the same threshold the market page's detector uses. */
const EROSION_USD = -0.5;

function PricingVerdict({ pricing, creativeName }: {
  pricing: PricingSection; creativeName?: Record<string, string>;
}) {
  const rungs = pricing.ladder ?? [];
  const best = pricing.best_level;
  const control = rungs.find((r) => r.level === 0);
  // one row per ad, one column per depth — "how did each ad react"
  const adIds = [...new Set(rungs.flatMap((r) => (r.creatives ?? []).map((c) => c.creative)))];
  const peak = Math.max(1, ...rungs.map((r) => r.revenue_total ?? 0));
  const winner = rungs.find((r) => r.level === best);
  const eroding = rungs.filter(
    (r) => r.reference_price_drift != null && r.reference_price_drift < EROSION_USD);

  return (
    <div className="panel" style={{ marginBottom: 12 }}>
      <div className="ph">
        PRICE SENSITIVITY · REVENUE BY DISCOUNT DEPTH
        <span className="phnote">one arm per depth · same seeded population</span>
      </div>
      <div className="ladder">
        {rungs.map((r) => (
          <div className={`lrow ${r.level === best ? "win" : ""}`} key={r.arm}>
            <span className="ll">{Math.round(r.level * 100)}% off</span>
            <span className="lt">
              <i style={{ width: `${(100 * (r.revenue_total ?? 0)) / peak}%` }} />
            </span>
            <span className="lv">
              {r.revenue_total == null ? "—" : `$${r.revenue_total.toFixed(2)}`}
            </span>
            <span className="lv" style={{ color: "var(--muted)" }}>
              {r.bought_total ?? "—"} buys
            </span>
          </div>
        ))}
      </div>
      {adIds.length > 0 && (
        <div className="pc" style={{ overflowX: "auto" }}>
          <div className="ph" style={{ padding: "6px 0" }}>
            HOW EACH AD REACTED · REVENUE, AND THE CHANGE VS THE FULL-PRICE CONTROL
          </div>
          <table className="term">
            <thead><tr>
              <th>Ad</th>
              {rungs.map((r) => (
                <th key={r.arm} style={{ textAlign: "right" }}>
                  {r.level === 0 ? "CONTROL" : `${Math.round(r.level * 100)}% off`}
                </th>
              ))}
            </tr></thead>
            <tbody>
              {adIds.map((cid) => (
                <tr key={cid}>
                  <td className="mono">{creativeName?.[String(cid)] ?? cid}</td>
                  {rungs.map((r) => {
                    const c = (r.creatives ?? []).find((x) => x.creative === cid);
                    const d = r.vs_control?.by_creative?.[String(cid)];
                    const delta = d?.revenue_delta ?? 0;
                    return (
                      <td key={r.arm} className="num" style={{ textAlign: "right" }}>
                        ${(c?.revenue ?? 0).toFixed(0)}
                        {r.level !== 0 && delta !== 0 && (
                          <span style={{ marginLeft: 6, fontSize: 11,
                            color: delta > 0 ? "var(--good)" : "var(--bad)" }}>
                            {delta > 0 ? "+" : ""}{delta.toFixed(0)}
                          </span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="verdict">
        {winner ? (
          <>
            Best depth: <b>{Math.round(winner.level * 100)}% off</b> — ${winner.revenue_total?.toFixed(2)} revenue
            from {winner.bought_total} purchases.{" "}
            {winner.level !== 0 && winner.vs_control?.revenue_lift_pct != null && (
              <>That is {winner.vs_control.revenue_lift_pct > 0 ? "+" : ""}
              {winner.vs_control.revenue_lift_pct.toFixed(0)}% versus the full-price control.</>
            )}
            {control && (
              <div style={{ color: "var(--muted)", marginTop: 8, fontSize: 12.5 }}>
                The control runs the <b>same ads at full price</b> — not "no ads". A sale
                creative still claims its discount there, so the gap between what the ad
                promises and what the page charges is itself part of what is being measured.
              </div>
            )}
          </>
        ) : (
          <>No arm reported revenue yet — the ladder is still running.</>
        )}
        {eroding.length > 0 && (
          <div style={{ color: "var(--gold)", marginTop: 8 }}>
            ⚠ Reference-price erosion at{" "}
            {eroding.map((r) => `${Math.round(r.level * 100)}%`).join(", ")}: shoppers&apos;
            remembered price fell by up to $
            {Math.abs(Math.min(...eroding.map((r) => r.reference_price_drift!))).toFixed(2)}.
            Deep discounts are teaching the population to expect a lower price.
          </div>
        )}
      </div>
    </div>
  );
}

export default function ExperimentPage({ params }: { params: Promise<{ name: string }> }) {
  const { name: rawName } = use(params);
  const name = decodeURIComponent(rawName);
  const [detail, setDetail] = useState<ExperimentDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  /** ad names for the reaction matrix — any arm's catalog will do, they share one */
  const [creativeNames, setCreativeNames] = useState<Record<string, string>>({});

  useEffect(() => {
    let dead = false;
    const load = () => api.experiment(name)
      .then((d) => !dead && (setDetail(d), setErr(null)))
      .catch((ex) => !dead && setErr(String(ex)));
    load();
    const t = setInterval(load, 4000);
    return () => { dead = true; clearInterval(t); };
  }, [name]);

  const firstRun = detail?.arm_runs[0]?.run_id;
  useEffect(() => {
    if (!firstRun) return;
    api.creatives(firstRun)
      .then((r) => setCreativeNames(Object.fromEntries(
        r.creatives.map((c) => [String(c.creative_id), c.name]))))
      .catch(() => {});
  }, [firstRun]);

  const comparison = detail?.comparison as Record<string, unknown> | null | undefined;
  const adTest = comparison?.ad_test as { creatives?: CreativeRow[] } | undefined;
  const pages = comparison?.page_ab as Record<string, unknown> | undefined;
  const pricing = comparison?.pricing as PricingSection | undefined;
  const ladder = pricing?.ladder?.length ? pricing.ladder : null;
  const goalStats = comparison?.goal_stats as Record<string, { p_buy_need_on: number | null; p_buy_need_off: number | null }> | undefined;
  const orchestratorDead = detail?.orchestrator && !detail.orchestrator.alive
    && detail.arm_runs.some((r) => r.status !== "complete");

  return (
    <main className="wrap" style={{ maxWidth: 1200 }}>
      <div className="runhead">
        <h1 style={{ fontSize: 22 }}>{name}</h1>
        <span className={`statuschip ${comparison ? "done" : ""}`}>
          {comparison ? "COMPLETE" : detail?.orchestrator?.alive ? "RUNNING" : "PARTIAL"}
        </span>
      </div>
      {err && <div className="errbox" style={{ marginBottom: 12 }}>{err}</div>}
      {orchestratorDead && (
        <div className="errbox" style={{ marginBottom: 12 }}>
          The orchestrator exited before every arm finished — tail of its log:
          <pre className="mono" style={{ fontSize: 10.5, whiteSpace: "pre-wrap" }}>{detail?.log_tail.slice(-1200)}</pre>
        </div>
      )}

      <div className="panel" style={{ marginBottom: 12 }}>
        <div className="ph">ARMS · SEQUENTIAL · SHARED SEED = PAIRED POPULATIONS</div>
        <div>
          {detail?.arm_runs.map((r) => (
            <Link key={r.run_id} className="rowlink" href={`/market/${r.run_id}`}>
              <div className="t">
                {r.arm}
                <span className={`chip ${r.status === "running" ? "running" : ""}`}>
                  {r.status === "running" && r.progress.tick != null
                    ? `RUNNING · DAY ${(r.progress.tick ?? 0) + 1}/${r.progress.ticks}`
                    : r.status.toUpperCase()}
                </span>
              </div>
              <div className="m">{r.run_id} · {r.status === "complete" ? "replay + results ready" : "watch live"}</div>
            </Link>
          ))}
        </div>
      </div>

      {adTest?.creatives && (
        <div className="panel" style={{ marginBottom: 12 }}>
          <div className="ph">AD TEST · PER-CREATIVE COMPARISON (comparison.json)</div>
          <div className="pc" style={{ overflowX: "auto" }}>
            <table className="term">
              <thead><tr>
                <th>Arm</th><th>Creative</th><th>CTR</th><th>SAW</th><th>CLICKED</th>
                <th>BROWSED</th><th>CARTED</th><th>BOUGHT</th><th>P(buy|need)</th><th>P(buy|none)</th>
              </tr></thead>
              <tbody>
                {adTest.creatives.map((row) => {
                  const g = goalStats?.[row.arm];
                  return (
                    <tr key={row.arm}>
                      <td className="mono">{row.arm}</td>
                      <td>{creativeNames[String(row.creative)] ?? row.creative}</td>
                      <td className="num"><b>{fmtPct(row.ctr, 1)}</b></td>
                      <td className="num">{row.SAW ?? "—"}</td>
                      <td className="num">{row.CLICKED ?? "—"}</td>
                      <td className="num">{row.BROWSED ?? "—"}</td>
                      <td className="num">{row.CARTED ?? "—"}</td>
                      <td className="num"><b>{row.BOUGHT ?? "—"}</b></td>
                      <td className="num">{fmtPct(g?.p_buy_need_on ?? null, 1)}</td>
                      <td className="num">{fmtPct(g?.p_buy_need_off ?? null, 1)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {pages != null && (
        <div className="panel" style={{ marginBottom: 12 }}>
          <div className="ph">PAGE A/B · CROSS-VARIANT</div>
          <pre className="pc mono" style={{ fontSize: 11, overflowX: "auto" }}>{JSON.stringify(pages, null, 1)}</pre>
        </div>
      )}
      {ladder != null && <PricingVerdict pricing={pricing!} creativeName={creativeNames} />}

      {pricing != null && ladder == null && (
        <div className="panel" style={{ marginBottom: 12 }}>
          <div className="ph">PRICING · CROSS-ARM</div>
          <pre className="pc mono" style={{ fontSize: 11, overflowX: "auto" }}>{JSON.stringify(pricing, null, 1)}</pre>
        </div>
      )}

      {comparison != null && (
        <details className="panel" style={{ marginBottom: 12 }}>
          <summary className="ph" style={{ cursor: "pointer", paddingBottom: 9 }}>RAW comparison.json</summary>
          <pre className="pc mono" style={{ fontSize: 10.5, overflowX: "auto", maxHeight: 400, overflowY: "auto" }}>
            {JSON.stringify(comparison, null, 1)}
          </pre>
        </details>
      )}
      <div className="panel note">
        Paired design: every arm draws the identical population from the shared seed, so per-arm differences are the
        creative&apos;s doing, not the crowd&apos;s. Open any completed arm to replay it day by day.
      </div>
    </main>
  );
}
