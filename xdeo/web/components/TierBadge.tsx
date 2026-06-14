import type { Tier } from "@/lib/api";

const STYLES: Record<Tier, string> = {
  OBSERVER: "bg-edge text-muted",
  ANALYST: "bg-blue-500/15 text-blue-300",
  SAGE: "bg-purple-500/15 text-purple-300",
  ORACLE: "bg-accent/15 text-accent",
  LEGEND: "bg-gold/15 text-gold"
};

export function TierBadge({ tier }: { tier: Tier }) {
  return (
    <span
      className={`rounded px-2 py-0.5 text-xs font-semibold tracking-wide ${STYLES[tier] ?? STYLES.OBSERVER}`}
    >
      {tier}
    </span>
  );
}
