"use client";

import { useEffect, useState } from "react";
import { api, type VerdictResponse } from "@/lib/api";
import { TierBadge } from "./TierBadge";
import { Loading, ErrorBox, Dash } from "./StateBlock";

function shortAddr(a: string) {
  return a.length > 12 ? `${a.slice(0, 6)}…${a.slice(-4)}` : a;
}

export function VerdictView({ filingId }: { filingId: string }) {
  const [data, setData] = useState<VerdictResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .verdict(filingId)
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(String(e.message ?? e)));
    return () => {
      alive = false;
    };
  }, [filingId]);

  if (error) return <ErrorBox error={error} />;
  if (!data) return <Loading label="Loading verdict…" />;

  const f = data.filing;
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">
          Verdict · ${f.ticker} {f.fiscal_period} {f.fiscal_year}
        </h1>
        <p className="text-muted">
          {f.form} filed {f.filed_at} · actual EPS{" "}
          <span className="font-semibold text-white">
            {f.eps_actual !== null ? `$${f.eps_actual.toFixed(2)}` : <Dash />}
          </span>
        </p>
      </div>

      <div className="overflow-hidden rounded-xl border border-edge">
        <table className="w-full text-left text-sm">
          <thead className="bg-panel text-muted">
            <tr>
              <th className="px-4 py-3">#</th>
              <th className="px-4 py-3">Analyst</th>
              <th className="px-4 py-3">Tier</th>
              <th className="px-4 py-3 text-right">Predicted</th>
              <th className="px-4 py-3 text-right">Score</th>
              <th className="px-4 py-3">Badge</th>
            </tr>
          </thead>
          <tbody>
            {data.verdict.map((e) => (
              <tr key={e.analyst} className="border-t border-edge/60">
                <td className="px-4 py-3 text-muted">{e.rank}</td>
                <td className="px-4 py-3 font-mono">{e.handle || shortAddr(e.analyst)}</td>
                <td className="px-4 py-3"><TierBadge tier={e.tier} /></td>
                <td className="px-4 py-3 text-right">${e.predicted.toFixed(2)}</td>
                <td className="px-4 py-3 text-right font-semibold text-accent">
                  {e.score.toFixed(1)}
                </td>
                <td className="px-4 py-3">
                  {e.badge === "NOSTRADAMUS" && <span className="text-gold">🔮 Nostradamus</span>}
                  {e.badge === "RIP" && <span className="text-red-400">🪦 RIP</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
