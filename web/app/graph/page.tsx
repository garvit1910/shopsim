"use client";

/** 04 GRAPH — the P1 Social Memory Graph.
 *
 * Three mutually-trusting shoppers and their real HydraDB neighbourhoods, in
 * one connected graph. The engine picks the triple (the best one that can
 * actually show TRUSTS_PERSON → BOUGHT → EXPERIENCED), hands over the topology
 * with every edge's version history, and this page owns time, selection and
 * explanation. Nothing here synthesises graph structure.
 *
 * By default this reads the COMMITTED capture (`GET /memory-graph`), not the
 * live store. Shopper worldviews exist only in HydraDB, and that store gets
 * archived and recreated routinely — reading it live meant the exhibit blanked
 * after every reset and reshaped itself run to run. So the graph is fixed: the
 * same real, captured picture whatever simulation is loaded or running. The
 * aside says which run it is a photograph of, because a frozen graph that
 * looks live is a lie.
 *
 * `?run=<id>` still reads that run's graph out of the store — the live path,
 * kept for regenerating the capture and for looking at a specific run.
 */

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import type { GraphEdge, MemoryGraph, MotifPayload, SocialRunRow } from "@/lib/types";
import { shopperName } from "@/lib/format";
import {
  explainMotifs, graphAtDay, localMemory, metStimuli, type ExplainResult,
} from "@/lib/graph";
import MemoryGraphCanvas, { type SimEdge, type SimNode } from "@/components/MemoryGraph";
import GraphAside, { type Mode } from "@/components/GraphAside";

export default function GraphPage() {
  return (
    <Suspense fallback={<Booting />}>
      <GraphRoute />
    </Suspense>
  );
}

function GraphRoute() {
  // ?run=<id> opts into the live store read; absent means the frozen capture.
  const runId = useSearchParams().get("run");
  return <GraphView runId={runId} />;
}

function Booting({ runId }: { runId?: string | null }) {
  return (
    <div className="graphpage">
      <section>
        <div className="gempty">
          <b>Reading the graph</b>
          <span>{runId ?? "committed capture"}</span>
        </div>
      </section>
    </div>
  );
}

