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
