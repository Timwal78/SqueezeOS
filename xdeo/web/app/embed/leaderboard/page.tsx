import Link from "next/link";
import { Leaderboard } from "@/components/Leaderboard";

// Bare, iframe-friendly leaderboard widget for partner blogs/Substacks/Discords.
// Renders outside the (site) chrome. Partners earn affiliate fees on traffic via
// the X-AGENT-ID header on any x402 calls their readers make.
export default function EmbedLeaderboard() {
  return (
    <div className="p-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs font-bold tracking-tight">
          x<span className="text-accent">DEO</span> · top analysts
        </span>
        <Link href="/" className="text-[10px] text-muted hover:text-white">
          powered by xDEO ↗
        </Link>
      </div>
      <Leaderboard limit={10} compact />
    </div>
  );
}
