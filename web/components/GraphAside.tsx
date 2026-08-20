"use client";

/** The 04 Graph aside — the pen's 360px panel, carrying our content.
 *
 * Structure and typography are AlexVanK's (title, subtitle, Controls, Legend);
 * the copy is ours, and the two legend paragraphs still say what the pen's
 * said, because the distinction survived the port: solid lines are direct
 * relationships, dashed ones are indirect.
 */

import type { GraphEdge, GraphNode, MemoryGraph, MotifPayload } from "@/lib/types";
import { brandName, fmtUsd, padOffset, segmentName, shopperName } from "@/lib/format";
import { endpointId, occurrencesBy, versionAt, type ExplainResult } from "@/lib/graph";
import type { SimEdge, SimNode } from "./MemoryGraph";

export type Mode = "people" | "inspect" | "explain";

const num = (v: unknown) =>
  typeof v === "number" ? (Number.isInteger(v) ? String(v) : v.toFixed(4)) : String(v);

export function nodeTitle(n: GraphNode): string {
  if (n.kind === "shopper") return shopperName(Number(n.props.offset));
  if (n.kind === "brand") return brandName(n.id);
  return n.label ?? String(n.id);
}

export default function GraphAside({
  graph, mode, setMode, day, setDay, focus, isolated, setIsolated,
  selection, hovered, explain, explainStimulus, setExplainStimulus,
  stimulusOptions, explainLoading, nodesById, creativeLabel,
}: {
  graph: MemoryGraph;
  mode: Mode;
  setMode: (m: Mode) => void;
  day: number;
  setDay: (d: number) => void;
  focus: GraphNode[];
  isolated: number | null;
  setIsolated: (id: number | null) => void;
  selection: { node?: SimNode; edge?: SimEdge } | null;
  hovered: { node?: SimNode; edge?: SimEdge } | null;
  explain: ExplainResult | null;
  explainStimulus: number | null;
  setExplainStimulus: (id: number) => void;
  stimulusOptions: { id: number; kind: "creative" | "page" }[];
  explainLoading: boolean;
  nodesById: Map<number, GraphNode>;
  creativeLabel: (id: number) => string;
}) {
  const asOf = graph.t0 + day * graph.tick_seconds;
  const shown = hovered ?? selection;

  return (
    <aside>
      <h1>Social Memory</h1>
      <h2>Graph (Force-Directed)</h2>
      <h3>HydraDB · {graph.run_id}</h3>

      <div className="gtabs">
        {(["people", "inspect", "explain"] as Mode[]).map((m) => (
          <button key={m} className={mode === m ? "on" : ""} onClick={() => setMode(m)}>
            {m}
          </button>
        ))}
      </div>

      <strong>As of</strong>
      <div className="gscrub">
        <span className="gday">DAY {day}</span>
        {/* capped at head_tick, not ticks-1: a run that has consolidated 12 of
            28 days has NOTHING to show for day 20, and a scrub that happily
            slid there would be reporting an empty worldview as a real one. */}
        <input
          type="range" min={0} max={Math.max(graph.head_tick, 0)} step={1}
          value={day} onChange={(e) => setDay(Number(e.target.value))}
          aria-label="viewing day"
        />
        <span className="gday">{day >= graph.head_tick ? "HEAD" : `/ ${graph.head_tick}`}</span>
      </div>
      <p className="gnote">
        Every edge carries its own <code>t</code> and <code>valid_to</code>, so this
        is a real as-of read of the store, not a replay of the event log.
        {graph.head_tick < graph.ticks - 1 && (
          <> This run has consolidated {graph.head_tick + 1} of its {graph.ticks}{" "}
          days, so the scrub stops at day {graph.head_tick}.</>
        )}
      </p>

      {mode === "people" && (
        <PeoplePanel graph={graph} focus={focus} isolated={isolated}
                     setIsolated={setIsolated} asOf={asOf} />
      )}
      {mode === "inspect" && (
        <InspectPanel shown={shown} nodesById={nodesById} asOf={asOf}
                      graph={graph} creativeLabel={creativeLabel} />
      )}
      {mode === "explain" && (
        <ExplainPanel graph={graph} explain={explain} loading={explainLoading}
                      stimulus={explainStimulus} setStimulus={setExplainStimulus}
                      options={stimulusOptions} isolated={isolated}
                      nodesById={nodesById} creativeLabel={creativeLabel} />
      )}

      <hr />
      <strong>Controls</strong>
      <p>✔ Drag &amp; drop the nodes to reorganize the graph.</p>
      <p>✔ Once a node has been pinned, unpin it by double-clicking it.</p>
      <p>✔ Click a shopper to fade everything outside their own memory.</p>

      <strong>Legend</strong>
      <div className="glegend">
        <div><i style={{ background: "hsl(152,94%,72%)" }} />people — shoppers and their friends</div>
        <div><i style={{ background: "hsl(202,94%,78%)" }} />the world — ads, pages, products, brands, concepts</div>
        <div><i style={{ background: "hsl(42,94%,72%)" }} />the mind — beliefs, needs, expectations</div>
        <div><i style={{ background: "var(--gold)", outline: "2px dashed #000", outlineOffset: 2 }} />pinned</div>
      </div>
      <p>
        Node size and colour saturation follow the number of edges connected to it.
        The more edges, the stronger the hue and the larger the radius.
      </p>
      <p>
        Continuous lines are <u>direct</u> relationships — rows HydraDB actually
        stores. Dashed lines are <u>indirect</u> ones the engine derives at
        retrieval time and never writes.
      </p>
    </aside>
  );
}

