/** 05 Mind — pure derivations for the Shopper Mind brain layout.
 *
 * Takes the pinned shopper's frozen neighbourhood and sorts every node into
 * one of the reference design's six lobes. Classification only READS stored
 * edges (which relationship connects the shopper to the node, and what the
 * PREFERS version history says about its source); it never invents structure.
 * The lobes themselves are presentation — a spatial grouping of real nodes —
 * and the page's legend says so.
 */

import type { GraphEdge, GraphNode } from "./types";
import { brandName, shopperName } from "./format";
import { localMemory } from "./graph";

export type LobeId =
  | "persona" | "agent" | "prefs" | "goals" | "episodic" | "beliefs";

/** The head artwork the lobes are measured against — a left-facing profile,
 * face at the left, on rgb(1,2,8). Every lobe ellipse below is in ITS pixel
 * space, placed inside the skull interior measured row by row from the
 * image (glow edge: y330 spans x 370–1192 at the widest, nose tip x 319 at
 * y530, chin x 385 at y700, neck from y810). */
export const MIND_IMAGE = { href: "/mind/brain.jpg", w: 1672, h: 941 } as const;

/** The canvas crop: ~100 px in front of the nose for the incoming retrieval
 * path, the right edge just past the back of the head. */
export const MIND_VIEWBOX = { x: 170, y: 0, w: 1100, h: 941 } as const;

export interface LobeSpec {
  id: LobeId;
  title: string;
  /** fixed ellipse inside the head, in MIND_IMAGE pixels */
  cx: number;
  cy: number;
  rx: number;
  ry: number;
  /** where the title sits on the ellipse's top edge, so a vertical connector
   * at cx passes beside the words rather than through them */
  titleAnchor: "start" | "middle" | "end";
  /** lobe hue — one per family, echoing the reference's color coding */
  color: string;
}

/** Fixed regions following the reference image: persona top-front, agent
 * state top-back, preferences mid-front, goals mid-back, episodic low-front,
 * beliefs/social low-back. Every pair sits ≥30 px apart and ≥25 px inside
 * the glow edge, so the hulls cannot overlap whatever the nodes do. */
export const LOBES: LobeSpec[] = [
  { id: "persona", title: "Persona", cx: 600, cy: 220, rx: 150, ry: 92,
    titleAnchor: "middle", color: "#4b9df5" },
  { id: "agent", title: "Agent State", cx: 945, cy: 212, rx: 160, ry: 100,
    titleAnchor: "middle", color: "#8ffff8" },
  { id: "prefs", title: "Preferences & Habits", cx: 620, cy: 474, rx: 170, ry: 108,
    titleAnchor: "start", color: "#9085e9" },
  { id: "goals", title: "Goals / Active Needs", cx: 1000, cy: 452, rx: 150, ry: 105,
    titleAnchor: "end", color: "#35c26a" },
  { id: "episodic", title: "Episodic Memory", cx: 620, cy: 706, rx: 170, ry: 92,
    titleAnchor: "start", color: "#d9a01f" },
  { id: "beliefs", title: "Beliefs / Social Context", cx: 950, cy: 678, rx: 130, ry: 92,
    titleAnchor: "end", color: "#6da7ec" },
];

export const LOBE_BY_ID: Record<LobeId, LobeSpec> = Object.fromEntries(
  LOBES.map((l) => [l.id, l])) as Record<LobeId, LobeSpec>;

/** The reference's inter-lobe architecture legend. Presentation only — these
 * are NOT stored relationships (CONTRACT v3.12-draft names them a static
 * legend), which is why they render in their own faint style. */
export const LOBE_CONNECTORS: { from: LobeId; to: LobeId; label: string }[] = [
  { from: "persona", to: "agent", label: "INFLUENCES" },
  { from: "agent", to: "goals", label: "AFFECTS" },
  { from: "persona", to: "prefs", label: "SHAPES" },
  { from: "prefs", to: "goals", label: "NEEDS" },
  { from: "episodic", to: "prefs", label: "INFORMS" },
  { from: "episodic", to: "beliefs", label: "INFORMS" },
  { from: "beliefs", to: "goals", label: "SHAPED BY" },
];

/** Strongest-first: when a shopper holds several episodic edges to one node
 * (SAW and CLICKED and BOUGHT), the node reads as the deepest engagement. */
const EPISODIC_RANK = [
  "BOUGHT", "EXPERIENCED", "CARTED", "ABANDONED", "CLICKED",
  "BROWSED", "BOUNCED", "VISITED", "SAW", "PRICE_SEEN", "REFERENCE_PRICE",
];

export interface MindClassified {
  /** every node the canvas draws (the pinned shopper's local memory) */
  keep: Set<number>;
  /** node -> lobe, for everything except the self node and the stimulus */
  lobeOf: Map<number, LobeId>;
  /** display label, reference-style: "PREFERS eco_friendly", "SAW Ad …" */
  labelOf: Map<number, string>;
}

