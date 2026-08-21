"use client";

/** 05 Mind — the side panels of the reference layout.
 *
 * Left: the current ad (the real creative, its image and PERCEIVED claims —
 * AdCard's honesty rule: headline/body are what a human reads, claims are
 * what the simulation reacts to) and the pinned shopper's identity card.
 * Right: Appraisal and Decision.
 *
 * The Appraisal panel keeps the reference's six rows, each sourced from its
 * real layer of one decision-preview: preference_fit and goal_fit are MOTIFS
 * (they feed relevance), trust_belief and price_gap are SCALARS (they feed
 * credibility and the price term), fatigue and expectation_alignment are the
 * engine's appraisal dims. The Decision panel shows P(click) from the ad
 * decision and reach probabilities for the landing-page gates — products of
 * the engine's sequential gate probabilities, multiplied client-side and
 * labelled as such. IGNORE is 1 − P(click), derived, and says so.
 */

import { proxied } from "@/lib/api";
import type { CreativeCard, DecisionPreview, GraphNode } from "@/lib/types";
import { fmtUsd, segmentName, shopperLabel } from "@/lib/format";

const pct = (n: number) => `${Math.round(n * 100)}%`;

const num = (v: unknown): number | null => (typeof v === "number" ? v : null);
const rec = (v: unknown): Record<string, unknown> | null =>
  v != null && typeof v === "object" && !Array.isArray(v)
    ? (v as Record<string, unknown>) : null;

/** appraise()'s _strongest: the motif of this type with max strength. */
function strongest(preview: DecisionPreview, type: string) {
  let best: { strength?: number | null;[k: string]: unknown } | null = null;
  for (const m of preview.motifs) {
    if (m.type !== type) continue;
    if (!best || (m.strength ?? 0) > (best.strength ?? 0)) best = m;
  }
  return best;
}

export interface AppraisalRow {
  key: string;
  value: number | null;   // null = abstention (unknown brand)
  color: string;
  /** where the number really lives in the engine */
  source: "motif" | "scalar" | "dim";
  signed?: boolean;
}

export function appraisalRows(preview: DecisionPreview): AppraisalRow[] {
  const pref = strongest(preview, "preference_fit");
  const goal = strongest(preview, "goal_fit");
  const trust = rec(preview.scalars.trust_belief);
  return [
    { key: "preference_fit", source: "motif", color: "#35c26a",
      value: pref ? (num(pref.strength) ?? 0) * (num(pref.recency) ?? 1) : 0 },
    { key: "goal_fit", source: "motif", color: "#35c26a",
      value: goal ? (num(goal.strength) ?? 0) * (num(goal.urgency) ?? 0) : 0 },
    { key: "trust_belief", source: "scalar", color: "#4b9df5",
      value: trust ? num(trust.value) : null },
    { key: "fatigue", source: "dim", color: "#9085e9",
      value: preview.appraisal.brand_message_fatigue },
    { key: "expectation_alignment", source: "dim", color: "#6da7ec",
      value: preview.appraisal.expectation_alignment },
    { key: "price_gap", source: "scalar", color: "#ef7f4a", signed: true,
      value: num(preview.scalars.current_price_gap) },
  ];
}

export function AppraisalPanel({ preview }: { preview: DecisionPreview }) {
  const rows = appraisalRows(preview);
  return (
    <div className="mpanel appraisal">
      <div className="mph">⚖ Appraisal</div>
      {rows.map((r) => (
        <div className="barrow" key={r.key}>
          <i className="dot" style={{ background: r.color }} />
          <span className="bl">{r.key}</span>
          <span className={`bt${r.signed ? " signed" : ""}`}>
            {r.value != null && !r.signed && (
              <i className="bf" style={{
                width: `${Math.round(Math.min(1, Math.max(0, r.value)) * 100)}%`,
                background: r.color }} />
            )}
            {r.value != null && r.signed && (
              <i className="bf" style={{
                left: r.value >= 0 ? "50%" : `${50 + Math.max(-0.5, r.value / 2) * 100}%`,
                width: `${Math.min(50, Math.abs(r.value / 2) * 100)}%`,
                background: r.color }} />
            )}
          </span>
          <span className="bv">
            {r.value == null ? "—" : r.signed ? r.value.toFixed(2) : r.value.toFixed(2)}
          </span>
        </div>
      ))}
      <div className="maxis"><span>Low</span><span>Medium</span><span>High</span></div>
      {rows[2].value == null && (
        <div className="mnote">trust_belief — no belief held: unknown brand, the engine abstains</div>
      )}
      <div className="mnote">
        preference_fit · goal_fit are motifs, trust_belief · price_gap are
        scalars, fatigue · expectation_alignment are appraisal dims — all from
        this ad&apos;s decision preview
      </div>
    </div>
  );
}

export interface DecisionRow {
  key: string;
  p: number | null;
  derived: boolean;
}