function PeoplePanel({ graph, focus, isolated, setIsolated, asOf }: {
  graph: MemoryGraph; focus: GraphNode[]; isolated: number | null;
  setIsolated: (id: number | null) => void; asOf: number;
}) {
  const trust = graph.edges.filter((e) => e.rel === "TRUSTS_PERSON");
  const why = graph.candidates[0]?.why;
  return (
    <>
      <strong>The three friends</strong>
      <div className="gpeople">
        {focus.map((n) => {
          const off = Number(n.props.offset);
          const bought = graph.edges.filter(
            (e) => e.rel === "BOUGHT" && e.source === n.id && (e.versions[0]?.t ?? 0) <= asOf).length;
          return (
            <button key={n.id} className={`gperson ${isolated === n.id ? "on" : ""}`}
                    onClick={() => setIsolated(isolated === n.id ? null : n.id)}>
              <i style={{ background: "hsl(152,94%,72%)" }} />
              <b>{shopperName(off)}</b>
              <span>{padOffset(off)} · {segmentName(Number(n.props.segment_id))}
                {bought ? ` · ${bought} bought` : ""}</span>
            </button>
          );
        })}
      </div>

      <strong>Trust between them</strong>
      <dl className="gkv">
        {dedupeTrust(trust, new Set(focus.map((f) => f.id))).map((e) => (
          <div key={e.id} style={{ display: "contents" }}>
            <dt>{shopperName(offsetOf(e.source, focus))} ↔ {shopperName(offsetOf(e.target, focus))}</dt>
            <dd>w = {num(e.versions[0]?.w)}</dd>
          </div>
        ))}
      </dl>
      {why && <p className="gnote">Chosen because {why}.</p>}
      <p className="gnote">
        TRUSTS_PERSON is a seeded Watts-Strogatz small world (degree ≈ 4, weights
        U(0.4, 0.9)). It is written in both directions because retrieval only ever
        reads outgoing edges.
      </p>
    </>
  );
}

