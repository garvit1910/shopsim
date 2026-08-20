/** Client-side graph derivations for 04 Graph.
 *
 * The engine hands over the topology plus every edge's version history and
 * lets the client own time (see engine/shopsim/hydramem/memgraph.py). That
 * makes the day scrub a pure function — no refetch per day — and it is the
 * same as-of rule the Inspector already applies to preference chains.
 */

import type { GraphEdge, GraphNode, MemoryGraph, MotifPayload } from "./types";

/** HydraDB's open-ended `valid_to`. */
export const SENTINEL = 9007199254740991;

export const dayToEpoch = (g: Pick<MemoryGraph, "t0" | "tick_seconds">, day: number) =>
  g.t0 + day * g.tick_seconds;

/** The version of an edge in force at `asOf`, or null if it was not yet
 * written / already superseded. `static` edges (the objective closure and
 * TRUSTS_PERSON, which is seeded before tick 0) are always in force. */
export function versionAt(e: GraphEdge, asOf: number) {
  if (e.time === "static") return e.versions[e.versions.length - 1] ?? {};
  if (e.time === "event") {
    const seen = e.versions.filter((v) => (v.t ?? 0) <= asOf);
    return seen.length ? seen[seen.length - 1] : null;
  }
  for (const v of e.versions) {
    if ((v.t ?? 0) <= asOf && asOf < (v.valid_to ?? SENTINEL)) return v;
  }
  return null;
}

/** How many times an event edge had fired by `asOf` — the count the aside
 * shows, which must not run ahead of the day being viewed. */
export const occurrencesBy = (e: GraphEdge, asOf: number) =>
  e.versions.filter((v) => (v.t ?? 0) <= asOf).length;

export interface GraphAtDay {
  nodes: GraphNode[];
  edges: GraphEdge[];
  /** Nodes that exist in the payload but have no live edge on this day. */
  hiddenNodeIds: Set<number>;
}

/** The graph as it stood on one day. Nodes with no live edge drop out, which
 * is what makes a worldview visibly grow: on day 0 a shopper is their seeded
 * priors, by day N they carry ads, pages, prices, beliefs and a purchase. */
export function graphAtDay(g: MemoryGraph, day: number): GraphAtDay {
  const asOf = dayToEpoch(g, day);
  const edges = g.edges.filter((e) => versionAt(e, asOf) !== null);
  const live = new Set<number>();
  for (const e of edges) { live.add(e.source); live.add(e.target); }
  const nodes = g.nodes.filter((n) => live.has(n.id));
  const hiddenNodeIds = new Set(g.nodes.filter((n) => !live.has(n.id)).map((n) => n.id));
  return { nodes, edges, hiddenNodeIds };
}

/** d3.forceLink REPLACES an edge's `source`/`target` ids with references to
 * the node objects, in place. Anything reading an edge that has been through
 * the simulation has to cope with both shapes. */
export const endpointId = (end: unknown): number =>
  typeof end === "object" && end !== null ? Number((end as { id: number }).id) : Number(end);

/** Undirected adjacency over a set of edges. */
export function adjacency(edges: GraphEdge[]): Map<number, Set<number>> {
  const adj = new Map<number, Set<number>>();
  const add = (a: number, b: number) => {
    let s = adj.get(a);
    if (!s) adj.set(a, (s = new Set()));
    s.add(b);
  };
  for (const e of edges) { add(e.source, e.target); add(e.target, e.source); }
  return adj;
}

/** One shopper's local memory: themselves, everything they touch, and — one
 * hop further — what their trusted friends did with the products already in
 * view. The extra hop is the point of the exhibit; without it "inspect Maya"
 * would hide the very path that explains her. */
export function localMemory(
  edges: GraphEdge[], shopperId: number, shopperIds: Set<number>,
): Set<number> {
  const keep = new Set<number>([shopperId]);
  for (const e of edges) {
    if (e.source === shopperId) keep.add(e.target);
    if (e.target === shopperId) keep.add(e.source);
  }
  const friends = new Set(
    edges.filter((e) => e.rel === "TRUSTS_PERSON" && e.source === shopperId)
      .map((e) => e.target));
  for (const e of edges) {
    if (!friends.has(e.source) || !keep.has(e.target)) continue;
    keep.add(e.source);
  }
  // belief satellites hang off belief nodes, not off the shopper
  for (const e of edges) {
    if (keep.has(e.source) && !shopperIds.has(e.source)) keep.add(e.target);
  }
  return keep;
}

