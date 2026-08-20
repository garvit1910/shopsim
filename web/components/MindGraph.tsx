"use client";

/** 05 Mind — the shopper's head, drawn to the reference layout.
 *
 * One shopper's real HydraDB neighbourhood arranged into six lobes inside a
 * left-facing head. The head is a photograph (`/mind/brain.jpg`, the first
 * layer of the SVG); the lobes are FIXED ellipses measured into its skull
 * interior (lib/mindLayout.ts), so they cannot overlap whatever the data
 * does. d3-force runs SYNCHRONOUSLY — a settled diagram, not a live
 * simulation — with one custom force that keeps every node inside its own
 * lobe: it runs last in the tick, predicts where integration would put the
 * node, and bends the velocity so it lands on the ellipse rim instead.
 *
 * Every node and every solid edge came out of the frozen capture; the only
 * synthetic marks are the agent-state stat chips (engine scalars, drawn as
 * chips precisely because they are NOT graph nodes), the lobe hulls, and the
 * labelled inter-lobe connectors — the reference's architecture legend,
 * drawn in their own faint style and named presentation-only by CONTRACT
 * v3.12-draft. Captions are budgeted per lobe so the picture reads; every
 * quiet dot still names itself on hover.
 *
 * The retrieval path (`.rp`) is the trace's motif hops mapped onto stored
 * edges by lib/graph.ts::explainMotifs — the same machinery 04 Graph's
 * Explain mode uses. Animation is pure CSS (stroke-dash flow), so the global
 * prefers-reduced-motion rule freezes it to a static path for free.
 */

import { useEffect, useMemo, useRef } from "react";
import { select } from "d3-selection";
import {
  forceCollide, forceLink, forceSimulation, forceX, forceY,
  type Force, type SimulationLinkDatum, type SimulationNodeDatum,
} from "d3-force";
import type { GraphEdge, GraphNode } from "@/lib/types";
import {
  classifyMind, LOBE_BY_ID, LOBE_CONNECTORS, LOBES, MIND_IMAGE, MIND_VIEWBOX,
  type LobeId,
} from "@/lib/mindLayout";

/** where the ad's signal enters — just in front of the face, eye level */
const ENTRY = { x: 268, y: 470 };
/** the self node: the clear pocket between prefs, goals and agent state */
const SELF = { x: 815, y: 372 };
/** captions per lobe; retrieval-path nodes never count against it */
const CAPTION_BUDGET = 5;

type MindNode = SimulationNodeDatum & {
  id: number;
  lobe: LobeId | null;   // null = self or stimulus (pinned)
  /** rendered caption; undefined = dot only, hover title still names it */
  label?: string;
  kind: string;
  stat?: string;         // agent-state chips carry a value line
  r: number;
};
type MindEdge = SimulationLinkDatum<MindNode> & GraphEdge;

/** How much of the ellipse a node needs around its centre so that its
 * caption (drawn above the dot) or chip stays inside the hull. */
const pad = (n: MindNode): [number, number] =>
  n.kind === "scalar" ? [56, 21]
    : n.label
      ? [Math.min(LOBE_BY_ID[n.lobe!].rx - 24, 6 + n.label.length * 3.2), n.r + 18]
      : [n.r + 4, n.r + 4];

/** Keep each node inside its lobe. Registered LAST: d3-force calls forces in
 * registration order, each mutating vx/vy, then integrates
 * `x += vx *= decay`. Seeing the full tick velocity lets this force bend it
 * so the node lands exactly on the rim, tangential motion intact — zeroing
 * the velocity instead would throw away collide's work and a crowded lobe
 * would never un-overlap. */
