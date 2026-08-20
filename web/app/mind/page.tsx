"use client";

/** 05 MIND — the Shopper Mind exhibit.
 *
 * One shopper. One mind. Many signals. The pinned shopper's real HydraDB
 * worldview drawn as a head (six lobes, the reference layout), the currently
 * selected Studio ad as the stimulus on the left, the active retrieval path
 * lit through the mind, and the engine's appraisal + gate probabilities on
 * the right.
 *
 * Everything on this page reads the COMMITTED capture (`GET /shopper-mind`,
 * CONTRACT v3.12-draft): the mind was chosen once, at export time, and always
 * exists — it does not blank when the store is reset and does not become a
 * different shopper when a new simulation loads. The provenance line under
 * the title names the run it is a photograph of, as the contract requires.
 * The ad card itself (image, copy, perceived claims) comes from the same
 * catalog the capture names.
 */

import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { proxied } from "@/lib/api";
import type { CreativeCard, FrozenMind, GraphEdge } from "@/lib/types";
import { explainMotifs, graphAtDay } from "@/lib/graph";
import { fmtUsd, shopperLabel } from "@/lib/format";
import { selectMindAd, useMindSel } from "@/lib/mind";
import MindGraph from "@/components/MindGraph";
import {
  AppraisalPanel, DecisionPanel, needLabelFrom, ShopperCard, StimulusCard,
} from "@/components/MindPanels";

