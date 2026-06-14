"use client";

import { useEffect, useState } from "react";
import { api, type AnalystRow } from "@/lib/api";
import { TierBadge } from "./TierBadge";
import { Loading, ErrorBox, Empty } from "./StateBlock";

function shortAddr(a: string) {
  return a.length > 12 ? `${a.slice(0, 6)}…${a.slice(-4)}` : a;
}

export function Leaderboard({ limit = 25, compact = false }: { limit?: number; compact?: boolean }) {
  const [rows, setRows] = useState<AnalystRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .analysts(limit)
      .then((r) => alive && setRows(r.analysts))
      .catch((e) => alive && setError(String(e.message ?? e)));
    return () => {
      alive = false;
    };
  }, [limit]);

  if (error) return <ErrorBox error={error} />;
  if (!rows) return <Loading label="Loading leaderboard…" />;
  if (rows.length === 0) return <Empty label="No ranked analysts yet" />;

  return (
    <div className="overflow-hidden rounded-xl border border-edge">
      <table className="w-full text-left text-sm">
        <thead className="bg-panel text-muted">
          <tr>
            <th className="px-4 py-3 font-medium">#</th>
            <th className="px-4 py-3 font-medium">Analyst</th>
            <th className="px-4 py-3 font-medium">Tier</th>
            <th className="px-4 py-3 text-right font-medium">Reputation</th>
            {!compact && <th className="px-4 py-3 text-right font-medium">Accuracy</th>}
            {!compact && <th className="px-4 py-3 text-right font-medium">Scored</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((a) => (
            <tr key={a.address} className="border-t border-edge/60 hover:bg-panel/50">
              <td className="px-4 py-3 text-muted">{a.rank}</td>
              <td className="px-4 py-3 font-mono">{a.handle || shortAddr(a.address)}</td>
              <td className="px-4 py-3"><TierBadge tier={a.tier} /></td>
              <td className="px-4 py-3 text-right font-semibold text-accent">
                {a.reputation.toFixed(1)}
              </td>
              {!compact && (
                <td className="px-4 py-3 text-right">{(a.accuracy * 100).toFixed(1)}%</td>
              )}
              {!compact && <td className="px-4 py-3 text-right text-muted">{a.scored_count}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
