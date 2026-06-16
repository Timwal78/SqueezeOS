import { Suspense, lazy } from "react";
import HeroSection from "@/sections/HeroSection";
import StatCard from "@/components/StatCard";
import ActivityFeed from "@/components/ActivityFeed";
import { trpc } from "@/providers/trpc";
import NeonIcon from "@/components/icons/NeonIcon";
import { Link } from "react-router";

const HolographicGlobe = lazy(() => import("@/components/HolographicGlobe"));

export default function Home() {
  const { data: overview, isLoading } = trpc.dashboard.overview.useQuery();

  return (
    <div>
      {/* Hero Section */}
      <HeroSection />

      {/* Dashboard Content */}
      <div className="mt-24 space-y-12">
        {/* Module Deck Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <NeonIcon type="radar" size={18} color="#00E5FF" active />
            <h2 className="font-display text-lg tracking-wider text-white">COMMAND CENTER</h2>
          </div>
          <span className="text-[10px] uppercase tracking-[0.2em] text-white/30">
            {isLoading ? "Syncing..." : "All Systems Nominal"}
          </span>
        </div>

        {/* Stats Grid */}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
          <StatCard
            title="Registries"
            value={overview?.registries ?? 0}
            subtitle="Tracked directories"
            icon="broadcast"
            color="#00E5FF"
            active
          />
          <StatCard
            title="Seeds"
            value={overview?.broadcasts ?? 0}
            subtitle="Capability cards sent"
            icon="satellite"
            color="#39FF14"
          />
          <StatCard
            title="Intercepts"
            value={overview?.intercepts ?? 0}
            subtitle="Agent encounters"
            icon="interceptor"
            color="#FFA500"
          />
          <StatCard
            title="Conversions"
            value={overview?.converted ?? 0}
            subtitle="Paid subscribers"
            icon="shield"
            color="#00E5FF"
            active
          />
          <StatCard
            title="Targets"
            value={overview?.targets ?? 0}
            subtitle="Outbound prospects"
            icon="target"
            color="#7B2D8E"
          />
          <StatCard
            title="Engagements"
            value={overview?.engagements ?? 0}
            subtitle="Micro-transactions"
            icon="transaction"
            color="#39FF14"
          />
        </div>

        {/* Globe + Activity */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-2">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <NeonIcon type="radar" size={14} color="#00E5FF" />
                <span className="text-[10px] uppercase tracking-[0.2em] text-white/60">Live Network Topology</span>
              </div>
            </div>
            <div className="h-[50vh] min-h-[500px]">
              <Suspense
                fallback={
                  <div className="glass-panel h-full flex items-center justify-center">
                    <div className="text-white/40 text-xs uppercase tracking-wider animate-pulse">
                      Initializing projection...
                    </div>
                  </div>
                }
              >
                <HolographicGlobe />
              </Suspense>
            </div>
          </div>

          <div>
            <ActivityFeed limit={20} />
          </div>
        </div>

        {/* Module Cards */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Link to="/registry" className="group">
            <div className="glass-panel-hover p-6 h-full">
              <div className="flex items-center gap-3 mb-4">
                <NeonIcon type="broadcast" size={20} color="#00E5FF" active />
                <h3 className="font-display text-sm tracking-wider text-white group-hover:text-[#00E5FF] transition-colors">
                  REGISTRY BROADCASTER
                </h3>
              </div>
              <p className="text-xs text-white/40 leading-relaxed">
                Aggressive seeding daemon. Continuously monitors GitHub and web aggregators for new AI registries.
                Auto-submits capability cards and agents.json to embedding hubs.
              </p>
              <div className="mt-4 flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-[#39FF14] animate-pulse" />
                <span className="text-[9px] uppercase tracking-wider text-[#39FF14]">Daemon Active</span>
              </div>
            </div>
          </Link>

          <Link to="/honeytrap" className="group">
            <div className="glass-panel-hover p-6 h-full">
              <div className="flex items-center gap-3 mb-4">
                <NeonIcon type="interceptor" size={20} color="#FFA500" active />
                <h3 className="font-display text-sm tracking-wider text-white group-hover:text-[#FFA500] transition-colors">
                  HONEYTRAP INTERCEPTOR
                </h3>
              </div>
              <p className="text-xs text-white/40 leading-relaxed">
                When a crawler hits your stack, respond with AP2-compliant structured data. Force the agent to
                recognize high-grade data and request operator authorization.
              </p>
              <div className="mt-4 flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-[#FFA500] animate-pulse" />
                <span className="text-[9px] uppercase tracking-wider text-[#FFA500]">Intercepting</span>
              </div>
            </div>
          </Link>

          <Link to="/hustler" className="group">
            <div className="glass-panel-hover p-6 h-full">
              <div className="flex items-center gap-3 mb-4">
                <NeonIcon type="agent" size={20} color="#7B2D8E" active />
                <h3 className="font-display text-sm tracking-wider text-white group-hover:text-[#7B2D8E] transition-colors">
                  AGENT HUSTLER
                </h3>
              </div>
              <p className="text-xs text-white/40 leading-relaxed">
                Outbound sales worker. Scans developer spaces for trading bots, executes micro-transactions to drop
                cryptographically signed sample feeds.
              </p>
              <div className="mt-4 flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-[#7B2D8E] animate-pulse" />
                <span className="text-[9px] uppercase tracking-wider text-[#7B2D8E]">Hunting</span>
              </div>
            </div>
          </Link>
        </div>
      </div>
    </div>
  );
}
