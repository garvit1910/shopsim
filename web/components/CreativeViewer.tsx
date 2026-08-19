"use client";

/** The creative, actually seen.
 *
 * The studio grid shows every ad cropped to a 104px strip with its copy and
 * provenance suppressed — you could pick five ads for a market without once
 * reading what any of them said. The eye on a card opens this: the same
 * `AdCard`, rendered `full`, so the image is uncropped and the body copy,
 * claim strengths, offer and perception provenance all come along for free —
 * no second rendering of an ad to drift out of sync with the first.
 */

import { useEffect, useRef } from "react";
import type { CreativeCard } from "@/lib/types";
import AdCard from "@/components/AdCard";

export default function CreativeViewer({
  cards, index, onIndex, onClose, selected, onToggle,
}: {
  cards: CreativeCard[];
  index: number;
  onIndex: (i: number) => void;
  onClose: () => void;
  selected: boolean;
  onToggle: () => void;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const card = cards[index];

  useEffect(() => { closeRef.current?.focus(); }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { onClose(); return; }
      if (e.key === "ArrowLeft" && index > 0) onIndex(index - 1);
      if (e.key === "ArrowRight" && index < cards.length - 1) onIndex(index + 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [index, cards.length, onIndex, onClose]);

  if (!card) return null;

  return (
    <div className="adview" role="dialog" aria-modal="true" aria-label="Creative viewer"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="adview-panel">
        <div className="adview-head">
          <span>CREATIVE {card.creative_id} · {card.name}</span>
          <span className="adview-count">{index + 1} / {cards.length}</span>
          <button ref={closeRef} className="adview-x" onClick={onClose} aria-label="Close">×</button>
        </div>

        <AdCard card={card} full selected={selected} />

        <div className="adview-foot">
          <button className={`btn ${selected ? "primary" : ""}`} onClick={onToggle}>
            {selected ? "SELECTED — REMOVE" : "SELECT THIS AD"}
          </button>
          <div className="adview-nav">
            <button className="adnav" onClick={() => onIndex(index - 1)}
              disabled={index === 0} aria-label="Previous creative">‹</button>
            <button className="adnav" onClick={() => onIndex(index + 1)}
              disabled={index >= cards.length - 1} aria-label="Next creative">›</button>
          </div>
        </div>
      </div>
    </div>
  );
}