export interface ExplainHop {
  from: number; rel: string; to: number;
  edgeId: string | null;   // null when the hop is derived, not stored
}

export interface ExplainResult {
  litEdgeIds: Set<string>;
  hotEdgeIds: Set<string>;
  hops: ExplainHop[];
  /** Hops the engine derives but never writes — drawn dashed, per the pen's
   * direct/indirect distinction. */
  derivedEdges: GraphEdge[];
  socialMotif: MotifPayload | null;
}

/** Map a trace's motif paths onto edges that are actually on screen.
 *
 * A motif path alternates node, relationship, node. Some hops are walked
 * against their stored direction — brand_semantic_fatigue ends
 * `concept CLAIMS stimulus` while the store holds `creative CLAIMS concept` —
 * so each hop is looked up both ways before being called derived. */
export function explainMotifs(
  motifs: MotifPayload[], edges: GraphEdge[], nodeIds: Set<number>,
): ExplainResult {
  const index = new Set(edges.map((e) => e.id));
  const lit = new Set<string>();
  const hot = new Set<string>();
  const hops: ExplainHop[] = [];
  const derived = new Map<string, GraphEdge>();
  let socialMotif: MotifPayload | null = null;

  for (const m of motifs) {
    const path = m.path ?? [];
    const isSocial = m.type === "social_proof";
    if (isSocial) socialMotif = m;
    for (let i = 0; i + 2 < path.length; i += 2) {   // node, rel, node, rel, node
      const a = path[i], rel = path[i + 1], b = path[i + 2];
      if (typeof a !== "number" || typeof b !== "number" || typeof rel !== "string") continue;
      const fwd = `${rel}:${a}:${b}`;
      const rev = `${rel}:${b}:${a}`;
      const hit = index.has(fwd) ? fwd : index.has(rev) ? rev : null;
      hops.push({ from: a, rel, to: b, edgeId: hit });
      if (hit) {
        (isSocial ? hot : lit).add(hit);
      } else if (nodeIds.has(a) && nodeIds.has(b)) {
        // both ends are on screen but the store holds no such edge: this is
        // an inference (NOT_SHOWN_BY, or a hop across a version boundary).
        const id = `${rel}:${a}:${b}`;
        derived.set(id, {
          id, source: a, target: b, rel, family: "subjective",
          time: "static", derived: true, owner: a, count: 1,
          versions: [{ inferred: true }],
        });
        (isSocial ? hot : lit).add(id);
      }
    }
  }

  // the friend's satisfaction is where social_proof's valence comes from, so
  // light it even though the motif path stops at BOUGHT
  if (socialMotif) {
    const path = socialMotif.path ?? [];
    const peer = path[2], product = path[4];
    if (typeof peer === "number" && typeof product === "number") {
      const id = `EXPERIENCED:${peer}:${product}`;
      if (index.has(id)) hot.add(id);
    }
  }
  return { litEdgeIds: lit, hotEdgeIds: hot, hops, derivedEdges: [...derived.values()], socialMotif };
}

/** Stimuli this shopper actually met, newest first — the only ones an Explain
 * run can honestly be asked about. Pages as well as ads: a page decision is
 * where expectation_violation fires, and that motif's NOT_SHOWN_BY hop is the
 * one relationship the engine derives and never writes — i.e. the only thing
 * the canvas's dashed "indirect" class exists to draw. */
export function metStimuli(edges: GraphEdge[], shopperId: number) {
  const rows = edges
    .filter((e) => (e.rel === "SAW" || e.rel === "VISITED") && e.source === shopperId)
    .sort((a, b) => (lastT(b) ?? 0) - (lastT(a) ?? 0));
  return rows.map((e) => ({
    id: e.target,
    kind: e.rel === "SAW" ? ("creative" as const) : ("page" as const),
  }));
}

const lastT = (e: GraphEdge) => e.versions[e.versions.length - 1]?.t;
