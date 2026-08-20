"use client";

/** The 04 Graph canvas — a shopper cohort's HydraDB neighbourhood, drawn with
 * d3-force.
 *
 * Adapted from AlexVanK's force-directed pen (codepen.io/AlexVanK/pen/dygjEWP).
 * Everything that gives the pen its look is kept as it was written: the same
 * simulation (link distance, forceCenter offset by +60, charge -150, forceX/Y,
 * alphaTarget 1), the same elliptical-arc `step()`, the same drag with a
 * `pinned` class on release and dblclick to unpin, and the same encodings —
 * radius `3 + weight * 2`, fill `hsl(h, 94%, 99 - weight * 7)`, label offset
 * `-10 + weight * -2`. `weight` is the node's edge count, exactly as the pen
 * computes it, so size and saturation still mean "how connected is this".
 *
 * D3 draws; it does not invent. Every node and edge here came out of
 * /runs/{id}/memory-graph, which reads the store and adds nothing. The only
 * things this file decides are geometry and colour.
 *
 * Two adaptations the data forces:
 *   - the pen's two edge classes carry our meaning. `.link` (solid) is a
 *     relationship really stored in HydraDB; `.linkish` (dashed) is one the
 *     engine derives and never writes — the NOT_SHOWN_BY hop inside an
 *     expectation_violation, and the social-proof inference. The pen's own
 *     legend copy ("direct" vs "indirect") survives almost unchanged.
 *   - hue splits three ways instead of one, because a worldview has parts a
 *     board-game graph does not: cyan for the objective world, green for the
 *     people, gold for the mind. The lightness and radius formulas — the
 *     pen's actual signature — are untouched.
 */

import { useEffect, useMemo, useRef } from "react";
import { drag as d3drag } from "d3-drag";
import { select } from "d3-selection";
import {
  forceCenter, forceLink, forceManyBody, forceSimulation, forceX, forceY,
  type Simulation, type SimulationLinkDatum, type SimulationNodeDatum,
} from "d3-force";
import type { GraphEdge, GraphNode } from "@/lib/types";
import { brandName, shopperName } from "@/lib/format";

export type SimNode = SimulationNodeDatum & GraphNode & {
  name: string;      // the pen keys links on `name`
  weight?: number;
  fixed?: boolean;
};
export type SimEdge = SimulationLinkDatum<SimNode> & GraphEdge;

/** Hue per family. Cyan 202 is the pen's own; the other two are ShopSim's
 * --accent and --gold, read as hues so the pen's lightness formula still
 * applies unchanged. */
const HUE: Record<string, number> = {
  shopper: 152,   // the people        (--accent green)
  belief: 42,     // the subjective    (--gold)
  concept: 202,   // the objective world, and everything below it
  category: 42,   // a need's target reads as part of the mind
  brand: 202,
  product: 202,
  creative: 202,
  page: 202,
  aspect: 42,
  anchor: 202,
};

export interface GraphSelection {
  node?: SimNode;
  edge?: SimEdge;
}

