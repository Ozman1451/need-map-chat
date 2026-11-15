export const C = {
  bg: "#0A0A0F",
  surface: "#12121A",
  border: "#23232F",
  text: "#EDEDF2",
  muted: "#8A8A9A",
  magenta: "#E94BA8",
  saffron: "#F5A524",
};

/** 12 cluster colours, all readable on #0A0A0F, ordered so neighbours differ in hue. */
export const PALETTE = [
  "#E94BA8", // magenta
  "#F5A524", // saffron
  "#4CC9F0", // sky
  "#7BE495", // mint
  "#A78BFA", // violet
  "#FF7A59", // coral
  "#2DD4BF", // teal
  "#FACC15", // yellow
  "#60A5FA", // blue
  "#F472B6", // pink
  "#A3E635", // lime
  "#FDBA74", // peach
];

/** Stable colour per cluster id: C3 → palette[2]; sub-clusters (C3.2) share the parent hue. */
export function clusterColor(id: string | null | undefined): string {
  const m = /(\d+)/.exec(String(id ?? ""));
  if (!m) return C.muted;
  return PALETTE[(parseInt(m[1], 10) - 1 + PALETTE.length) % PALETTE.length];
}

/** Mix a hex colour toward white (t ∈ 0..1). */
export function lighten(hex: string, t: number): string {
  const n = parseInt(hex.slice(1), 16);
  const ch = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => Math.round(v + (255 - v) * t));
  return `#${ch.map((v) => v.toString(16).padStart(2, "0")).join("")}`;
}

export const FONT = "var(--font-geist-sans), ui-sans-serif, system-ui, sans-serif";
export const MONO = "var(--font-geist-mono), ui-monospace, monospace";

export const tooltip = {
  backgroundColor: "rgba(18,18,26,0.96)",
  borderColor: C.border,
  borderWidth: 1,
  padding: [8, 10],
  textStyle: { color: C.text, fontSize: 12, fontFamily: "Geist, sans-serif" },
  extraCssText: "border-radius:10px;box-shadow:0 8px 30px rgba(0,0,0,.5);max-width:320px;white-space:normal;",
};

export const axis = {
  axisLine: { lineStyle: { color: C.border } },
  axisTick: { show: false },
  axisLabel: { color: C.muted, fontSize: 11 },
  splitLine: { lineStyle: { color: "rgba(35,35,47,0.6)" } },
  nameTextStyle: { color: C.muted, fontSize: 11 },
};

export const base = {
  backgroundColor: "transparent",
  textStyle: { fontFamily: "Geist, ui-sans-serif, system-ui, sans-serif", color: C.text },
  animationDuration: 700,
  animationEasing: "cubicOut",
};

export const pct = (v: number, d = 0) => `${(v * 100).toFixed(d)}%`;