function GraphView({ runId }: { runId: string | null }) {
  const [graph, setGraph] = useState<MemoryGraph | null>(null);
  const [socialRuns, setSocialRuns] = useState<SocialRunRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [mode, setMode] = useState<Mode>("people");
  const [day, setDay] = useState(0);
  const [isolated, setIsolated] = useState<number | null>(null);
  const [selection, setSelection] = useState<{ node?: SimNode; edge?: SimEdge } | null>(null);
  const [hovered, setHovered] = useState<{ node?: SimNode; edge?: SimEdge } | null>(null);
  const [stimulus, setStimulus] = useState<number | null>(null);
  const [motifs, setMotifs] = useState<MotifPayload[] | null>(null);
  const [explainLoading, setExplainLoading] = useState(false);

  const live = runId != null;

  useEffect(() => {
    let alive = true;
    setGraph(null);
    setError(null);
    if (live) api.socialRuns().then((r) => alive && setSocialRuns(r)).catch(() => {});
    const load = live ? api.memoryGraph(runId!) : api.frozenGraph();
    load
      .then((g) => {
        if (!alive) return;
        setGraph(g);
        setDay(g.head_tick);
      })
      .catch((e) => alive && setError(
        e instanceof ApiError ? `${e.status} · ${e.message}` : String(e)));
    return () => { alive = false; };
  }, [runId, live]);

  // ---- the graph as it stood on `day` ------------------------------------
  const at = useMemo(() => (graph ? graphAtDay(graph, day) : null), [graph, day]);

  const shopperIds = useMemo(
    () => new Set((graph?.nodes ?? []).filter((n) => n.kind === "shopper").map((n) => n.id)),
    [graph]);

  const focusNodes = useMemo(
    () => (graph?.focus ?? [])
      .map((off) => graph!.nodes.find((n) => Number(n.props.offset) === off))
      .filter((n): n is NonNullable<typeof n> => !!n),
    [graph]);

  const creativeLabel = useCallback((id: number) => {
    const n = graph?.nodes.find((x) => x.id === id);
    return n?.label ?? `Ad ${id}`;
  }, [graph]);

  // ---- explain mode -------------------------------------------------------
  const stimulusOptions = useMemo(
    () => (at && isolated != null ? metStimuli(at.edges, isolated) : []),
    [at, isolated]);

  useEffect(() => {
    if (mode !== "explain" || isolated == null) return;
    if (stimulus == null || !stimulusOptions.some((o) => o.id === stimulus)) {
      setStimulus(stimulusOptions[0]?.id ?? null);
    }
  }, [mode, isolated, stimulus, stimulusOptions]);

  useEffect(() => {
    if (mode !== "explain" || isolated == null || stimulus == null || !graph) {
      setMotifs(null);
      return;
    }
    const offset = Number(graph.nodes.find((n) => n.id === isolated)?.props.offset);

    // Frozen: the traces were captured by the same get_trace call the live
    // path makes, so the numbers on screen are the engine's either way.
    if (!live) {
      setMotifs(graph.traces?.[String(offset)]?.[String(stimulus)]?.motifs ?? []);
      setExplainLoading(false);
      return;
    }
    let alive = true;
    setExplainLoading(true);
    api.trace(runId!, offset, stimulus)
      .then((t) => alive && setMotifs(t.motifs))
      .catch(() => alive && setMotifs([]))
      .finally(() => alive && setExplainLoading(false));
    return () => { alive = false; };
  }, [mode, isolated, stimulus, runId, live, graph]);

  const explain: ExplainResult | null = useMemo(() => {
    if (mode !== "explain" || !motifs || !at) return null;
    return explainMotifs(motifs, at.edges, new Set(at.nodes.map((n) => n.id)));
  }, [mode, motifs, at]);

  // Derived hops are drawn too — dashed, per the pen's indirect class.
  const edges: GraphEdge[] = useMemo(
    () => (at ? [...at.edges, ...(explain?.derivedEdges ?? [])] : []),
    [at, explain]);

  const dimmed = useMemo(() => {
    if (!at || isolated == null) return null;
    const keep = localMemory(edges, isolated, shopperIds);
    return new Set(at.nodes.filter((n) => !keep.has(n.id)).map((n) => n.id));
  }, [at, isolated, edges, shopperIds]);

  const nodesById = useMemo(
    () => new Map((at?.nodes ?? []).map((n) => [n.id, n])), [at]);

  const onSelect = useCallback((sel: { node?: SimNode; edge?: SimEdge } | null) => {
    setSelection(sel);
    if (sel?.node?.kind === "shopper") {
      setIsolated((cur) => (cur === sel.node!.id ? null : sel.node!.id));
      return;
    }
    if (sel) setMode((m) => (m === "explain" ? m : "inspect"));
    if (!sel) setIsolated(null);
  }, []);

  if (error) {
    return (
      <div className="graphpage">
        <section>
          <div className="gempty">
            <b>The graph could not be read</b>
            <span>{error}</span>
            <span className="gnote">
              {live
                ? <>This view reads HydraDB live — if the store is down, start it
                   with <code>infra/up.sh</code>.</>
                : <>The committed capture lives at{" "}
                   <code>fixtures/social-graph/memory-graph.json</code>. Regenerate it
                   with <code>python -m shopsim.runner export-graph</code>.</>}
            </span>
          </div>
        </section>
        <SocialRunSwitcher runs={socialRuns} current={runId} />
      </div>
    );
  }

  if (!graph || !at) return <Booting runId={runId} />;

  if (!graph.focus.length) {
    // Two different nothings, and saying the wrong one sends you hunting the
    // wrong bug. `social_enabled` comes from the manifest's
    // social_config_hash, so a run can have HAD a trust layer while the store
    // it was written to has since been archived away (infra/README's reset
    // ritual moves store/ aside before a timed run; worldviews live only in
    // HydraDB, so they go with it).
    const hadLayer = graph.social_enabled;
    return (
      <div className="graphpage">
        <section>
          <div className="gempty">
            <b>{hadLayer ? "This run's graph is not in the store" : "No trust layer in this run"}</b>
            {hadLayer ? (
              <span>
                {graph.run_id} was built WITH <code>population.social</code> — its
                manifest carries a <code>social_config_hash</code> — but HydraDB
                currently holds no TRUSTS_PERSON edges for it. Its store was most
                likely archived (see <code>infra/README.md</code>); shopper
                worldviews live only in the graph, so they move with it.
                <code> runs/</code> still has this run's events and results.
              </span>
            ) : (
              <span>
                {graph.run_id} was built without <code>population.social</code>, so it
                holds no TRUSTS_PERSON edges — there is nothing social to draw, and
                inventing a social graph for it would be a lie.
              </span>
            )}
          </div>
        </section>
        <SocialRunSwitcher runs={socialRuns} current={runId} />
      </div>
    );
  }

  return (
    <div className="graphpage">
      <section>
        <div className="gcorner">
          <span>{at.nodes.length} nodes · {edges.length} edges</span>
          <span>· day {day}</span>
          {isolated != null && (
            <span>· {shopperName(Number(nodesById.get(isolated)?.props.offset))} isolated</span>
          )}
        </div>
        <MemoryGraphCanvas
          nodes={at.nodes}
          edges={edges}
          litEdgeIds={explain?.litEdgeIds ?? EMPTY_STR}
          hotEdgeIds={explain?.hotEdgeIds ?? EMPTY_STR}
          focusOffsets={graph.focus}
          dimmedNodeIds={dimmed}
          onSelect={onSelect}
          onHover={setHovered}
        />
      </section>
      <GraphAside
        graph={graph} mode={mode} setMode={setMode} day={day} setDay={setDay}
        focus={focusNodes} isolated={isolated} setIsolated={setIsolated}
        selection={selection} hovered={hovered} explain={explain}
        explainStimulus={stimulus} setExplainStimulus={setStimulus}
        stimulusOptions={stimulusOptions} explainLoading={explainLoading}
        nodesById={nodesById} creativeLabel={creativeLabel}
      />
    </div>
  );
}

function SocialRunSwitcher({ runs, current }: { runs: SocialRunRow[]; current: string | null }) {
  const others = runs.filter((r) => r.run_id !== current);
  return (
    <aside>
      <h1>Social Memory</h1>
      <h3>no trust layer here</h3>
      <strong>Runs that have one</strong>
      {others.length ? (
        <div className="gpeople">
          {others.map((r) => (
            <Link key={r.run_id} href={`/graph?run=${r.run_id}`} className="gperson">
              <i style={{ background: "hsl(152,94%,72%)" }} />
              <b>{r.label}</b>
              <span>{r.ticks} days</span>
            </Link>
          ))}
        </div>
      ) : (
        <p className="gnote">
          None yet. Launch one with
          <code> fixtures/run-configs/social-graph-demo.json</code> — it sets
          <code> population.social.enabled</code> and pays for the channel with
          <code> calibration.appraisal.w_social</code>.
        </p>
      )}
    </aside>
  );
}

const EMPTY_STR: ReadonlySet<string> = new Set<string>();
