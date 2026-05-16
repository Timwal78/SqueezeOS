import { useQuery } from "@tanstack/react-query";
import { cn } from "@/lib/cn";
import { useWorkspace } from "@/store/workspaceStore";

export function SML() {
  const openTab = useWorkspace((s) => s.openTab);
  const { data, isLoading, error } = useQuery({
    queryKey: ["terminal-v2"],
    queryFn: async () => {
      const res = await fetch("/api/terminal");
      if (!res.ok) throw new Error("V2 API Offline");
      return res.json();
    },
    refetchInterval: 3000, // Institutional high-velocity refresh
  });

  if (isLoading) return <div className="p-8 text-term-muted uppercase tracking-[0.2em] animate-pulse">Initializing SML War Room Beast...</div>;
  if (error) return <div className="p-8 text-term-red uppercase tracking-[0.2em]">Council Offline: {(error as Error).message}</div>;

  const { 
    master_decision, master_grade, war_room_score, agents, tickers, 
    options, whale_alerts, news 
  } = data;

  return (
    <div className="p-1 flex flex-col gap-1 h-full overflow-hidden bg-black">
      {/* 1. MASTER BANNER - COMPACT & HIGH IMPACT */}
      <div className="bg-term-panel2 border-b border-term-amber/30 px-4 py-2 flex items-center justify-between shadow-[0_0_15px_rgba(255,140,0,0.1)]">
        <div className="flex items-center gap-6">
          <div className="flex flex-col">
            <span className="text-term-amber text-[9px] uppercase tracking-[0.4em] font-bold opacity-70">Institutional Verdict</span>
            <h1 className={cn("text-3xl font-black italic tracking-tighter leading-none mt-1", 
              master_decision.includes("LONG") ? "up" : "down")}>
              {master_decision}
            </h1>
          </div>
          <div className="h-10 w-px bg-term-border mx-2" />
          <div className="flex gap-6">
            <div className="text-center">
              <div className="text-[9px] text-term-muted uppercase tracking-widest">Grade</div>
              <div className="text-2xl font-black text-term-amber leading-none">{master_grade}</div>
            </div>
            <div className="text-center">
              <div className="text-[9px] text-term-muted uppercase tracking-widest">Edge</div>
              <div className="text-2xl font-black up leading-none">+{war_room_score.edge}</div>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-4 text-right">
          <div className="flex flex-col">
            <span className="text-[9px] text-term-muted uppercase tracking-widest">SML Core Status</span>
            <span className="text-term-green font-bold text-[11px] animate-pulse">● LIVE TAPE SYNCHRONIZED</span>
          </div>
        </div>
      </div>

      {/* 2. MAIN TELEMETRY GRID - NO EMPTY SPACE */}
      <div className="flex-1 grid grid-cols-12 gap-1 min-h-0 overflow-hidden">
        
        {/* COLUMN 1: AGENT COUNCIL (2 cols) */}
        <div className="col-span-2 panel flex flex-col">
          <div className="panel-header">
            <span>Agent Council</span>
            <span className="up font-bold">WRB V2</span>
          </div>
          <div className="flex-1 overflow-auto scroll-thin p-1 flex flex-col gap-1">
            {agents.map((agent: any) => (
              <div key={agent.name} className="p-2 bg-term-panel2/50 border border-term-border rounded text-[11px]">
                <div className="flex items-center justify-between mb-0.5">
                  <span className="text-term-amber font-bold uppercase text-[9px]">{agent.name}</span>
                  <span className="text-[8px] px-1 bg-term-green/10 text-term-green border border-term-green/20 rounded">
                    {agent.status}
                  </span>
                </div>
                <p className="text-term-text italic opacity-80 leading-snug">"{agent.last_thought}"</p>
              </div>
            ))}
          </div>
        </div>

        {/* COLUMN 2: REAL-TIME TICKERS (3 cols) */}
        <div className="col-span-3 panel flex flex-col">
          <div className="panel-header">
            <span>Real-Time Discovery</span>
            <span className="text-term-muted">Top 10 High-Vol</span>
          </div>
          <div className="flex-1 overflow-auto scroll-thin p-0">
            <table className="w-full text-[11px] grid-data border-separate border-spacing-0">
              <thead>
                <tr>
                  <th className="sticky top-0 bg-term-panel2">Ticker</th>
                  <th className="sticky top-0 bg-term-panel2 num">Price</th>
                  <th className="sticky top-0 bg-term-panel2 num">Apex</th>
                  <th className="sticky top-0 bg-term-panel2 num">GEX</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(tickers).map(([sym, t]: [string, any]) => (
                  <tr key={sym} className="cursor-pointer hover:bg-term-amberSubtle" onClick={() => openTab("INTEL", sym)}>
                    <td className={cn("font-bold", sym === "IWM" ? "text-term-cyan underline decoration-term-cyan/30" : "text-term-amber")}>{sym}</td>
                    <td className="num">{t.price.toFixed(2)}</td>
                    <td className={cn("num font-bold", t.apex > 5 ? "up" : "text-term-muted")}>{t.apex}</td>
                    <td className="num text-term-cyan">{(t.gex / 1e6).toFixed(1)}M</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* COLUMN 3: INSTITUTIONAL OPTION SWEEPS (4 cols) */}
        <div className="col-span-4 panel flex flex-col border-x-term-amber/20 border-x-2">
          <div className="panel-header">
            <span>Option Recommendations (S3 GRADE)</span>
            <span className="amber">Δ 0.30 - 0.45 Focus</span>
          </div>
          <div className="flex-1 overflow-auto scroll-thin p-0">
            <table className="w-full text-[10px] grid-data border-separate border-spacing-0">
              <thead>
                <tr>
                  <th className="sticky top-0 bg-term-panel2">Symbol</th>
                  <th className="sticky top-0 bg-term-panel2">Contract</th>
                  <th className="sticky top-0 bg-term-panel2 num">Mid</th>
                  <th className="sticky top-0 bg-term-panel2 num">Delta</th>
                  <th className="sticky top-0 bg-term-panel2 num">Grade</th>
                </tr>
              </thead>
              <tbody>
                {options.map((opt: any, i: number) => {
                  const isUserTarget = Math.abs(opt.delta) >= 0.3 && Math.abs(opt.delta) <= 0.45;
                  return (
                    <tr key={i} className={cn(isUserTarget && "bg-term-amber/5")}>
                      <td className="font-bold text-term-amber">{opt.symbol}</td>
                      <td>
                        <div className="flex flex-col leading-none">
                          <span className={cn("font-bold uppercase", opt.type === "call" ? "up" : "down")}>
                            ${opt.strike} {opt.type}
                          </span>
                          <span className="text-[8px] text-term-muted">{opt.expiration} ({opt.dte}D)</span>
                        </div>
                      </td>
                      <td className="num">${opt.mid.toFixed(2)}</td>
                      <td className={cn("num font-bold", isUserTarget ? "text-term-amber underline" : "text-term-muted")}>
                        {opt.delta.toFixed(3)}
                      </td>
                      <td className="num">
                        <span className={cn("px-1 rounded font-bold", 
                          opt.grade === 'A' ? "bg-term-green text-black" : 
                          opt.grade === 'B' ? "bg-term-amber text-black" : "text-term-muted")}>
                          {opt.grade}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {options.length === 0 && <div className="p-4 text-center text-term-muted italic">Scanning for high-conviction flow...</div>}
          </div>
        </div>

        {/* COLUMN 4: WHALE STALKER (3 cols) */}
        <div className="col-span-3 panel flex flex-col">
          <div className="panel-header">
            <span>Whale Stalker (Dark Pool)</span>
            <span className="up">Sweep Detected</span>
          </div>
          <div className="flex-1 overflow-auto scroll-thin p-1 flex flex-col gap-1">
            {whale_alerts.map((alert: any, i: number) => (
              <div key={i} className="p-1.5 border-b border-term-borderSoft last:border-0 hover:bg-term-panel2">
                <div className="flex justify-between items-center mb-0.5">
                  <span className="text-[11px] font-bold text-term-cyan">{alert.symbol}</span>
                  <span className="text-[9px] num text-term-muted">{alert.timestamp}</span>
                </div>
                <div className="text-[10px] leading-tight flex flex-col">
                  <div className="flex justify-between">
                    <span className="text-term-text">Type: <span className="font-bold">{alert.type}</span></span>
                    <span className="up font-bold">${(alert.value / 1e6).toFixed(2)}M</span>
                  </div>
                  <span className="text-term-muted truncate">D: {alert.description}</span>
                </div>
              </div>
            ))}
            {whale_alerts.length === 0 && <div className="p-4 text-center text-term-muted italic uppercase text-[9px]">Listening for dark pool echoes...</div>}
          </div>
        </div>
      </div>

      {/* 3. INTELLIGENCE WIRE (NEWS) - BOTTOM TAPE */}
      <div className="h-24 panel border-t-2 border-term-amber/40">
        <div className="panel-header bg-black/50">
          <span>Global Intelligence Wire</span>
          <span className="animate-pulse">STREAMING LIVE</span>
        </div>
        <div className="flex-1 overflow-x-auto overflow-y-hidden scroll-thin whitespace-nowrap p-2 flex items-center gap-6">
          {news.map((item: any, i: number) => (
            <div key={i} className="inline-flex flex-col min-w-[300px] border-r border-term-border pr-6 last:border-0">
              <div className="flex items-center gap-2 mb-0.5">
                <span className="text-[8px] text-term-amber bg-term-amber/10 px-1 border border-term-amber/20 rounded uppercase">{item.source}</span>
                <span className="text-[8px] text-term-muted num">{new Date(item.created_at).toLocaleTimeString()}</span>
              </div>
              <div className="text-[11px] text-term-heading truncate font-bold group cursor-pointer hover:text-term-amber"
                   onClick={() => window.open(item.url, '_blank')}>
                {item.headline}
              </div>
            </div>
          ))}
          {news.length === 0 && <div className="text-term-muted italic text-[11px]">Initializing news relays...</div>}
        </div>
      </div>
    </div>
  );
}