export function decisionRows(
  preview: DecisionPreview, pagePreview: DecisionPreview | null,
): DecisionRow[] {
  const click = preview.probabilities.CLICK ?? null;
  const browse = click != null && pagePreview
    ? click * (pagePreview.probabilities.BROWSE ?? 0) : null;
  const cart = browse != null && pagePreview
    ? browse * (pagePreview.probabilities.CART ?? 0) : null;
  const buy = cart != null && pagePreview
    ? cart * (pagePreview.probabilities.BUY ?? 0) : null;
  return [
    { key: "Ignore", p: click == null ? null : 1 - click, derived: true },
    { key: "Click", p: click, derived: false },
    { key: "Browse", p: browse, derived: true },
    { key: "Cart", p: cart, derived: true },
    { key: "Buy", p: buy, derived: true },
  ];
}

export function DecisionPanel({ preview, pagePreview }: {
  preview: DecisionPreview;
  pagePreview: DecisionPreview | null;
}) {
  const rows = decisionRows(preview, pagePreview);
  const winner = rows.reduce(
    (best, r) => (r.p != null && (best?.p == null || r.p > best.p) ? r : best),
    null as DecisionRow | null);
  return (
    <div className="mpanel decision">
      <div className="mph">⑂ Decision</div>
      {rows.map((r) => (
        <div className={`barrow${winner?.key === r.key ? " win" : ""}`} key={r.key}>
          <span className="bl">{r.key}</span>
          <span className="bt">
            {r.p != null && (
              <i className="bf" style={{ width: `${Math.round(r.p * 100)}%` }} />
            )}
          </span>
          <span className="bv">{r.p == null ? "—" : pct(r.p)}</span>
        </div>
      ))}
      <div className="maxis"><span>0%</span><span>50%</span><span>100%</span></div>
      <div className="mcaption">Probability of Action</div>
      <div className="mnote">
        click is the ad gate; browse · cart · buy are reach — products of the
        landing page&apos;s sequential gate probabilities; ignore = 1 − P(click)
      </div>
    </div>
  );
}

export function StimulusCard({ card }: { card: CreativeCard | null }) {
  if (!card) {
    return (
      <div className="mpanel stimulus">
        <div className="mph">Current Ad / Stimulus</div>
        <div className="mnote">ad card unavailable — the catalog could not be read</div>
      </div>
    );
  }
  const claims = card.perceived?.claims ?? card.authored_claims;
  const discount = Math.max(
    0, ...(card.perceived?.claimed_discounts ?? []).map((d) => d.claimed_pct));
  const offer = card.offers[0];
  return (
    <div className="mpanel stimulus">
      <div className="mph">Current Ad / Stimulus</div>
      {card.image_url && (
        <img src={proxied(card.image_url)} alt={card.headline || card.name} />
      )}
      <div className="mhead">{card.headline || card.name}</div>
      <div className="msub">
        {card.brand_name} · {card.name}
        {offer && offer.list_price > 0 && <> · {fmtUsd(offer.list_price)}</>}
      </div>
      <div className="mchipslabel">Claims / Signals</div>
      <div className="mchips">
        {claims.map((c) => (
          <span className="chip" key={c.concept} title={`strength ${c.strength}`}>
            {c.concept.toLowerCase().replace(/_/g, " ")}
          </span>
        ))}
        {discount > 0 && <span className="chip sale">{pct(discount)} off</span>}
      </div>
      {card.perceived && (
        <div className="mnote">
          claims perceived {card.perceived.from_image ? "from the image" : "from the copy"} · {card.perceived.model}
        </div>
      )}
    </div>
  );
}

export function ShopperCard({
  offset, shopperId, segmentId, runId, headTick, ticks, preview, needLabel,
}: {
  offset: number;
  shopperId: number;
  segmentId: number | null;
  runId: string;
  headTick: number;
  ticks: number;
  preview: DecisionPreview;
  needLabel: string | null;
}) {
  const budget = num(preview.scalars.budget_left);
  const exposures = num(preview.scalars.exposures_72h);
  const cart = Array.isArray(preview.scalars.cart)
    ? preview.scalars.cart.length : 0;
  return (
    <div className="mpanel shopper">
      <div className="mph">Shopper</div>
      <dl className="mkv">
        <dt>Shopper</dt>
        <dd>{shopperLabel(offset)} <span className="mid">{shopperId}</span></dd>
        <dt>Segment</dt>
        <dd>{segmentId == null ? "—" : segmentName(segmentId)}</dd>
        <dt>Mind state</dt>
        <dd>frozen · {runId} · day {headTick} of {ticks}</dd>
        <dt>Goal</dt>
        <dd>{needLabel ?? "no active need"}</dd>
        <dt>Context</dt>
        <dd>
          {budget != null ? `${fmtUsd(budget)} left` : "—"}
          {exposures != null && <> · {exposures} seen /72h</>}
          {` · cart ${cart}`}
        </dd>
      </dl>
    </div>
  );
}

/** used by the shopper card: the active need's category label off the graph */
export function needLabelFrom(
  preview: DecisionPreview, nodesById: Map<number, GraphNode>,
): string | null {
  const need = rec(preview.scalars.active_need);
  if (!need) return null;
  const cat = num(need.category);
  const name = cat != null ? nodesById.get(cat)?.label ?? `category ${cat}` : "?";
  const strength = num(need.strength);
  return `NEEDS ${name}${strength != null ? ` · strength ${strength.toFixed(2)}` : ""}`;
}
