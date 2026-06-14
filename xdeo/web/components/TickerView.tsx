"use client";

import { useEffect, useState } from "react";
import { api, API_BASE, type TickerRow, type Consensus } from "@/lib/api";
import { Loading, ErrorBox, Dash } from "./StateBlock";

type Data = TickerRow & { consensus: Consensus };

export function TickerView({ ticker }: { ticker: string }) {
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .ticker(ticker)
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(String(e.message ?? e)));
    return () => {
      alive = false;
    };
  }, [ticker]);

  if (error) return <ErrorBox error={error} />;
  if (!data) return <Loading label={`Loading $${ticker}…`} />;

  const c = data.consensus;
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold">${data.ticker}</h1>
        <p className="text-muted">
          {data.name} · CIK {data.cik}
        </p>
      </div>

      <section className="rounded-xl border border-edge bg-panel p-6">
        <h2 className="mb-3 text-sm uppercase tracking-wide text-muted">
          Free consensus (reputation-weighted)
        </h2>
        {c.available ? (
          <div className="flex flex-wrap items-end gap-8">
            <Stat label={`EPS · ${c.period}`} value={`$${c.reputation_weighted_eps?.toFixed(2)}`} big />
            <Stat label="Simple mean" value={`$${c.mean_eps?.toFixed(2)}`} />
            <Stat label="Analysts" value={String(c.n)} />
          </div>
        ) : (
          <p className="text-muted">Awaiting estimates for this ticker.</p>
        )}
      </section>

      <section className="rounded-xl border border-edge p-6">
        <h2 className="mb-2 text-sm uppercase tracking-wide text-muted">Full estimate index</h2>
        <p className="text-sm text-muted">
          Individual analyst estimates and theses are x402-gated. Agents fetch them at{" "}
          <code className="text-white">
            GET /api/v1/tickers/{data.ticker}/estimates
          </code>{" "}
          ($0.01 USDC) and per-estimate theses at analyst-set prices.
        </p>
        <a
          href={`${API_BASE}/api/v1/tickers/${data.ticker}/estimates`}
          className="mt-3 inline-block text-sm text-accent hover:underline"
        >
          Endpoint →
        </a>
      </section>
    </div>
  );
}

function Stat({ label, value, big }: { label: string; value: string | null; big?: boolean }) {
  return (
    <div>
      <div className="text-xs text-muted">{label}</div>
      <div className={big ? "text-4xl font-extrabold text-accent" : "text-xl font-semibold"}>
        {value ?? <Dash />}
      </div>
    </div>
  );
}