function forceLobeEllipse(decay: number): Force<MindNode, MindEdge> {
  let nodes: MindNode[] = [];
  const force = (() => {
    for (const n of nodes) {
      if (n.fx != null || !n.lobe) continue;
      const L = LOBE_BY_ID[n.lobe];
      const [px, py] = pad(n);
      const rx = Math.max(8, L.rx - px), ry = Math.max(8, L.ry - py);
      const nx = (n.x ?? L.cx) + (n.vx ?? 0) * decay;
      const ny = (n.y ?? L.cy) + (n.vy ?? 0) * decay;
      const dx = nx - L.cx, dy = ny - L.cy;
      const k = (dx * dx) / (rx * rx) + (dy * dy) / (ry * ry);
      if (k <= 1) continue;
      const s = 1 / Math.sqrt(k);
      n.vx = (L.cx + dx * s - (n.x ?? L.cx)) / decay;
      n.vy = (L.cy + dy * s - (n.y ?? L.cy)) / decay;
    }
  }) as Force<MindNode, MindEdge>;
  force.initialize = (ns) => { nodes = ns; };
  return force;
}

/** The belt-and-braces pass after the last tick: same ellipse, on x/y. */
function projectInside(n: MindNode) {
  if (n.fx != null || !n.lobe) return;
  const L = LOBE_BY_ID[n.lobe];
  const [px, py] = pad(n);
  const rx = Math.max(8, L.rx - px), ry = Math.max(8, L.ry - py);
  const dx = (n.x ?? L.cx) - L.cx, dy = (n.y ?? L.cy) - L.cy;
  const k = (dx * dx) / (rx * rx) + (dy * dy) / (ry * ry);
  if (k <= 1) return;
  const s = 1 / Math.sqrt(k);
  n.x = L.cx + dx * s;
  n.y = L.cy + dy * s;
}

