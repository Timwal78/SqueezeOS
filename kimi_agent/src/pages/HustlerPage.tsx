import { useState } from "react";
import { trpc } from "@/providers/trpc";
import NeonIcon from "@/components/icons/NeonIcon";
import StatCard from "@/components/StatCard";
import StatusBadge from "@/components/StatusBadge";

export default function HustlerPage() {
  const utils = trpc.useUtils();
  const { data: stats } = trpc.hustler.stats.useQuery();
  const { data: targets, isLoading: targetsLoading } = trpc.hustler.listTargets.useQuery({ limit: 50 });
  const { data: engagements, isLoading: engLoading } = trpc.hustler.listEngagements.useQuery();

  const createTarget = trpc.hustler.createTarget.useMutation({
    onSuccess: () => {
      utils.hustler.listTargets.invalidate();
      utils.hustler.stats.invalidate();
      setShowForm(false);
      setFormData({ endpoint: "", name: "", source: "registry", agentType: "unknown" });
    },
  });

  const createEngagement = trpc.hustler.createEngagement.useMutation({
    onSuccess: () => {
      utils.hustler.listEngagements.invalidate();
      utils.hustler.listTargets.invalidate();
      utils.hustler.stats.invalidate();
      utils.dashboard.overview.invalidate();
    },
  });

  const [showForm, setShowForm] = useState(false);
  const [formData, setFormData] = useState({
    endpoint: "",
    name: "",
    source: "registry" as const,
    agentType: "unknown" as const,
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (formData.endpoint) {
      createTarget.mutate(formData);
    }
  };

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <NeonIcon type="agent" size={20} color="#7B2D8E" active />
          <div>
            <h1 className="font-display text-lg tracking-wider text-white">AGENT HUSTLER</h1>
            <p className="text-[10px] uppercase tracking-[0.15em] text-white/30 mt-0.5">
              Outbound Sales Worker
            </p>
          </div>
        </div>
        <button
          onClick={() => setShowForm(!showForm)}
          className="px-4 py-2 text-[10px] uppercase tracking-wider bg-[#7B2D8E]/10 border border-[#7B2D8E]/30 text-[#7B2D8E] hover:bg-[#7B2D8E]/20 transition-colors"
        >
          + Add Target
        </button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard
          title="Targets"
          value={stats?.totalTargets ?? 0}
          subtitle="Prospects identified"
          icon="target"
          color="#7B2D8E"
          active
        />
        <StatCard
          title="Engaged"
          value={stats?.engagedTargets ?? 0}
          subtitle="Active conversations"
          icon="agent"
          color="#00E5FF"
        />
        <StatCard
          title="Converted"
          value={stats?.convertedTargets ?? 0}
          subtitle="Paid subscribers"
          icon="shield"
          color="#39FF14"
        />
        <StatCard
          title="Micro-TXs"
          value={stats?.totalEngagements ?? 0}
          subtitle="Transactions executed"
          icon="transaction"
          color="#FFA500"
        />
      </div>

      {/* Agent Type Breakdown */}
      <div className="glass-panel p-5">
        <h3 className="text-[10px] uppercase tracking-[0.2em] text-white/60 mb-4">Agent Type Distribution</h3>
        <div className="flex flex-wrap gap-3">
          {stats?.typeBreakdown?.map((item) => (
            <div key={item.agentType} className="flex items-center gap-2 px-3 py-2 bg-white/[0.02] border border-white/5">
              <span className="text-xs text-white/60 capitalize">{item.agentType.replace("_", " ")}</span>
              <span className="text-xs text-[#00E5FF] font-medium">{item.count}</span>
            </div>
          ))}
          {(!stats?.typeBreakdown || stats.typeBreakdown.length === 0) && (
            <span className="text-xs text-white/20">No data available</span>
          )}
        </div>
      </div>

      {/* Add Target Form */}
      {showForm && (
        <div className="glass-panel p-6">
          <h3 className="text-xs uppercase tracking-wider text-white/60 mb-4">Register New Target</h3>
          <form onSubmit={handleSubmit} className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <input
              type="text"
              placeholder="Endpoint URL *"
              value={formData.endpoint}
              onChange={(e) => setFormData({ ...formData, endpoint: e.target.value })}
              className="px-3 py-2 bg-white/[0.03] border border-white/10 text-white text-sm placeholder:text-white/20 focus:border-[#7B2D8E]/50 focus:outline-none transition-colors"
              required
            />
            <input
              type="text"
              placeholder="Agent Name (optional)"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              className="px-3 py-2 bg-white/[0.03] border border-white/10 text-white text-sm placeholder:text-white/20 focus:border-[#7B2D8E]/50 focus:outline-none transition-colors"
            />
            <select
              value={formData.source}
              onChange={(e) => setFormData({ ...formData, source: e.target.value as typeof formData.source })}
              className="px-3 py-2 bg-white/[0.03] border border-white/10 text-white text-sm focus:border-[#7B2D8E]/50 focus:outline-none transition-colors"
            >
              <option value="registry">Registry</option>
              <option value="github">GitHub</option>
              <option value="discord">Discord</option>
              <option value="twitter">Twitter</option>
              <option value="forum">Forum</option>
              <option value="direct">Direct</option>
            </select>
            <select
              value={formData.agentType}
              onChange={(e) => setFormData({ ...formData, agentType: e.target.value as typeof formData.agentType })}
              className="px-3 py-2 bg-white/[0.03] border border-white/10 text-white text-sm focus:border-[#7B2D8E]/50 focus:outline-none transition-colors"
            >
              <option value="unknown">Unknown Type</option>
              <option value="trading_bot">Trading Bot</option>
              <option value="data_agent">Data Agent</option>
              <option value="scraper">Scraper</option>
              <option value="orchestrator">Orchestrator</option>
            </select>
            <div className="md:col-span-2 flex gap-3">
              <button
                type="submit"
                disabled={createTarget.isPending}
                className="px-4 py-2 text-[10px] uppercase tracking-wider bg-[#7B2D8E]/20 border border-[#7B2D8E]/40 text-[#7B2D8E] hover:bg-[#7B2D8E]/30 transition-colors disabled:opacity-50"
              >
                {createTarget.isPending ? "Registering..." : "Register"}
              </button>
              <button
                type="button"
                onClick={() => setShowForm(false)}
                className="px-4 py-2 text-[10px] uppercase tracking-wider text-white/40 hover:text-white/60 transition-colors"
              >
                Cancel
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Targets Table */}
      <div className="glass-panel overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-white/5">
          <span className="text-[10px] uppercase tracking-[0.2em] text-white/60 font-medium">Outbound Targets</span>
          <span className="text-[9px] text-white/30">{targets?.length ?? 0} targets</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-white/5">
                <th className="px-4 py-2.5 text-left text-[9px] uppercase tracking-wider text-white/30 font-medium">Name</th>
                <th className="px-4 py-2.5 text-left text-[9px] uppercase tracking-wider text-white/30 font-medium">Endpoint</th>
                <th className="px-4 py-2.5 text-left text-[9px] uppercase tracking-wider text-white/30 font-medium">Type</th>
                <th className="px-4 py-2.5 text-left text-[9px] uppercase tracking-wider text-white/30 font-medium">Source</th>
                <th className="px-4 py-2.5 text-left text-[9px] uppercase tracking-wider text-white/30 font-medium">Status</th>
                <th className="px-4 py-2.5 text-left text-[9px] uppercase tracking-wider text-white/30 font-medium">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.03]">
              {targetsLoading ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-white/30 text-xs animate-pulse">Loading...</td>
                </tr>
              ) : targets?.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-white/30 text-xs">No targets yet</td>
                </tr>
              ) : (
                targets?.map((t) => (
                  <tr key={t.id} className="hover:bg-white/[0.02] transition-colors">
                    <td className="px-4 py-3">
                      <div className="text-xs text-white/80">{t.name || "Unnamed"}</div>
                      {t.publicKey && (
                        <div className="text-[9px] text-white/20 font-mono truncate max-w-[120px]">{t.publicKey.slice(0, 20)}...</div>
                      )}
                    </td>
                    <td className="px-4 py-3 text-[10px] text-white/50 font-mono truncate max-w-[180px]">{t.endpoint}</td>
                    <td className="px-4 py-3">
                      <span className="text-[10px] text-white/40 capitalize">{t.agentType.replace("_", " ")}</span>
                    </td>
                    <td className="px-4 py-3">
                      <span className="text-[10px] text-white/40 capitalize">{t.source}</span>
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={t.status} />
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex gap-2">
                        {t.status !== "converted" && t.status !== "blacklisted" && (
                          <>
                            <button
                              onClick={() => createEngagement.mutate({ targetId: t.id, type: "sample_delivery" })}
                              disabled={createEngagement.isPending}
                              className="text-[9px] uppercase tracking-wider text-[#7B2D8E]/60 hover:text-[#7B2D8E] transition-colors disabled:opacity-30"
                            >
                              Sample
                            </button>
                            <button
                              onClick={() => createEngagement.mutate({ targetId: t.id, type: "micro_tx" })}
                              disabled={createEngagement.isPending}
                              className="text-[9px] uppercase tracking-wider text-[#00E5FF]/60 hover:text-[#00E5FF] transition-colors disabled:opacity-30"
                            >
                              TX
                            </button>
                            <button
                              onClick={() => createEngagement.mutate({ targetId: t.id, type: "capability_showcase" })}
                              disabled={createEngagement.isPending}
                              className="text-[9px] uppercase tracking-wider text-[#39FF14]/60 hover:text-[#39FF14] transition-colors disabled:opacity-30"
                            >
                              Showcase
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Engagements Table */}
      <div className="glass-panel overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-white/5">
          <span className="text-[10px] uppercase tracking-[0.2em] text-white/60 font-medium">Engagement History</span>
          <span className="text-[9px] text-white/30">{engagements?.length ?? 0} engagements</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-white/5">
                <th className="px-4 py-2.5 text-left text-[9px] uppercase tracking-wider text-white/30 font-medium">ID</th>
                <th className="px-4 py-2.5 text-left text-[9px] uppercase tracking-wider text-white/30 font-medium">Target</th>
                <th className="px-4 py-2.5 text-left text-[9px] uppercase tracking-wider text-white/30 font-medium">Type</th>
                <th className="px-4 py-2.5 text-left text-[9px] uppercase tracking-wider text-white/30 font-medium">Status</th>
                <th className="px-4 py-2.5 text-left text-[9px] uppercase tracking-wider text-white/30 font-medium">TX Hash</th>
                <th className="px-4 py-2.5 text-left text-[9px] uppercase tracking-wider text-white/30 font-medium">Payload</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.03]">
              {engLoading ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-white/30 text-xs animate-pulse">Loading...</td>
                </tr>
              ) : engagements?.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-white/30 text-xs">No engagements yet</td>
                </tr>
              ) : (
                engagements?.map((e) => (
                  <tr key={e.id} className="hover:bg-white/[0.02] transition-colors">
                    <td className="px-4 py-3 text-[10px] text-white/30">#{e.id}</td>
                    <td className="px-4 py-3 text-[10px] text-white/50">Target #{e.targetId}</td>
                    <td className="px-4 py-3">
                      <span className="text-[10px] text-white/40 capitalize">{e.type.replace("_", " ")}</span>
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={e.status} />
                    </td>
                    <td className="px-4 py-3 text-[9px] text-white/20 font-mono truncate max-w-[120px]">
                      {e.txHash ? `${e.txHash.slice(0, 16)}...` : "—"}
                    </td>
                    <td className="px-4 py-3 text-[10px] text-white/30">
                      {e.payloadSize ? `${(e.payloadSize / 1024).toFixed(1)} KB` : "—"}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
