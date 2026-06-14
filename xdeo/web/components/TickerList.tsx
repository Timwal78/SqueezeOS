"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api, type TickerRow } from "@/lib/api";
import { Loading, ErrorBox, Empty } from "./StateBlock";

export function TickerList() {
  const [rows, setRows] = useState<TickerRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");

  useEffect(() => {
    let alive = true;
    api
      .tickers()
      .then((r) => alive && setRows(r.tickers))
      .catch((e) => alive && setError(String(e.message ?? e)));
    return () => {
      alive = false;
    };
  }, []);

  const filtered = useMemo(() => {
    if (!rows) return [];
    const needle = q.trim().toUpperCase();
    if (!needle) return rows;
    return rows.filter(
      (t) => t.ticker.includes(needle) || t.name.toUpperCase().includes(needle)
    );
  }, [rows, q]);

  if (error) return <ErrorBox error={error} />;
  if (!rows) return <Loading label="Loading tickers…" />;

  return (
    <div>
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Search ticker or company…"
        className="mb-4 w-full rounded-lg border border-edge bg-panel px-4 py-2 text-sm outline-none focus:border-accent"
      />
      {filtered.length === 0 ? (
        <Empty label="No tracked tickers yet — submit an estimate to add one." />
      ) : (
        <ul className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {filtered.map((t) => (
            <li key={t.ticker}>
              <Link
                href={`/t/${t.ticker}`}
                className="block rounded-lg border border-edge bg-panel px-4 py-3 hover:border-accent"
              >
                <div className="font-bold">${t.ticker}</div>
                <div className="truncate text-xs text-muted">{t.name}</div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