export default function MindGraph({
  nodes, edges, selfId, selfLabel, stimulusId, stimulusLabel,
  litEdgeIds, hotEdgeIds, softEdgeIds, agentStats,
}: {
  nodes: GraphNode[];
  edges: GraphEdge[];
  selfId: number;
  selfLabel: string;
  stimulusId: number;
  stimulusLabel: string;
  /** the decisive retrieval path — the decision's motif hops on stored edges */
  litEdgeIds: ReadonlySet<string>;
  /** the social hop, kept distinct as in 04 Graph */
  hotEdgeIds: ReadonlySet<string>;
  /** the other candidates retrieval surfaced — drawn quiet, never animated */
  softEdgeIds: ReadonlySet<string>;
  /** engine scalars for the Agent State lobe (label, value) */
  agentStats: { label: string; value: string }[];
}) {
  const svgRef = useRef<SVGSVGElement>(null);

  const mind = useMemo(
    () => classifyMind(nodes, edges, selfId, stimulusId),
    [nodes, edges, selfId, stimulusId]);

  const rebuildKey = useMemo(() => [
    selfId, stimulusId,
    [...mind.keep].join(","),
    edges.map((e) => e.id).join(","),
    [...litEdgeIds].join(","), [...hotEdgeIds].join(","), [...softEdgeIds].join(","),
    agentStats.map((s) => `${s.label}=${s.value}`).join(","),
  ].join("|"), [mind, edges, selfId, stimulusId, litEdgeIds, hotEdgeIds, softEdgeIds, agentStats]);

  useEffect(() => {
    const svgEl = svgRef.current;
    if (!svgEl) return;
    const svg = select(svgEl);
    svg.selectAll("*").remove();

    const nodeById = new Map(nodes.map((n) => [n.id, n]));

    // nodes the retrieval path touches always earn a caption — the path must
    // read as words, whatever the budget says about the quiet field
    const litNodeIds = new Set<number>();
    for (const e of edges) {
      if (litEdgeIds.has(e.id) || hotEdgeIds.has(e.id)) {
        litNodeIds.add(endpoint(e.source));
        litNodeIds.add(endpoint(e.target));
      }
    }

    const degree = new Map<number, number>();
    for (const e of edges) {
      degree.set(e.source, (degree.get(e.source) ?? 0) + 1);
      degree.set(e.target, (degree.get(e.target) ?? 0) + 1);
    }
    const maxDeg = Math.max(1, ...[...degree.values()]);

    // --- the caption budget, per lobe ---------------------------------------
    const captioned = new Set<number>();
    for (const lobe of LOBES) {
      const ids = [...mind.keep].filter((id) => mind.lobeOf.get(id) === lobe.id);
      const lit = ids.filter((id) => litNodeIds.has(id));
      lit.forEach((id) => captioned.add(id));
      ids.filter((id) => !litNodeIds.has(id) && mind.labelOf.has(id))
        .sort((a, b) => (degree.get(b) ?? 0) - (degree.get(a) ?? 0))
        .slice(0, Math.max(0, CAPTION_BUDGET - lit.length))
        .forEach((id) => captioned.add(id));
    }

    // --- sim nodes: real memory + self + stimulus + agent-state chips ------
    const simNodes: MindNode[] = [];
    for (const id of mind.keep) {
      if (id === selfId || id === stimulusId) continue;
      const lobe = mind.lobeOf.get(id);
      const n = nodeById.get(id);
      if (!lobe || !n) continue;
      const caption = captioned.has(id)
        ? mind.labelOf.get(id) ?? n.label ?? String(id) : undefined;
      simNodes.push({
        id, lobe, kind: n.kind, label: caption,
        r: 5 + Math.sqrt((degree.get(id) ?? 1) / maxDeg) * 7,
      });
    }
    agentStats.forEach((s, i) => simNodes.push({
      id: -(i + 1), lobe: "agent", kind: "scalar",
      label: s.label, stat: s.value, r: 15,
    }));
    simNodes.push({
      id: selfId, lobe: null, kind: "self", label: selfLabel, r: 10,
      fx: SELF.x, fy: SELF.y, x: SELF.x, y: SELF.y,
    });
    simNodes.push({
      id: stimulusId, lobe: null, kind: "stimulus", label: stimulusLabel, r: 13,
      fx: ENTRY.x, fy: ENTRY.y, x: ENTRY.x, y: ENTRY.y,
    });
    const byId = new Map(simNodes.map((n) => [n.id, n]));

    const simEdges: MindEdge[] = edges
      .filter((e) => byId.has(e.source) && byId.has(e.target))
      .map((e) => ({ ...e } as MindEdge));

    // seed inside the lobe so the settle is short and local
    for (const n of simNodes) {
      if (n.fx != null || !n.lobe) continue;
      const L = LOBE_BY_ID[n.lobe];
      n.x = L.cx + (hash(n.id) % L.rx) - L.rx / 2;
      n.y = L.cy + (hash(n.id * 7) % L.ry) - L.ry / 2;
    }

    // --- the settled layout ------------------------------------------------
    const sim = forceSimulation<MindNode>(simNodes)
      .force("x", forceX<MindNode>((d) =>
        d.lobe ? LOBE_BY_ID[d.lobe].cx : SELF.x).strength(0.06))
      .force("y", forceY<MindNode>((d) =>
        d.lobe ? LOBE_BY_ID[d.lobe].cy : SELF.y).strength(0.06))
      // a caption is wide, not round: give long ones a bigger circle so two
      // captions in one lobe cannot sit on top of each other
      .force("collide", forceCollide<MindNode>((d) =>
        d.kind === "scalar" ? 58
          : d.label ? Math.max(d.r + 22, 6 + d.label.length * 2.4)
            : d.r + 6)
        .strength(0.9).iterations(2))
      .force("link", forceLink<MindNode, MindEdge>(simEdges)
        .id((d) => d.id).distance(72).strength(0.03))
      .stop();
    // a NEW key, so it really is last in the force map
    sim.force("contain", forceLobeEllipse(1 - sim.velocityDecay()));
    for (let i = 0; i < 300; i += 1) sim.tick();
    for (const n of simNodes) projectInside(n);

    // --- background: the head ------------------------------------------------
    svg.append("g").attr("class", "mindbg").attr("aria-hidden", "true")
      .append("image")
      .attr("href", MIND_IMAGE.href)
      .attr("x", 0).attr("y", 0)
      .attr("width", MIND_IMAGE.w).attr("height", MIND_IMAGE.h)
      .attr("preserveAspectRatio", "none");

    // --- lobe hulls: the fixed regions -------------------------------------
    const hulls = svg.append("g").attr("class", "lobes");
    for (const lobe of LOBES) {
      hulls.append("g").attr("class", `lobe l-${lobe.id}`)
        .style("--lobe" as never, lobe.color)
        .append("ellipse")
        .attr("cx", lobe.cx).attr("cy", lobe.cy)
        .attr("rx", lobe.rx).attr("ry", lobe.ry);
    }

    // --- the architecture legend: labelled inter-lobe connectors -----------
    const conns = svg.append("g").attr("class", "mconns");
    for (const c of LOBE_CONNECTORS) {
      const a = LOBE_BY_ID[c.from], b = LOBE_BY_ID[c.to];
      const x1 = a.cx + (b.cx - a.cx) * 0.3, y1 = a.cy + (b.cy - a.cy) * 0.3;
      const x2 = a.cx + (b.cx - a.cx) * 0.7, y2 = a.cy + (b.cy - a.cy) * 0.7;
      conns.append("line").attr("class", "mconn")
        .attr("x1", x1).attr("y1", y1).attr("x2", x2).attr("y2", y2);
      // a label beside a near-vertical line, above a near-horizontal one
      const vertical = Math.abs(y2 - y1) > Math.abs(x2 - x1);
      const side = (a.cx + b.cx) / 2 < 800 ? 1 : -1;
      conns.append("text").attr("class", "mconnlabel")
        .attr("x", vertical ? (x1 + x2) / 2 + 12 * side : (x1 + x2) / 2)
        .attr("y", vertical ? (y1 + y2) / 2 + 3 : (y1 + y2) / 2 - 5)
        .style("text-anchor", vertical ? (side > 0 ? "start" : "end") : "middle")
        .text(c.label);
    }

    // --- the ad's connector into the head + entry label --------------------
    const VB = MIND_VIEWBOX;
    const entry = svg.append("g");
    entry.append("path").attr("class", "assoc rp")
      .attr("d", `M ${VB.x + 6} ${ENTRY.y} C ${VB.x + 40} ${ENTRY.y} ${ENTRY.x - 50} ${ENTRY.y} ${ENTRY.x - 16} ${ENTRY.y}`);
    entry.append("text").attr("class", "entrylabel")
      .attr("x", VB.x + 6).attr("y", ENTRY.y - 10).text("RETRIEVAL PATH");

    // --- edges (arcs, like 04 Graph) ---------------------------------------
    const lit = new Set(litEdgeIds), hot = new Set(hotEdgeIds), soft = new Set(softEdgeIds);
    const explaining = lit.size > 0 || hot.size > 0 || soft.size > 0;
    const edgeG = svg.append("g").attr("id", "edges");
    const arc = (d: MindEdge) => {
      const a = byId.get(endpoint(d.source))!, b = byId.get(endpoint(d.target))!;
      const dx = (b.x ?? 0) - (a.x ?? 0), dy = (b.y ?? 0) - (a.y ?? 0);
      const dr = Math.sqrt(dx * dx + dy * dy) * 1.6;
      return `M${a.x},${a.y}A${dr},${dr} 0 0,1 ${b.x},${b.y}`;
    };
    const paths = edgeG.selectAll<SVGPathElement, MindEdge>("path")
      .data(simEdges).enter().append("path")
      .attr("class", (d) => {
        const base = d.derived ? "assoc drv" : "assoc";
        if (hot.has(d.id)) return `${base} rp hot`;
        if (lit.has(d.id)) return `${base} rp`;
        // the other candidates retrieval surfaced: present, quiet, social in gold
        if (soft.has(d.id)) {
          return `${base} rp soft${d.rel === "TRUSTS_PERSON" ? " hot" : ""}`;
        }
        return explaining ? `${base} dim` : base;
      })
      .attr("d", arc);
    paths.append("title").text((d) => `${d.rel}${d.count > 1 ? ` ×${d.count}` : ""}`);
    // paint order: soft candidates, then the decisive path, then its social hop
    paths.filter((d) => soft.has(d.id)).each(function () { this.parentNode?.appendChild(this); });
    paths.filter((d) => lit.has(d.id)).each(function () { this.parentNode?.appendChild(this); });
    paths.filter((d) => hot.has(d.id)).each(function () { this.parentNode?.appendChild(this); });
    // name the decisive hops — only those long enough to carry a word
    paths.filter((d) => lit.has(d.id) || hot.has(d.id))
      .each(function (d) {
        const len = this.getTotalLength();
        if (len < 70) return;
        const mid = this.getPointAtLength(len / 2);
        edgeG.append("text").attr("class", `relabel${hot.has(d.id) ? " hotlabel" : ""}`)
          .attr("x", mid.x).attr("y", mid.y - 5).text(d.rel);
      });

    // --- nodes -------------------------------------------------------------
    const nodeG = svg.append("g").attr("id", "nodes");
    for (const n of simNodes) {
      const color = n.lobe ? LOBE_BY_ID[n.lobe].color
        : n.kind === "stimulus" ? "#8ffff8" : "var(--accent)";
      const g = nodeG.append("g")
        .attr("class", `mnode k-${n.kind}`)
        .attr("transform", `translate(${n.x},${n.y})`);
      if (n.kind === "scalar") {
        g.append("rect")
          .attr("x", -52).attr("y", -17).attr("width", 104).attr("height", 34)
          .attr("rx", 7);
        g.append("text").attr("class", "statlabel").attr("y", -3).text(n.label ?? "");
        g.append("text").attr("class", "statvalue").attr("y", 11).text(n.stat ?? "");
      } else {
        g.append("circle").attr("r", n.r).attr("fill", color);
        if (n.label) {
          g.append("text").attr("class", "nlabel")
            // the stimulus sits under the entry label, so its name goes below
            .attr("y", n.kind === "stimulus" ? n.r + 16 : -n.r - 5)
            .text(n.label);
        }
      }
      const real = nodeById.get(n.id);
      if (real) {
        g.append("title")
          .text(`${real.kind} · ${mind.labelOf.get(n.id) ?? real.label ?? n.id}`);
      }
    }

    // lobe titles paint over everything — they name the regions, and a name
    // buried under a hub defeats the layout
    const titles = svg.append("g").attr("class", "lobetitles");
    for (const lobe of LOBES) {
      const x = lobe.titleAnchor === "start" ? lobe.cx - lobe.rx
        : lobe.titleAnchor === "end" ? lobe.cx + lobe.rx : lobe.cx;
      titles.append("text").attr("class", "lobelabel")
        .style("--lobe" as never, lobe.color)
        .style("text-anchor", lobe.titleAnchor)
        .attr("x", x).attr("y", lobe.cy - lobe.ry - 9)
        .text(lobe.title);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rebuildKey]);

  return (
    <svg
      ref={svgRef}
      viewBox={`${MIND_VIEWBOX.x} ${MIND_VIEWBOX.y} ${MIND_VIEWBOX.w} ${MIND_VIEWBOX.h}`}
      preserveAspectRatio="xMidYMid meet"
      role="img"
      aria-label="The shopper's memory graph, arranged by lobe inside a head, with the active retrieval path lit"
    />
  );
}

const endpoint = (end: unknown): number =>
  typeof end === "object" && end !== null ? (end as { id: number }).id : Number(end);

const hash = (n: number) => {
  let x = Math.abs(Math.trunc(n)) + 7;
  x = ((x >> 16) ^ x) * 0x45d9f3b;
  x = ((x >> 16) ^ x) * 0x45d9f3b;
  return Math.abs((x >> 16) ^ x);
};
