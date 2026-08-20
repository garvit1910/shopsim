"use client";

/** The Mind page's current-ad selection — the one piece of Studio state that
 * outlives Studio. Written whenever an ad is picked there (the grid toggle
 * and the lightbox's SELECT both route through Studio's toggle()), mirrored
 * to localStorage so the pinned mind keeps its stimulus across reloads. The
 * Mind page treats it as a hint: an id the frozen capture carries no preview
 * for falls back to the capture's own demo_stimuli[0]. */

import { create } from "zustand";

const KEY = "shopsim.mind.creative";

const initial = (): number | null => {
  if (typeof window === "undefined") return null;
  const n = Number(window.localStorage.getItem(KEY));
  return Number.isFinite(n) && n > 0 ? n : null;
};

export const useMindSel = create<{ creativeId: number | null }>(() => ({
  creativeId: initial(),
}));

export function selectMindAd(creativeId: number) {
  useMindSel.setState({ creativeId });
  try {
    window.localStorage.setItem(KEY, String(creativeId));
  } catch {
    /* storage unavailable (private mode) — session-only selection is fine */
  }
}
