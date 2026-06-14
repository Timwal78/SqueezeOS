// Shareable estimate cards. Renders a 1200x630 SVG (no external deps; works on
// Workers). Every estimate becomes a marketing event (spec §SHARING MECHANISMS).
// SVG is returned directly; downstream can rasterize to PNG via an image service.

export interface CardData {
  ticker: string;
  handle: string;
  predicted: number;
  metric: string;
  confidence: number;
  reputation: number;
  accuracy: number;
  tier: string;
  period: string;
}

function esc(s: string): string {
  return s.replace(/[<>&'"]/g, (ch) =>
    ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", "'": "&apos;", '"': "&quot;" })[ch]!
  );
}

export function estimateCardSvg(d: CardData): string {
  const conf = Math.round(d.confidence * 100);
  const acc = (d.accuracy * 100).toFixed(1);
  const pred = d.metric === "revenue"
    ? `$${(d.predicted / 1e9).toFixed(2)}B`
    : `$${d.predicted.toFixed(2)}`;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#0a0e1a"/>
      <stop offset="1" stop-color="#101935"/>
    </linearGradient>
  </defs>
  <rect width="1200" height="630" fill="url(#bg)"/>
  <text x="64" y="96" fill="#7c8db5" font-family="monospace" font-size="28">xDEO · Decentralized Earnings Oracle</text>
  <text x="64" y="210" fill="#ffffff" font-family="sans-serif" font-size="92" font-weight="700">$${esc(d.ticker)}</text>
  <text x="64" y="270" fill="#9fb3d9" font-family="sans-serif" font-size="34">${esc(d.metric.toUpperCase())} · ${esc(d.period)}</text>
  <text x="64" y="400" fill="#39FF14" font-family="sans-serif" font-size="120" font-weight="800">${esc(pred)}</text>
  <text x="64" y="450" fill="#7c8db5" font-family="sans-serif" font-size="30">${conf}% confidence</text>
  <text x="64" y="560" fill="#ffffff" font-family="sans-serif" font-size="36">🔮 ${esc(d.handle)}</text>
  <text x="64" y="600" fill="#FFD700" font-family="sans-serif" font-size="28">${esc(d.tier)} · ${acc}% accuracy · rep ${d.reputation.toFixed(1)}</text>
  <text x="900" y="600" fill="#5a6b8c" font-family="monospace" font-size="24">scored vs SEC EDGAR</text>
</svg>`;
}