function InspectPanel({ shown, nodesById, asOf, graph, creativeLabel }: {
  shown: { node?: SimNode; edge?: SimEdge } | null;
  nodesById: Map<number, GraphNode>; asOf: number; graph: MemoryGraph;
  creativeLabel: (id: number) => string;
}) {
  const dayOf = (t: number) => Math.round((t - graph.t0) / graph.tick_seconds);
  if (!shown) {
    return (
      <>
        <strong>Inspect</strong>
        <p className="gnote">
          Hover or click any node or edge. Every value shown is the row HydraDB
          returned — nothing here is computed for display.
        </p>
      </>
    );
  }
  if (shown.edge) {
    const e = shown.edge;
    const v = versionAt(e, asOf) ?? e.versions[e.versions.length - 1] ?? {};
    const label = (end: unknown) => {
      const id = endpointId(end);
      const n = nodesById.get(id);
      if (!n) return String(id);
      return n.kind === "creative" ? creativeLabel(id) : nodeTitle(n);
    };
    return (
      <>
        <strong>Relationship</strong>
        <p className="gpath">
          <em>{label(e.source)}</em> <span className="grel">{e.rel}</span>{" "}
          <em>{label(e.target)}</em>
        </p>
        <dl className="gkv">
          {Object.entries(v)
            .filter(([k]) => k !== "run")
            .map(([k, val]) => (
              <div key={k} style={{ display: "contents" }}>
                <dt>{k}</dt>
                <dd>{k === "valid_to" && Number(val) > 4e15 ? "live"
                     : k === "valid_to" ? `until day ${dayOf(Number(val))}`
                     : k === "t" ? `day ${dayOf(Number(val))}`
                     : num(val)}</dd>
              </div>
            ))}
          {e.time === "event" && e.count > 1 && (
            <div style={{ display: "contents" }}>
              <dt>times</dt><dd>{occurrencesBy(e, asOf)} of {e.count}</dd>
            </div>
          )}
          <div style={{ display: "contents" }}>
            <dt>stored</dt>
            <dd>{e.derived ? "derived at retrieval" : "yes — a row in HydraDB"}</dd>
          </div>
        </dl>
      </>
    );
  }
  const n = shown.node!;
  return (
    <>
      <strong>{n.kind}</strong>
      <p className="gpath"><em>{n.kind === "creative" ? creativeLabel(n.id) : nodeTitle(n)}</em></p>
      <dl className="gkv">
        <div style={{ display: "contents" }}><dt>id</dt><dd>{n.id}</dd></div>
        {n.kind === "shopper" && (
          <div style={{ display: "contents" }}>
            <dt>segment</dt><dd>{segmentName(Number(n.props.segment_id))}</dd>
          </div>
        )}
        {Object.entries(n.props)
          .filter(([k]) => !["offset", "focus", "peer", "segment_id"].includes(k))
          .map(([k, val]) => (
            <div key={k} style={{ display: "contents" }}>
              <dt>{k}</dt>
              <dd>{k === "price_now" || k === "list_price"
                ? fmtUsd(Number(val))
                : k === "valid_to" && Number(val) > 4e15 ? "live" : num(val)}</dd>
            </div>
          ))}
      </dl>
    </>
  );
}