export function classifyMind(
  nodes: GraphNode[], edges: GraphEdge[], selfId: number, stimulusId: number,
): MindClassified {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const shopperIds = new Set(
    nodes.filter((n) => n.kind === "shopper").map((n) => n.id));

  const keep = localMemory(edges, selfId, shopperIds);
  keep.add(stimulusId);
  // plumbing anchors (pricebook/catalog) say nothing about the mind
  for (const id of [...keep]) {
    if (byId.get(id)?.kind === "anchor") keep.delete(id);
  }

  // self -> node relationships, node -> self included (rels are directed
  // outward from the shopper, but stay safe about it)
  const selfRels = new Map<number, Set<string>>();
  const peerRels = new Map<number, Set<string>>();
  for (const e of edges) {
    if (e.source === selfId && keep.has(e.target)) {
      let s = selfRels.get(e.target);
      if (!s) selfRels.set(e.target, (s = new Set()));
      s.add(e.rel);
    } else if (e.target === selfId && keep.has(e.source)) {
      let s = selfRels.get(e.source);
      if (!s) selfRels.set(e.source, (s = new Set()));
      s.add(e.rel);
    } else if (shopperIds.has(e.source) && e.source !== selfId
               && keep.has(e.target)) {
      let s = peerRels.get(e.target);
      if (!s) peerRels.set(e.target, (s = new Set()));
      s.add(e.rel);
    }
  }

  /** every version of the self's PREFERS edge to `id` is a seeded prior */
  const priorOnly = (id: number): boolean => {
    const e = edges.find(
      (x) => x.rel === "PREFERS" && x.source === selfId && x.target === id);
    if (!e) return false;
    return e.versions.every((v) => v.source === "prior" || v.source == null);
  };

  const lobeOf = new Map<number, LobeId>();
  const labelOf = new Map<number, string>();

  for (const id of keep) {
    if (id === selfId || id === stimulusId) continue;
    const n = byId.get(id);
    if (!n) continue;
    const rels = selfRels.get(id) ?? new Set<string>();

    if (n.kind === "belief" || n.kind === "aspect") {
      lobeOf.set(id, "beliefs");
      if (n.kind === "belief") {
        const aspect = String(n.props.aspect ?? "belief").toUpperCase();
        const about = Number(n.props.about_id);
        labelOf.set(id, Number.isFinite(about)
          ? `${aspect} ${brandName(about)}` : aspect);
      } else {
        labelOf.set(id, n.label ?? String(id));
      }
      continue;
    }
    if (n.kind === "shopper") {
      lobeOf.set(id, "beliefs");
      labelOf.set(id, `TRUSTS ${shopperName(Number(n.props.offset))}`);
      continue;
    }
    if (rels.has("NEEDS")) {
      lobeOf.set(id, "goals");
      labelOf.set(id, `NEEDS ${n.label ?? id}`);
      continue;
    }
    if (rels.has("PREFERS") || rels.has("HABIT")) {
      const habitOnly = rels.has("HABIT") && !rels.has("PREFERS");
      const name = n.kind === "brand" ? brandName(id) : n.label ?? String(id);
      if (habitOnly) {
        lobeOf.set(id, "prefs");
        labelOf.set(id, `HABIT ${name}`);
      } else if (priorOnly(id)) {
        // seeded taste — who they arrived as, not what the market taught them
        lobeOf.set(id, "persona");
        labelOf.set(id, `PREFERS ${name}`);
      } else {
        lobeOf.set(id, "prefs");
        labelOf.set(id, `PREFERS ${name}`);
      }
      continue;
    }
    const episodic = EPISODIC_RANK.find((r) => rels.has(r));
    if (episodic) {
      lobeOf.set(id, "episodic");
      // only deep engagement earns a caption — a lobe of thirty "SAW …"
      // labels is unreadable; the shallow dots keep their hover title
      if (EPISODIC_RANK.indexOf(episodic) <= EPISODIC_RANK.indexOf("CLICKED")) {
        labelOf.set(id, `${episodic.replace("_", " ")} ${
          n.kind === "brand" ? brandName(id) : n.label ?? id}`);
      }
      continue;
    }
    if (rels.has("EXPECTS")) {
      lobeOf.set(id, "beliefs");
      labelOf.set(id, `EXPECTS ${n.label ?? id}`);
      continue;
    }
    const peer = peerRels.get(id);
    if (peer?.has("BOUGHT") || peer?.has("EXPERIENCED")) {
      lobeOf.set(id, "beliefs");
      labelOf.set(id, `PEER BOUGHT ${n.label ?? id}`);
      continue;
    }
  }

  // objective-closure leftovers (a concept only an ad claims, a brand only a
  // product points at): join the lobe most of their classified neighbours
  // are in, episodic as the last resort — they arrived through the world.
  for (const id of keep) {
    if (id === selfId || id === stimulusId || lobeOf.has(id)) continue;
    const n = byId.get(id);
    if (!n) continue;
    const votes = new Map<LobeId, number>();
    for (const e of edges) {
      const other = e.source === id ? e.target : e.target === id ? e.source : null;
      if (other == null) continue;
      const lobe = lobeOf.get(other);
      if (lobe) votes.set(lobe, (votes.get(lobe) ?? 0) + 1);
    }
    const best = [...votes.entries()].sort((a, b) => b[1] - a[1])[0]?.[0];
    lobeOf.set(id, best ?? "episodic");
    // closure furniture stays unlabelled (hover title only) — the captions
    // belong to the shopper's own relationships
  }

  return { keep, lobeOf, labelOf };
}
