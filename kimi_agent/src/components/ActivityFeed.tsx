import { useEffect, useRef, useState } from "react";
import { trpc } from "@/providers/trpc";
import NeonIcon from "./icons/NeonIcon";

const levelColors: Record<string, string> = {
  info: "#00E5FF",
  warning: "#FFA500",
  error: "#FF4444",
  success: "#39FF14",
};

const moduleIcons: Record<string, "satellite" | "radar" | "broadcast" | "shield" | "agent" | "transaction" | "target" | "interceptor"> = {
  registry: "broadcast",
  honeytrap: "interceptor",
  hustler: "agent",
  system: "radar",
};

export default function ActivityFeed({ limit = 20 }: { limit?: number }) {
  const { data: activities, isLoading } = trpc.dashboard.overview.useQuery();
  const feedRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);

  useEffect(() => {
    if (autoScroll && feedRef.current) {
      feedRef.current.scrollTop = 0;
    }
  }, [activities, autoScroll]);

  if (isLoading) {
    return (
      <div className="glass-panel p-4 h-[400px] flex items-center justify-center">
        <div className="text-white/40 text-xs uppercase tracking-wider animate-pulse">Loading feed...</div>
      </div>
    );
  }

  const items = activities?.recentActivity?.slice(0, limit) || [];

  return (
    <div className="glass-panel p-0 overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-white/5">
        <div className="flex items-center gap-2">
          <NeonIcon type="radar" size={14} color="#00E5FF" active />
          <span className="text-[10px] uppercase tracking-[0.2em] text-white/60 font-medium">System Intercepts</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-1.5 h-1.5 rounded-full bg-[#39FF14] animate-pulse" />
          <span className="text-[9px] uppercase tracking-wider text-white/30">Live</span>
        </div>
      </div>

      <div
        ref={feedRef}
        className="h-[400px] overflow-y-auto scrollbar-thin scrollbar-thumb-white/10 scrollbar-track-transparent"
        onScroll={() => setAutoScroll(false)}
      >
        {items.length === 0 ? (
          <div className="flex items-center justify-center h-full text-white/30 text-xs">No activity recorded</div>
        ) : (
          <div className="divide-y divide-white/[0.03]">
            {items.map((item) => (
              <div key={item.id} className="px-4 py-3 hover:bg-white/[0.02] transition-colors group">
                <div className="flex items-start gap-3">
                  <NeonIcon
                    type={moduleIcons[item.module] || "radar"}
                    size={12}
                    color={levelColors[item.level] || "#00E5FF"}
                  />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span
                        className="text-[9px] uppercase tracking-wider font-medium"
                        style={{ color: levelColors[item.level] || "#00E5FF" }}
                      >
                        {item.module}
                      </span>
                      <span className="text-[9px] text-white/20">
                        {item.createdAt ? new Date(item.createdAt).toLocaleTimeString() : ""}
                      </span>
                    </div>
                    <p className="text-xs text-white/60 leading-relaxed group-hover:text-white/80 transition-colors">
                      {item.message}
                    </p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
