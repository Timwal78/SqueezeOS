import { useEffect, useState } from "react";
import { useWorkspace } from "@/store/workspaceStore";

export function StatusBar() {
  const [now, setNow] = useState(() => new Date());
  const [apiOk, setApiOk] = useState<boolean | null>(null);
  const tabs = useWorkspace((s) => s.tabs);

  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    let alive = true;
    const ping = async () => {
      try {
        const r = await fetch("/api/v1/equity/price/quote?symbol=SPY&provider=tradier");
        if (alive) setApiOk(r.ok);
      } catch { if (alive) setApiOk(false); }
    };
    ping();
    const t = setInterval(ping, 5000);  // 5s — always-connected institutional feed
    return () => { alive = false; clearInterval(t); };
  }, []);

  return (
    <div className="h-6 px-3 flex items-center justify-between border-t border-term-border bg-term-panel2 text-[10px] uppercase tracking-[0.18em] text-term-muted">
      <div className="flex items-center gap-5">
        <span className="flex items-center gap-2">
          <span className={
            apiOk == null ? "w-1.5 h-1.5 bg-term-muted animate-pulse"
            : apiOk ? "w-1.5 h-1.5 bg-term-green shadow-[0_0_6px_rgba(34,238,34,0.6)] animate-pulse"
            : "w-1.5 h-1.5 bg-term-red shadow-[0_0_6px_rgba(255,59,59,0.6)]"
          } />
          <span>TRADIER {apiOk == null ? "CONNECTING…" : apiOk ? "LIVE" : "RECONNECTING…"}</span>
        </span>
        <span>PROVIDER <span className="text-term-green ml-1 font-bold">TRADIER</span></span>
        <span>TABS <span className="text-term-text ml-1 num">{tabs.length}</span></span>
      </div>
      <div className="flex items-center gap-5 num">
        <span>{now.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "2-digit" })}</span>
        <span className="text-term-amber">{now.toLocaleTimeString()}</span>
      </div>
    </div>
  );
}