function ExplainPanel({
  graph, explain, loading, stimulus, setStimulus, options, isolated,
  nodesById, creativeLabel,
}: {
  graph: MemoryGraph; explain: ExplainResult | null; loading: boolean;
  stimulus: number | null; setStimulus: (id: number) => void;
  options: { id: number; kind: "creative" | "page" }[];
  isolated: number | null; nodesById: Map<number, GraphNode>;
  creativeLabel: (id: number) => string;
}) {
  if (isolated == null) {
    return (
      <>
        <strong>Explain a decision</strong>
        <p className="gnote">
          Pick a shopper first — in <b>people</b>, or by clicking them on the canvas.
          Explain then lights up only the paths retrieval actually walked for them.
        </p>
      </>
    );
  }
  const who = shopperName(Number(nodesById.get(isolated)?.props.offset));
  const social = explain?.socialMotif;
  return (
    <>
      <strong>Explain a decision</strong>
      <p className="gnote">{who} × which stimulus:</p>
      <select className="gpick" value={stimulus ?? ""}
              onChange={(e) => setStimulus(Number(e.target.value))}>
        {options.map((o) => (
          <option key={o.id} value={o.id}>
            {o.kind === "creative" ? `ad · ${creativeLabel(o.id)}` : `page · ${o.id}`}
          </option>
        ))}
      </select>
      {loading && <p className="gnote">reading get_trace…</p>}
      {!loading && explain && !explain.hops.length && (
        <p className="gnote">
          No motifs — no paths, no knowledge. The mind abstains rather than
          inventing a reason.
        </p>
      )}

      {social && (
        <div className="gmotif social">
          <h4>social_proof</h4>
          <dl className="gkv">
            <div style={{ display: "contents" }}><dt>peer_trust</dt><dd>{num(social.peer_trust)}</dd></div>
            <div style={{ display: "contents" }}><dt>experience</dt><dd>{num(social.experience)}</dd></div>
            <div style={{ display: "contents" }}><dt>valence</dt><dd>{num(social.valence)}</dd></div>
          </dl>
          <div className="gmath">{socialMath(social)}</div>
        </div>
      )}

      {!loading && explain?.hops.length ? (
        <>
          <strong>Paths lit on the canvas</strong>
          {groupHops(explain).map(([rel, hops]) => (
            <div className="gmotif" key={rel}>
              <h4>{rel}</h4>
              {hops.map((h, i) => (
                <p className="gpath" key={i}>
                  <em>{shortLabel(h.from, nodesById, creativeLabel)}</em>{" "}
                  <span className="grel">{h.rel}</span>{" "}
                  <em>{shortLabel(h.to, nodesById, creativeLabel)}</em>
                  {h.edgeId ? "" : " · derived"}
                </p>
              ))}
            </div>
          ))}
        </>
      ) : null}

      <p className="gnote">
        get_trace recomputes against the store as of day {graph.head_tick} (the last
        fully consolidated tick), so this is what retrieval finds today — not a
        replay of the tick the decision was originally made on.
      </p>
    </>
  );
}

function socialMath(m: MotifPayload): string {
  const w = Number(m.peer_trust ?? 0);
  const e = Number(m.experience ?? 0);
  const v = Number(m.valence ?? 0);
  return [
    `valence = clamp01((w·(2·experience − 1) + 1) / 2)`,
    `        = clamp01((${w.toFixed(4)}·${(2 * e - 1).toFixed(4)} + 1) / 2)`,
    `        = ${v.toFixed(4)}`,
    ``,
    `credibility += w_social · (2·valence − 1)`,
    `            = w_social · ${(2 * v - 1).toFixed(4)}`,
  ].join("\n");
}

function groupHops(explain: ExplainResult) {
  const by = new Map<string, ExplainResult["hops"]>();
  for (const h of explain.hops) {
    const key = h.rel;
    if (!by.has(key)) by.set(key, []);
    by.get(key)!.push(h);
  }
  return [...by.entries()];
}

function shortLabel(id: number, nodesById: Map<number, GraphNode>,
                    creativeLabel: (id: number) => string): string {
  const n = nodesById.get(id);
  if (!n) return String(id);
  return n.kind === "creative" ? creativeLabel(id) : nodeTitle(n);
}

function dedupeTrust(edges: GraphEdge[], focus: Set<number>): GraphEdge[] {
  const seen = new Set<string>();
  const out: GraphEdge[] = [];
  for (const e of edges) {
    if (!focus.has(e.source) || !focus.has(e.target)) continue;
    const key = [e.source, e.target].sort((a, b) => a - b).join(":");  // numeric, not lexicographic
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(e);
  }
  return out;
}

const offsetOf = (id: number, focus: GraphNode[]) =>
  Number(focus.find((f) => f.id === id)?.props.offset ?? id % 100000);
