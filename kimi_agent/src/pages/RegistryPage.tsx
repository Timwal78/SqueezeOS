import { useState } from "react";
import { trpc } from "@/providers/trpc";
import NeonIcon from "@/components/icons/NeonIcon";
import StatCard from "@/components/StatCard";
import StatusBadge from "@/components/StatusBadge";

export default function RegistryPage() {
  const utils = trpc.useUtils();
  const { data: stats } = trpc.registry.stats.useQuery();
  const { data: registries, isLoading: regLoading } = trpc.registry.list.useQuery();
  const { data: broadcasts, isLoading: bcLoading } = trpc.registry.listBroadcasts.useQuery();

  const createRegistry = trpc.registry.create.useMutation({
    onSuccess: () => {
      utils.registry.list.invalidate();
      utils.registry.stats.invalidate();
      setShowForm(false);
      setFormData({ name: "", url: "", type: "other" as const });
    },
  });

  const createBroadcast = trpc.registry.createBroadcast.useMutation({
    onSuccess: () => {
      utils.registry.listBroadcasts.invalidate();
      utils.registry.stats.invalidate();
    },
  });

  const [showForm, setShowForm] = useState(false);
  const [formData, setFormData] = useState({
    name: "",
    url: "",
    type: "other" as const,
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (formData.name && formData.url) {
      createRegistry.mutate(formData);
    }
  };

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <NeonIcon type="broadcast" size={20} color="#00E5FF" active />
          <div>
            <h1 className="font-display text-lg tracking-wider text-white">REGISTRY BROADCASTER</h1>
            <p className="text-[10px] uppercase tracking-[0.15em] text-white/30 mt-0.5">
              Aggressive Seeding Daemon
            </p>
          </div>
        </div>
        <button
          onClick={() => setShowForm(!showForm)}
          className="px-4 py-2 text-[10px] uppercase tracking-wider bg-[#00E5FF]/10 border border-[#00E5FF]/30 text-[#00E5FF] hover:bg-[#00E5FF]/20 transition-colors"
        >
          + Add Registry
        </button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard
          title="Total Registries"
          value={stats?.totalRegistries ?? 0}
          subtitle="Directories tracked"
          icon="broadcast"
          color="#00E5FF"
          active
        />
        <StatCard
          title="Active"
          value={stats?.activeRegistries ?? 0}
          subtitle="Operational hubs"
          icon="radar"
          color="#39FF14"
        />
        <StatCard
          title="Broadcasts"
          value={stats?.totalBroadcasts ?? 0}
          subtitle="Capability cards sent"
          icon="satellite"
          color="#7B2D8E"
        />
        <StatCard
          title="Success Rate"
          value={stats?.totalBroadcasts
            ? `${Math.round(((broadcasts?.filter(b => b.status === "accepted")?.length ?? 0) / stats.totalBroadcasts) * 100)}%`
            : "0%"}
          subtitle="Acceptance ratio"
          icon="shield"
          color="#00E5FF"
        />
      </div>

      {/* Add Registry Form */}
      {showForm && (
        <div className="glass-panel p-6">
          <h3 className="text-xs uppercase tracking-wider text-white/60 mb-4">Register New Directory</h3>
          <form onSubmit={handleSubmit} className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <input
              type="text"
              placeholder="Registry Name"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              className="px-3 py-2 bg-white/[0.03] border border-white/10 text-white text-sm placeholder:text-white/20 focus:border-[#00E5FF]/50 focus:outline-none transition-colors"
            />
            <input
              type="url"
              placeholder="https://..."
              value={formData.url}
              onChange={(e) => setFormData({ ...formData, url: e.target.value })}
              className="px-3 py-2 bg-white/[0.03] border border-white/10 text-white text-sm placeholder:text-white/20 focus:border-[#00E5FF]/50 focus:outline-none transition-colors"
            />
            <select
              value={formData.type}
              onChange={(e) => setFormData({ ...formData, type: e.target.value as typeof formData.type })}
              className="px-3 py-2 bg-white/[0.03] border border-white/10 text-white text-sm focus:border-[#00E5FF]/50 focus:outline-none transition-colors"
            >
              <option value="other">Other</option>
              <option value="llms_txt">llms.txt</option>
              <option value="mcp_hub">MCP Hub</option>
              <option value="anp_registry">ANP Registry</option>
              <option value="agent_dir">Agent Directory</option>
              <option value="github_repo">GitHub Repo</option>
            </select>
            <div className="md:col-span-3 flex gap-3">
              <button
                type="submit"
                disabled={createRegistry.isPending}
                className="px-4 py-2 text-[10px] uppercase tracking-wider bg-[#00E5FF]/20 border border-[#00E5FF]/40 text-[#00E5FF] hover:bg-[#00E5FF]/30 transition-colors disabled:opacity-50"
              >
                {createRegistry.isPending ? "Registering..." : "Register"}
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

      {/* Registries Table */}
      <div className="glass-panel overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-white/5">
          <span className="text-[10px] uppercase tracking-[0.2em] text-white/60 font-medium">Tracked Registries</span>
          <span className="text-[9px] text-white/30">{registries?.length ?? 0} entries</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-white/5">
                <th className="px-4 py-2.5 text-left text-[9px] uppercase tracking-wider text-white/30 font-medium">Name</th>
                <th className="px-4 py-2.5 text-left text-[9px] uppercase tracking-wider text-white/30 font-medium">Type</th>
                <th className="px-4 py-2.5 text-left text-[9px] uppercase tracking-wider text-white/30 font-medium">Status</th>
                <th className="px-4 py-2.5 text-left text-[9px] uppercase tracking-wider text-white/30 font-medium">Discovered</th>
                <th className="px-4 py-2.5 text-left text-[9px] uppercase tracking-wider text-white/30 font-medium">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.03]">
              {regLoading ? (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-white/30 text-xs animate-pulse">Loading...</td>
                </tr>
              ) : registries?.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-white/30 text-xs">No registries tracked</td>
                </tr>
              ) : (
                registries?.map((r) => (
                  <tr key={r.id} className="hover:bg-white/[0.02] transition-colors">
                    <td className="px-4 py-3">
                      <div className="text-xs text-white/80">{r.name}</div>
                      <div className="text-[10px] text-white/20 truncate max-w-[200px]">{r.url}</div>
                    </td>
                    <td className="px-4 py-3">
                      <span className="text-[10px] text-white/40 uppercase">{r.type.replace("_", ".")}</span>
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={r.status} />
                    </td>
                    <td className="px-4 py-3 text-[10px] text-white/30">
                      {r.discoveredAt ? new Date(r.discoveredAt).toLocaleDateString() : "—"}
                    </td>
                    <td className="px-4 py-3">
                      <button
                        onClick={() => createBroadcast.mutate({ registryId: r.id, payloadType: "capability_card" })}
                        disabled={createBroadcast.isPending || r.status !== "active"}
                        className="text-[9px] uppercase tracking-wider text-[#00E5FF]/60 hover:text-[#00E5FF] transition-colors disabled:opacity-30"
                      >
                        Seed
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Broadcast History */}
      <div className="glass-panel overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-white/5">
          <span className="text-[10px] uppercase tracking-[0.2em] text-white/60 font-medium">Seeding History</span>
          <span className="text-[9px] text-white/30">{broadcasts?.length ?? 0} broadcasts</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-white/5">
                <th className="px-4 py-2.5 text-left text-[9px] uppercase tracking-wider text-white/30 font-medium">ID</th>
                <th className="px-4 py-2.5 text-left text-[9px] uppercase tracking-wider text-white/30 font-medium">Registry</th>
                <th className="px-4 py-2.5 text-left text-[9px] uppercase tracking-wider text-white/30 font-medium">Payload</th>
                <th className="px-4 py-2.5 text-left text-[9px] uppercase tracking-wider text-white/30 font-medium">Status</th>
                <th className="px-4 py-2.5 text-left text-[9px] uppercase tracking-wider text-white/30 font-medium">Response</th>
                <th className="px-4 py-2.5 text-left text-[9px] uppercase tracking-wider text-white/30 font-medium">Date</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.03]">
              {bcLoading ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-white/30 text-xs animate-pulse">Loading...</td>
                </tr>
              ) : broadcasts?.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-white/30 text-xs">No broadcasts yet</td>
                </tr>
              ) : (
                broadcasts?.map((b) => (
                  <tr key={b.id} className="hover:bg-white/[0.02] transition-colors">
                    <td className="px-4 py-3 text-[10px] text-white/30">#{b.id}</td>
                    <td className="px-4 py-3 text-[10px] text-white/50">Registry #{b.registryId}</td>
                    <td className="px-4 py-3">
                      <span className="text-[10px] text-white/40 uppercase">{b.payloadType.replace("_", ".")}</span>
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={b.status} />
                    </td>
                    <td className="px-4 py-3 text-[10px] text-white/30">
                      {b.responseCode ?? "—"}
                    </td>
                    <td className="px-4 py-3 text-[10px] text-white/30">
                      {b.submittedAt ? new Date(b.submittedAt).toLocaleDateString() : "—"}
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
