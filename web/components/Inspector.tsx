"use client";

/** The shopper inspector — the crown jewel. Everything here is a real
 * payload: worldview (beliefs + confidence + provenance sentences),
 * cause-stamped preference chains with a valid_to version rail, the motif
 * why-trace, and the DECISION REPLAY block: real appraise() dims and pure
 * stage_probabilities() from /decision-preview, with the need-off
 * counterfactual. As-of scrubbing filters the version chains client-side. */

import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useMarket } from "@/lib/market";
import { STAGE_RANK, STAGE_NAMES, segmentOf } from "@/lib/selectors";
import type { DecisionPreview, PrefVersion, Worldview } from "@/lib/types";
import { fmtPct, fmtW, shopperLabel } from "@/lib/format";
import { conceptName } from "./panels";
import type { CreativeInfo } from "./panels";

const ASPECT_TRUST = 7101;
const DIM_COLORS: Record<string, string> = {
  relevance: "#4cc38a", credibility: "#6da7ec", brand_message_fatigue: "#d95926",
  offer_attractiveness: "#eda100", expectation_alignment: "#9085e9",
};

interface BeliefRow { dst?: number; value: number; evidence: number; about_id: number; that_id: number; t: number; valid_to: number }

export default function Inspector({ offset, viewTick, creatives, onClose }: {
  offset: number; viewTick: number; creatives: CreativeInfo[]; onClose: () => void;
}) {
  const s = useMarket();
  const runId = s.runId!;
  const [worldview, setWorldview] = useState<Worldview | null>(null);
  const [beliefHist, setBeliefHist] = useState<BeliefRow[] | null>(null);
  const [chains, setChains] = useState<Record<number, PrefVersion[]>>({});
  const [preview, setPreview] = useState<DecisionPreview | null>(null);
  const [pagePreview, setPagePreview] = useState<DecisionPreview | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const lead = creatives[0];

  useEffect(() => {
    let dead = false;
    setWorldview(null); setPreview(null); setPagePreview(null); setChains({}); setErr(null);
    (async () => {
      try {
        const wv = await api.worldview(runId, offset);
        if (dead) return;
        setWorldview(wv);
        const conceptIds = wv.preferences.map((p) => p.concept).slice(0, 3);
        const chainPairs = await Promise.all(conceptIds.map(async (c) => {
          try { return [c, await api.preferenceHistory(runId, offset, c)] as const; }
          catch { return [c, []] as const; }
        }));
        if (!dead) setChains(Object.fromEntries(chainPairs));
        api.beliefHistory(runId, offset).then((rows) => !dead && setBeliefHist(rows as unknown as BeliefRow[])).catch(() => {});
        if (lead) {
          const pv = await api.decisionPreview(runId, offset, lead.id);
          if (dead) return;
          setPreview(pv);
          if (pv.stimulus.page_id != null) {
            api.decisionPreview(runId, offset, pv.stimulus.page_id)
              .then((pp) => !dead && setPagePreview(pp)).catch(() => {});
          }
        }
      } catch (ex) {
        if (!dead) setErr(ex instanceof Error ? ex.message : String(ex));
      }
    })();
    return () => { dead = true; };
  }, [runId, offset, lead?.id]);

  const t0 = s.manifest?.t0 ?? 0;
  const tickSeconds = s.manifest?.tick_seconds ?? 86400;
  const asOfT = t0 + viewTick * tickSeconds;
  const atHead = viewTick >= s.headTick;

  // diary from the already-loaded event stream, ≤ viewing tick
  const diary = useMemo(() => {
    const out: { day: number; type: string; detail: string }[] = [];
    for (let d = Math.min(viewTick, s.eventsByTick.length - 1); d >= 0 && out.length < 16; d--) {
      for (const rec of [...(s.eventsByTick[d] ?? [])].reverse()) {
        if ((rec.shopper_id ?? -1) % 100_000 !== offset) continue;
        if (out.length >= 16) break;
        out.push({
          day: d, type: rec.type,
          detail: rec.type === "BOUGHT" && rec.price ? `$${rec.price.toFixed(2)}`
            : rec.type === "EXPERIENCED" && rec.sat != null ? `sat ${rec.sat.toFixed(2)}`
            : rec.type.startsWith("NEED") ? (rec.strength != null ? `strength ${rec.strength}` : "")
            : `→ ${rec.subject ?? ""}`,
        });
      }
    }
    return out;
  }, [s.eventsByTick, offset, viewTick]);

  const funnelStage = useMemo(() => {
    let st = 0;
    for (let d = 0; d <= viewTick && d < s.eventsByTick.length; d++)
      for (const rec of s.eventsByTick[d])
        if ((rec.shopper_id ?? -1) % 100_000 === offset)
          st = Math.max(st, STAGE_RANK[rec.type] ?? 0);
    return st;
  }, [s.eventsByTick, offset, viewTick]);

  const buys = diary.filter((d) => d.type === "BOUGHT").length;
  const needLive = useMemo(() => {
    let live: { strength?: number } | null = null;
    for (let d = 0; d <= viewTick && d < s.eventsByTick.length; d++)
      for (const rec of s.eventsByTick[d]) {
        if ((rec.shopper_id ?? -1) % 100_000 !== offset) continue;
        if (rec.type === "NEED_ACTIVATED") live = { strength: rec.strength };
        if (rec.type === "NEED_SATISFIED" || rec.type === "NEED_EXPIRED") live = null;
      }
    return live;
  }, [s.eventsByTick, offset, viewTick]);

  // as-of preference value from the chain (t <= asOfT and still valid)
  const asOfW = (chain: PrefVersion[] | undefined, liveW: number): { w: number; version: PrefVersion | null } => {
    if (!chain?.length) return { w: liveW, version: null };
    if (atHead) return { w: liveW, version: chain[chain.length - 1] };
    const past = chain.filter((v) => v.t <= asOfT);
    return past.length ? { w: past[past.length - 1].w, version: past[past.length - 1] } : { w: chain[0].w, version: chain[0] };
  };

  const trustAsOf = useMemo(() => {
    if (atHead) {
      const b = worldview?.beliefs.find((x) => x.aspect === "trust");
      return b ? { value: b.value, confidence: b.confidence, sentence: b.provenance_sentence } : null;
    }
    const rows = (beliefHist ?? []).filter((r) => r.that_id === ASPECT_TRUST && r.t <= asOfT);
    if (!rows.length) return null;
    const cur = rows[rows.length - 1];
    return { value: cur.value, confidence: cur.evidence / (cur.evidence + 0.7), sentence: `as-of day ${viewTick + 1} · evidence ${cur.evidence.toFixed(1)}` };
  }, [atHead, worldview, beliefHist, asOfT, viewTick]);

  const probChips = (pv: DecisionPreview | null, stages: string[]) =>
    stages.map((st) => {
      const v = pv?.probabilities[st];
      return (
        <span key={st} className="probchip">
          P({st.toLowerCase()}) <b style={{ color: st === "BUY" ? "#eda100" : "#e8e9ec" }}>{v == null ? "…" : v.toFixed(3)}</b>
        </span>
      );
    });

  const cf = preview?.counterfactual_need_off ?? pagePreview?.counterfactual_need_off;
  const buyP = pagePreview?.probabilities.BUY;
  const cfBuyP = pagePreview?.counterfactual_need_off?.probabilities.BUY;

  const railChain = chains[Object.keys(chains).map(Number).sort((a, b) =>
    (chains[b]?.length ?? 0) - (chains[a]?.length ?? 0))[0]];

  return (
    <>
      <div className="drawer-scrim" onClick={onClose} />
      <div className="drawer" role="dialog" aria-label="Shopper inspector">
        <button className="x" onClick={onClose} aria-label="Close">×</button>
        <div style={{ fontSize: 18, fontWeight: 800 }}>
          {shopperLabel(offset)}{" "}
          <span style={{ color: "#8b8f98", fontWeight: 400 }}>
            · shopper {s.manifest ? 1_000_000 + s.manifest.run_index * 100_000 + offset : offset}
          </span>
        </div>
        <div style={{ fontFamily: "var(--mono)", fontSize: 11.5, color: "#8b8f98" }}>
          {segmentOf(s.population, offset)} · viewing day {viewTick + 1}{atHead ? " (head)" : " (as-of scrub)"}
        </div>
        <div style={{ marginTop: 8 }}>
          <span className="dchip">{segmentOf(s.population, offset) || "segment —"}</span>
          <span className="dchip">funnel: {STAGE_NAMES[funnelStage]}</span>
          {buys > 0 && <span className="dchip">{buys} purchase{buys > 1 ? "s" : ""}</span>}
          {needLive && <span className="dchip need">NEEDS · strength {needLive.strength?.toFixed(2) ?? "—"} · live</span>}
        </div>
        {err && <div style={{ color: "#e66767", marginTop: 10, fontSize: 12.5 }}>{err}</div>}

        <h3>Preferences · learned, cause-stamped</h3>
        {worldview?.preferences.slice(0, 4).map((p) => {
          const { w } = asOfW(chains[p.concept], p.w);
          return (
            <div className="barrow" key={p.concept}>
              <div className="bl">{conceptName(p.concept)}</div>
              <div className="bt"><i className="bf" style={{ width: `${(100 * w).toFixed(1)}%`, background: "#4cc38a", display: "block", height: "100%" }} /></div>
              <div className="bv">{fmtW(w)}</div>
            </div>
          );
        }) ?? <div className="prov">loading worldview…</div>}

        <h3>Beliefs</h3>
        {trustAsOf ? (
          <div className="bcard">
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <span>trust · brand</span><b className="mono">{fmtW(trustAsOf.value)}</b>
            </div>
            <div className="conf"><i style={{ width: `${(100 * trustAsOf.confidence).toFixed(0)}%` }} /></div>
            <div className="prov">confidence {trustAsOf.confidence.toFixed(2)} — {trustAsOf.sentence}</div>
          </div>
        ) : (
          <div className="bcard">
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <span>trust · brand</span><b className="mono" style={{ color: "#8b8f98" }}>null</b>
            </div>
            <div className="prov">No belief node — unknown brand. Appraisal floors to neutral-low; nothing is fabricated (abstention, C1).</div>
          </div>
        )}

        <h3>Decision replay · vs {lead?.name ?? "lead creative"} · real appraise() + stage_probabilities()</h3>
        {preview ? (
          <>
            {Object.entries(preview.appraisal)
              .filter(([k, v]) => v != null && k in DIM_COLORS)
              .map(([k, v]) => (
                <div className="barrow" key={k}>
                  <div className="bl">{k.replace(/_/g, " ")}</div>
                  <div className="bt"><i className="bf" style={{ width: `${(100 * (v as number)).toFixed(0)}%`, background: DIM_COLORS[k], display: "block", height: "100%" }} /></div>
                  <div className="bv">{(v as number).toFixed(2)}</div>
                </div>
              ))}
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", margin: "10px 0 4px" }}>
              {probChips(preview, ["CLICK"])}
              {probChips(pagePreview, ["BROWSE", "CART", "BUY"])}
            </div>
            {cf && buyP != null && cfBuyP != null && (
              <div style={{ fontFamily: "var(--mono)", fontSize: 11.5, color: "#eda100", margin: "6px 0 2px" }}>
                need removed → P(buy) {cfBuyP.toFixed(3)} · the live need multiplies buy odds ×{cfBuyP > 0 ? (buyP / cfBuyP).toFixed(1) : "∞"}
              </div>
            )}
            {cf && buyP == null && (
              <div style={{ fontFamily: "var(--mono)", fontSize: 11.5, color: "#eda100", margin: "6px 0 2px" }}>
                counterfactual (need removed): P(click) {cf.probabilities.CLICK?.toFixed(3) ?? "—"}
              </div>
            )}
            <p className="prov">Recomputed server-side from the live graph context with the pure formula mind — no rng, byte-identical on refresh. Traits never leave the engine.</p>
          </>
        ) : <div className="prov">computing from the live context…</div>}

        <h3>Preference timeline + version rail</h3>
        {railChain?.length ? (
          <>
            <svg viewBox="0 0 380 30" width="100%" height="30" role="img" aria-label="preference version rail">
              {railChain.map((v, i) => {
                const ticks = s.manifest?.ticks ?? 14;
                const x = (d: number) => 8 + (364 * Math.max(0, Math.min(ticks - 1, d))) / (ticks - 1);
                const from = Math.floor((v.t - t0) / tickSeconds);
                const to = v.valid_to > 4e15 ? viewTick : Math.floor((v.valid_to - t0) / tickSeconds);
                return (
                  <g key={i}>
                    <rect x={x(from)} y={8} width={Math.max(2.5, x(Math.max(to, from)) - x(from))} height={13} rx={2}
                      fill="#4cc38a" opacity={0.22 + v.w * 0.78}>
                      <title>d{from + 1}→{v.valid_to > 4e15 ? "live" : `d${to + 1}`} · w {v.w.toFixed(3)} · {v.cause_kind} {v.cause_id || ""}</title>
                    </rect>
                    <line x1={x(from)} x2={x(from)} y1={5} y2={24} stroke="#8b8f98" strokeWidth={1} />
                  </g>
                );
              })}
            </svg>
            <ul className="tl">
              {railChain.filter((v) => atHead || v.t <= asOfT).map((v, i, arr) => {
                const prev = i > 0 ? arr[i - 1].w : null;
                const delta = prev == null ? null : v.w - prev;
                return (
                  <li key={i}>
                    <span className="w">{v.w.toFixed(3)}</span>
                    {delta != null && Math.abs(delta) > 0.0005 && (
                      <span className={delta > 0 ? "up" : "dn"} style={{ fontFamily: "var(--mono)", fontSize: 11, marginLeft: 5 }}>
                        {delta > 0 ? "+" : ""}{delta.toFixed(3)}
                      </span>
                    )}
                    <span className="cause">{v.cause_kind}{v.cause_id ? ` ${v.cause_id}` : ""}</span>
                    <div style={{ color: "#8b8f98", fontSize: 11 }}>day {Math.floor((v.t - t0) / tickSeconds) + 1}</div>
                  </li>
                );
              })}
            </ul>
          </>
        ) : <div className="prov">no learned versions yet — priors only (SEED)</div>}

        <h3>Why-trace · motif paths (get_trace)</h3>
        {preview?.motifs.length ? preview.motifs.map((m, i) => (
          <div className="path" key={i}>
            <span className="rel">{m.type}</span>{" "}
            <span style={{ color: "#8b8f98" }}>
              {m.strength != null && `strength ${Number(m.strength).toFixed(2)} `}
              {m.urgency != null && `urgency ${Number(m.urgency).toFixed(2)}`}
            </span>
            <br />{m.path.join(" — ")}
          </div>
        )) : <div className="prov">no motifs — no paths, no knowledge (abstention)</div>}

        {worldview && worldview.expects.length > 0 && (
          <>
            <h3>Belief vs truth · EXPECTS strengths</h3>
            {worldview.expects.slice(0, 5).map((e, i) => (
              <div className="barrow" key={i}>
                <div className="bl">{conceptName(e.concept)}</div>
                <div className="bt"><i className="bf" style={{ width: `${(100 * e.strength).toFixed(0)}%`, background: "#9085e9", display: "block", height: "100%" }} /></div>
                <div className="bv">{e.strength.toFixed(2)}</div>
              </div>
            ))}
            <p className="prov">what the ads taught this shopper to expect — page truth divergence shows up as the expectation_violation motif above.</p>
          </>
        )}

        <h3>Diary · last {diary.length} events ≤ day {viewTick + 1}</h3>
        <div className="diary">
          {diary.map((d, i) => (
            <div key={i}><span style={{ color: "#8b8f98", marginRight: 8 }}>d{d.day + 1}</span>{d.type} <span style={{ color: "#5c6069" }}>{d.detail}</span></div>
          ))}
          {diary.length === 0 && <div style={{ color: "#8b8f98" }}>nothing yet</div>}
        </div>
      </div>
    </>
  );
}
