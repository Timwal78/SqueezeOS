import Link from "next/link";
import { TickerList } from "@/components/TickerList";
import { Leaderboard } from "@/components/Leaderboard";

export default function Home() {
  return (
    <div className="space-y-12">
      <section className="space-y-4">
        <h1 className="text-4xl font-bold tracking-tight">
          A market for <span className="text-accent">earnings truth</span>.
        </h1>
        <p className="max-w-2xl text-muted">
          Analysts publish EPS &amp; revenue estimates. xDEO scores every one against the
          real SEC EDGAR filing and compounds an on-chain reputation. Agents discover and pay
          per estimate via x402 (USDC on Base). No accounts. No custody. Not investment advice.
        </p>
        <div className="flex gap-3">
          <Link
            href="/analysts"
            className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-ink hover:opacity-90"
          >
            View leaderboard
          </Link>
          <a
            href={`${process.env.NEXT_PUBLIC_XDEO_API ?? ""}/api/v1/openapi.json`}
            className="rounded-lg border border-edge px-4 py-2 text-sm text-muted hover:text-white"
          >
            API for agents
          </a>
        </div>
      </section>

      <section className="space-y-4">
        <h2 className="text-xl font-semibold">Tracked tickers</h2>
        <TickerList />
      </section>

      <section className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-semibold">Top analysts</h2>
          <Link href="/analysts" className="text-sm text-muted hover:text-white">
            Full leaderboard →
          </Link>
        </div>
        <Leaderboard limit={10} compact />
      </section>
    </div>
  );
}
