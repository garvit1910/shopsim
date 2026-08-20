export const fmtInt = (n: number | null | undefined) =>
  n == null ? "—" : n.toLocaleString("en-US");

export const fmtPct = (n: number | null | undefined, digits = 2) =>
  n == null ? "—" : (100 * n).toFixed(digits) + "%";

export const fmtUsd = (n: number | null | undefined) =>
  n == null ? "—" : "$" + n.toFixed(2);

export const fmtW = (n: number | null | undefined) =>
  n == null ? "—" : n.toFixed(3);

/** Deterministic display alias for a shopper offset — cosmetic only; the
 * offset is the identity. Same table as the design mock. */
const NAMES = ["Asha","Leo","Maya","Tom","Zoe","Ivan","Nina","Raj","Mia","Kai",
  "Ana","Ben","Lena","Omar","Ivy","Sam","Rosa","Finn","Ada","Noor","Eli","Tara",
  "Hugo","Sana","Max","Lila","Owen","Duaa","Jack","Emmy","Ravi","Cleo","Nate",
  "Isla","Yara","Cole","Ruth","Dev","June","Amir"];

export const shopperName = (offset: number) => NAMES[offset % NAMES.length];
export const padOffset = (offset: number) => "#" + String(offset).padStart(4, "0");
export const shopperLabel = (offset: number) => `${shopperName(offset)} ${padOffset(offset)}`;

/** Segment ids are stable across every personas file (only the budgets differ
 * between the value-tier and premium catalogs), so the names travel with the
 * id. Source: fixtures/demo-brand/personas.json. */
const SEGMENT_NAMES: Record<number, string> = {
  1001: "eco_enthusiast", 1002: "performance_athlete", 1003: "bargain_hunter",
  1004: "comfort_seeker", 1005: "style_conscious", 1006: "casual_browser",
  1007: "trail_adventurer", 1008: "marathon_trainer", 1009: "ortho_comfort",
  1010: "fashion_forward", 1011: "brand_skeptic", 1012: "deal_stacker",
  1013: "quality_investor",
};
export const segmentName = (id: number | null | undefined) =>
  id == null ? "—" : SEGMENT_NAMES[id] ?? `segment ${id}`;

/** The demo catalog's brands (engine/shopsim/contracts/ids.py names them in
 * comments; nothing in the graph stores a brand name). Anything else falls
 * back to its id rather than inventing a label. */
const BRAND_NAMES: Record<number, string> = {
  6001: "ShoeCo", 6002: "TrailForge", 6003: "UrbanStride",
  6100: "Nisolo",
};
export const brandName = (id: number) => BRAND_NAMES[id] ?? `Brand ${id}`;