export default function MemoryGraph({
  nodes, edges, litEdgeIds, hotEdgeIds, focusOffsets, dimmedNodeIds,
  onSelect, onHover,
}: {
  nodes: GraphNode[];
  edges: GraphEdge[];
  /** Explain mode: the motif paths to burn in (accent). */
  litEdgeIds: ReadonlySet<string>;
  /** The social hop specifically, so the headline path reads at a glance. */
  hotEdgeIds: ReadonlySet<string>;
  focusOffsets: number[];
  /** Nodes outside the current inspection — faded, never removed. */
  dimmedNodeIds: ReadonlySet<number> | null;
  onSelect: (sel: GraphSelection | null) => void;
  onHover: (sel: GraphSelection | null) => void;
}) {
  const svgRef = useRef<SVGSVGElement>(null);
  const simRef = useRef<Simulation<SimNode, SimEdge> | null>(null);
  /** Layout positions survive a day-scrub redraw: a node that was on screen
   * yesterday must not jump when today's edges arrive. */
  const posRef = useRef(new Map<number, { x: number; y: number; fx?: number | null; fy?: number | null }>());
  const cbRef = useRef({ onSelect, onHover });
  cbRef.current = { onSelect, onHover };

  /** Rebuild only when the topology changes — not on every hover. */
  const topology = useMemo(
    () => `${nodes.map((n) => n.id).join(",")}|${edges.map((e) => e.id).join(",")}`,
    [nodes, edges]);

  useEffect(() => {
    const svgEl = svgRef.current;
    if (!svgEl) return;
    const svg = select(svgEl);
    svg.selectAll("*").remove();
    if (!nodes.length) return;

    const { width, height } = svgEl.getBoundingClientRect();

    // --- the pen: parse into node objects, restoring known positions -------
    const simNodes: SimNode[] = nodes.map((n) => {
      const prev = posRef.current.get(n.id);
      return {
        ...n, name: String(n.id),
        x: prev?.x ?? width / 2 + (Math.random() - 0.5) * 200,
        y: prev?.y ?? height / 2 + (Math.random() - 0.5) * 200,
        fx: prev?.fx ?? null, fy: prev?.fy ?? null,
      };
    });
    const byName = new Map(simNodes.map((n) => [n.name, n]));
    const simEdges: SimEdge[] = edges
      .filter((e) => byName.has(String(e.source)) && byName.has(String(e.target)))
      .map((e) => ({ ...e, source: String(e.source), target: String(e.target) } as unknown as SimEdge));

    // --- the pen's simulation ---------------------------------------------
    // distance eases down as the graph grows so a 30-node worldview and a
    // 90-node one both fill the canvas; 200 stays the base the pen chose.
    const distance = Math.max(70, Math.min(200, 1400 / Math.sqrt(simNodes.length)));
    const simulation = forceSimulation<SimNode>()
      .nodes(simNodes)
      .force("link", forceLink<SimNode, SimEdge>(simEdges)
        .id((d) => d.name)
        .distance(distance))
      .force("center", forceCenter(width / 2, height / 2 + 60))
      .force("charge", forceManyBody().strength(-150))
      // the pen's forceX/forceY default to the origin, which on a small pen
      // canvas reads as gentle centring; at this size it drags the whole graph
      // into the top-left corner, so they are pointed at the same centre
      // forceCenter uses.
      .force("x", forceX(width / 2).strength(0.04))
      .force("y", forceY(height / 2 + 60).strength(0.04))
      // The pen pins alphaTarget at 1, so its simulation never cools — on a
      // small graph that reads as pleasant perpetual drift. At this size it
      // means the nodes are still moving when you reach for one, and every
      // interaction the exhibit promises (click a shopper, hover an edge,
      // grab a node) fights a moving target. Same forces, same resting
      // layout — it is just allowed to come to rest.
      .alphaTarget(1);
    simRef.current = simulation;
    const settle = window.setTimeout(() => simulation.alphaTarget(0), 1800);

    // --- edge and node elements -------------------------------------------
    const path = svg.append("g").attr("id", "edges")
      .selectAll<SVGPathElement, SimEdge>("path")
      .data(simEdges).enter().append("path");
    const circle = svg.append("g").attr("id", "nodes")
      .selectAll<SVGGElement, SimNode>("circle")
      .data(simNodes).enter().append("g");

    // --- the pen's step(): curved arcs + node transforms -------------------
    const step = () => {
      path.attr("d", (d) => {
        const s = d.source as SimNode, t = d.target as SimNode;
        const dx = (t.x ?? 0) - (s.x ?? 0);
        const dy = (t.y ?? 0) - (s.y ?? 0);
        const dr = Math.sqrt(dx * dx + dy * dy);
        return `M${s.x},${s.y}A${dr},${dr} 0 0,1 ${t.x},${t.y}`;
      });
      circle.attr("transform", (d) => `translate(${d.x},${d.y})`);
    };
    simulation.on("tick", step);

    // --- the pen's drag: pin on release, dblclick to unpin -----------------
    const drag = d3drag<SVGGElement, SimNode>()
      .subject((e) => e.sourceEvent.target)
      .on("start", (e, d) => {
        if (!e.active) simulation.alphaTarget(0.3).restart();
        d.fx = d.x; d.fy = d.y;
      })
      .on("drag", (e, d) => { d.fx = e.x; d.fy = e.y; })
      .on("end", (e, d) => {
        if (!e.active) simulation.alphaTarget(0);  // cool down, per above
        d.fx = d.x; d.fy = d.y;
        (e.subject as Element)?.setAttribute?.("class", "pinned");
        posRef.current.set(d.id, { x: d.x ?? 0, y: d.y ?? 0, fx: d.fx, fy: d.fy });
      });

    const dragreset = (e: MouseEvent, d: SimNode) => {
      d.fixed = false; d.fx = null; d.fy = null;
      (e.target as Element)?.setAttribute?.("class", "");
      posRef.current.set(d.id, { x: d.x ?? 0, y: d.y ?? 0, fx: null, fy: null });
      simulation.alphaTarget(0.3).restart();
      window.setTimeout(() => simulation.alphaTarget(0), 600);
    };

    // --- draw --------------------------------------------------------------
    path
      .attr("class", (d) => edgeClass(d))
      .on("mouseenter", (_e, d) => cbRef.current.onHover({ edge: d }))
      .on("mouseleave", () => cbRef.current.onHover(null))
      .on("click", (e, d) => { e.stopPropagation(); cbRef.current.onSelect({ edge: d }); })
      .append("title").text((d) => edgeTitle(d));

    // The pen encodes connectivity twice, in radius and in saturation, with
    // `3 + weight * 2` and `99 - weight * 7`. Those constants are calibrated
    // to ITS graph, where the busiest node had about seven edges. A worldview
    // hub here carries thirty-plus, which drives the radius past 60px and the
    // lightness straight to black — the encoding stops discriminating exactly
    // where it matters. So the formulas are kept verbatim and the INPUT is
    // rescaled: the busiest node in view maps to the pen's busiest, and every
    // node keeps its position in the ordering.
    const PEN_MAX_WEIGHT = 7;
    const maxWeight = Math.max(
      1, ...simNodes.map((n) => simEdges.reduce(
        (acc, l) => acc + (l.source === n || l.target === n ? 1 : 0), 0)));
    // sqrt, not linear: a shopper hub carries ten times a concept's edges, so
    // a linear rescale pins every concept at the bottom of the range and the
    // objective world goes uniformly small and near-white. sqrt keeps the
    // pen's claim intact — more edges is still strictly bigger and stronger —
    // while leaving the middle of the distribution legible.
    const penWeight = (d: SimNode) => {
      d.weight = path.filter((l) => l.source === d || l.target === d).size();
      return Math.sqrt(d.weight / maxWeight) * PEN_MAX_WEIGHT;
    };

    circle
      .attr("class", (d) => nodeClass(d, focusOffsets))
      .call(drag)
      .on("dblclick", (e: MouseEvent, d: SimNode) => dragreset(e, d))
      .on("mouseenter", (_e: MouseEvent, d: SimNode) => cbRef.current.onHover({ node: d }))
      .on("mouseleave", () => cbRef.current.onHover(null))
      .on("click", (e: MouseEvent, d: SimNode) => {
        e.stopPropagation();
        cbRef.current.onSelect({ node: d });
      })
      .append("circle")
      // the pen's formulas, on the rescaled weight
      .attr("r", (d) => {
        const w = penWeight(d);
        return (d.kind === "shopper" ? 6 : 3) + w * 2;
      })
      .attr("fill", (d) => `hsl(${HUE[d.kind] ?? 202},94%,${99 - penWeight(d) * 7}%)`);

    circle.append("text")
      .attr("y", (d) => -10 + Math.sqrt((d.weight ?? 0) / maxWeight) * PEN_MAX_WEIGHT * -2)
      .attr("text-anchor", "middle")
      .text((d) => nodeLabel(d));

    svg.on("click", () => cbRef.current.onSelect(null));

    return () => {
      window.clearTimeout(settle);
      // Remember where everything ended up. The day scrub changes the topology
      // and therefore rebuilds, and a node that was on screen yesterday must
      // not jump when today's edges arrive — the graph should look like it
      // grew, not like it was redrawn.
      for (const n of simNodes) {
        posRef.current.set(n.id, { x: n.x ?? 0, y: n.y ?? 0, fx: n.fx, fy: n.fy });
      }
      simulation.stop();
      simRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [topology]);

  /** Fade / highlight without rebuilding the layout — the simulation keeps
   * running underneath, so classes can change every hover for free. */
  useEffect(() => {
    const svgEl = svgRef.current;
    if (!svgEl) return;
    // Explain is a claim about which paths mattered, so everything the trace
    // did NOT walk drops back — otherwise the lit path is one thread inside a
    // hundred and the claim is unreadable.
    const explaining = litEdgeIds.size > 0 || hotEdgeIds.size > 0;
    const paths = select(svgEl).select("#edges")
      .selectAll<SVGPathElement, SimEdge>("path")
      .attr("class", (d) => {
        const base = edgeClass(d);
        if (hotEdgeIds.has(d.id)) return `${base} hot`;
        if (litEdgeIds.has(d.id)) return `${base} lit`;
        if (explaining) return `${base} faded`;
        const s = d.source as SimNode, t = d.target as SimNode;
        if (dimmedNodeIds && (dimmedNodeIds.has(s.id) || dimmedNodeIds.has(t.id))) {
          return `${base} faded`;
        }
        return base;
      });
    // SVG paints in document order, so a lit path sitting early in the list
    // would be overdrawn by every grey edge after it. Raise the walked ones.
    paths.filter((d) => litEdgeIds.has(d.id)).each(function () { this.parentNode?.appendChild(this); });
    paths.filter((d) => hotEdgeIds.has(d.id)).each(function () { this.parentNode?.appendChild(this); });
    select(svgEl).select("#nodes").selectAll<SVGGElement, SimNode>("g")
      .attr("class", (d) => {
        const base = nodeClass(d, focusOffsets);
        if (dimmedNodeIds?.has(d.id)) return `${base} faded`;
        return base;
      });
  }, [litEdgeIds, hotEdgeIds, dimmedNodeIds, focusOffsets, topology]);

  return <svg ref={svgRef} />;
}

/** Shoppers are drawn as people, not ids. The alias table is cosmetic and
 * deterministic per offset (lib/format.ts) — the offset stays the identity and
 * is always one hover away in the aside. */
function nodeLabel(d: SimNode): string {
  if (d.kind === "shopper") return shopperName(Number(d.props.offset));
  if (d.kind === "brand") return brandName(d.id);
  return d.label ?? String(d.id);
}

/** `person` is a focus shopper — the three the exhibit is about. `peer` is
 * someone one of them trusts who is not in the triple: really there, and the
 * reason a friend's purchase is visible, but not the subject. */
function nodeClass(d: SimNode, focusOffsets: number[]): string {
  if (d.kind !== "shopper") return "";
  return focusOffsets.includes(Number(d.props.offset)) ? "person" : "person peer";
}

/** Solid where HydraDB really stores the relationship, dashed where the
 * engine derives it — the pen's own direct/indirect distinction, carrying our
 * meaning. TRUSTS_PERSON gets extra weight because it is the exhibit. */
function edgeClass(d: SimEdge): string {
  if (d.rel === "TRUSTS_PERSON") return "link social";
  return d.derived ? "linkish" : "link";
}

function edgeTitle(d: SimEdge): string {
  const v = d.versions[d.versions.length - 1] ?? {};
  const props = Object.entries(v)
    .filter(([k]) => k !== "t" && k !== "valid_to" && k !== "run")
    .map(([k, val]) => `${k}=${typeof val === "number" ? round(val) : val}`)
    .join(" · ");
  const n = d.count > 1 ? ` ×${d.count}` : "";
  return `${d.rel}${n}${props ? ` — ${props}` : ""}`;
}

export const round = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(4).replace(/0+$/, ""));