export default function MindPage() {
  const [mind, setMind] = useState<FrozenMind | null>(null);
  const [cards, setCards] = useState<CreativeCard[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const picked = useMindSel((s) => s.creativeId);

  useEffect(() => {
    let alive = true;
    api.frozenMind()
      .then((g) => {
        if (!alive) return;
        setMind(g);
        api.catalogCreatives(g.catalog_key)
          .then((c) => alive && setCards(c.creatives))
          .catch(() => alive && setCards([]));
      })
      .catch((e) => alive && setError(
        e instanceof ApiError ? `${e.status} · ${e.message}` : String(e)));
    return () => { alive = false; };
  }, []);

  // ---- the pinned shopper and the validated stimulus ----------------------
  const offset0 = mind?.focus[0] ?? null;
  const previews = mind && offset0 != null ? mind.previews[String(offset0)] : null;

  const cid = useMemo(() => {
    if (!mind) return null;
    const demo = new Set(mind.demo_stimuli.map((d) => d.creative_id));
    // Studio's pick applies when it lives in this mind's world; otherwise the
    // capture's own lead stimulus. (Out-of-world ads: out of scope, by design.)
    if (picked != null && demo.has(picked)) return picked;
    return mind.demo_stimuli[0]?.creative_id ?? null;
  }, [mind, picked]);

  const preview = previews && cid != null ? previews[String(cid)] ?? null : null;
  const pagePreview = previews && preview?.stimulus.page_id != null
    ? previews[String(preview.stimulus.page_id)] ?? null : null;

  // ---- the graph as of the capture's head tick ----------------------------
  const at = useMemo(
    () => (mind ? graphAtDay(mind, mind.head_tick) : null), [mind]);

  const selfNode = useMemo(
    () => at?.nodes.find(
      (n) => n.kind === "shopper" && Number(n.props.offset) === offset0) ?? null,
    [at, offset0]);

  const nodesById = useMemo(
    () => new Map((at?.nodes ?? []).map((n) => [n.id, n])), [at]);

  // Two tiers of retrieval path, both mapped onto stored edges by 04 Graph's
  // Explain machinery. PRIMARY = the decision's own motifs (preview.motifs —
  // the strongest per type, exactly what appraise() consumed; the Appraisal
  // panel's numbers come from these). SOFT = the trace's other candidates
  // (relaxed thresholds, the explanatory habit/experience walks): HydraDB
  // retrieval surfaced them, the decision did not use them.
  const explain = useMemo(() => {
    if (!mind || !at || offset0 == null || cid == null || !preview) return null;
    const nodeIds = new Set(at.nodes.map((n) => n.id));
    const primary = explainMotifs(preview.motifs, at.edges, nodeIds);
    const traced = mind.traces?.[String(offset0)]?.[String(cid)]?.motifs;
    const all = traced ? explainMotifs(traced, at.edges, nodeIds) : primary;
    const soft = new Set<string>();
    for (const id of [...all.litEdgeIds, ...all.hotEdgeIds]) {
      if (!primary.litEdgeIds.has(id) && !primary.hotEdgeIds.has(id)) soft.add(id);
    }
    const derived = new Map<string, GraphEdge>();
    for (const e of [...primary.derivedEdges, ...all.derivedEdges]) derived.set(e.id, e);
    return { primary, soft, derivedEdges: [...derived.values()] };
  }, [mind, at, offset0, cid, preview]);

  const edges: GraphEdge[] = useMemo(
    () => (at ? [...at.edges, ...(explain?.derivedEdges ?? [])] : []),
    [at, explain]);

  const card = useMemo(
    () => cards?.find((c) => c.creative_id === cid) ?? null, [cards, cid]);

  const agentStats = useMemo(() => {
    if (!preview) return [];
    const s = preview.scalars;
    const n = (v: unknown) => (typeof v === "number" ? v : null);
    const budget = n(s.budget_left);
    const adstock = n(s.adstock);
    const exposures = n(s.exposures_72h);
    const cart = Array.isArray(s.cart) ? s.cart.length : 0;
    return [
      { label: "budget left", value: budget == null ? "—" : fmtUsd(budget) },
      { label: "fatigue · adstock", value: adstock == null ? "—" : adstock.toFixed(2) },
      { label: "seen /72h", value: exposures == null ? "—" : String(exposures) },
      { label: "cart", value: String(cart) },
    ];
  }, [preview]);

  if (error) {
    return (
      <div className="mindpage">
        <section className="mcanvas">
          <div className="mempty">
            <b>The mind could not be read</b>
            <span>{error}</span>
            <span className="mnote">
              The committed capture lives at{" "}
              <code>fixtures/shopper-mind/mind.json</code>. Regenerate it with{" "}
              <code>python -m shopsim.runner export-graph --config
              runs/experiments/shopper-mind-demo/run_config.json --run RUN_ID
              --out fixtures/shopper-mind/mind.json --previews</code>
              {" "}— see the README beside it.
            </span>
          </div>
        </section>
      </div>
    );
  }

  if (!mind || !at || offset0 == null || cid == null || !preview || !selfNode) {
    return (
      <div className="mindpage">
        <section className="mcanvas">
          <div className="mempty">
            <b>Reading the mind</b>
            <span>the committed capture</span>
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className="mindpage">
      <div className="mcol left">
        <header className="mtitle">
          <h1>Shopper Mind</h1>
          <p className="msubtitle">One shopper. One <em>mind</em>. Many signals.</p>
          {/* required provenance (v3.12-draft): frozen, and from which run */}
          <p className="mprov">
            frozen capture · {mind.captured?.run_id ?? mind.run_id} · day{" "}
            {mind.head_tick} of {mind.ticks}
          </p>
        </header>

        <StimulusCard card={card} />

        {cards && cards.length > 0 && (
          <div className="mthumbs">
            {mind.demo_stimuli.map((d) => {
              const c = cards.find((x) => x.creative_id === d.creative_id);
              if (!c?.image_url) return null;
              return (
                <button
                  key={d.creative_id}
                  className={d.creative_id === cid ? "on" : ""}
                  onClick={() => selectMindAd(d.creative_id)}
                  title={c.headline || c.name}
                  aria-label={`Show this ad in the mind: ${c.name}`}
                >
                  <img src={proxied(c.image_url)} alt="" />
                </button>
              );
            })}
          </div>
        )}

        <div className="mspacer" />

        <ShopperCard
          offset={offset0}
          shopperId={selfNode.id}
          segmentId={selfNode.props.segment_id == null
            ? null : Number(selfNode.props.segment_id)}
          runId={mind.captured?.run_id ?? mind.run_id}
          headTick={mind.head_tick}
          ticks={mind.ticks}
          preview={preview}
          needLabel={needLabelFrom(preview, nodesById)}
        />
      </div>

      <section className="mcanvas">
        <MindGraph
          nodes={at.nodes}
          edges={edges}
          selfId={selfNode.id}
          selfLabel={shopperLabel(offset0)}
          stimulusId={cid}
          stimulusLabel={card?.name ?? nodesById.get(cid)?.label ?? `Ad ${cid}`}
          litEdgeIds={explain?.primary.litEdgeIds ?? EMPTY}
          hotEdgeIds={explain?.primary.hotEdgeIds ?? EMPTY}
          softEdgeIds={explain?.soft ?? EMPTY}
          agentStats={agentStats}
        />
        <div className="mlegend">
          <div><i className="lg path" /> Decisive retrieval path — fed the appraisal</div>
          <div><i className="lg soft" /> Considered by retrieval, not decisive</div>
          <div><i className="lg assoc" /> Other Associations</div>
          <div><i className="lg node" /> Memory / Belief Node</div>
          <div><i className="lg scalar" /> Engine scalars — not graph nodes</div>
          <div><i className="lg conn" /> Lobe connectors — legend, not stored</div>
        </div>
      </section>

      <div className="mcol right">
        <div className="evarrow" aria-hidden="true">◂ ─ ─ evidence</div>
        <AppraisalPanel preview={preview} />
        <div className="dnarrow" aria-hidden="true">▾</div>
        <DecisionPanel preview={preview} pagePreview={pagePreview} />
      </div>
    </div>
  );
}

const EMPTY: ReadonlySet<string> = new Set<string>();
