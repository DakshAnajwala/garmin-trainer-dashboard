// Validated palette (see dataviz skill reference) — single source of truth
// for every chart and status color in the app.
export const colors = {
  blue: "#2a78d6",
  blueDark: "#184f95",
  blueTint: "#cde2fb",
  violet: "#4a3aa7",
  muted: "#898781",
  grid: "rgba(128,128,128,0.15)",
  good: "#0ca30c",
  warning: "#fab219",
  serious: "#ec835a",
  critical: "#d03b3b",
  surfaceLight: "#fcfcfb",
  surfaceDark: "#1a1a19",
};

// Form/TSB zones — ASSUMPTION: these numeric boundaries are my best-effort
// reconstruction of intervals.icu's 5-zone Form banding (the athlete named
// the zones and colors; the exact cutoffs aren't independently verified).
export const FORM_ZONES = [
  { max: -30, label: "Overreaching", color: "#d03b3b" },
  { max: -10, label: "Grey zone", color: "#898781" },
  { max: 5, label: "Maintaining", color: "#0ca30c" },
  { max: 25, label: "Fresh", color: "#2a78d6" },
  { max: Infinity, label: "Transition", color: "#fab219" },
];

export function formZoneFor(value) {
  return FORM_ZONES.find((z) => value <= z.max) ?? FORM_ZONES[FORM_ZONES.length - 1];
}

export function statusColorForScore(score) {
  if (score == null) return colors.muted;
  if (score < 25) return colors.critical;
  if (score < 50) return colors.warning;
  if (score < 75) return colors.blue;
  return colors.good;
}
