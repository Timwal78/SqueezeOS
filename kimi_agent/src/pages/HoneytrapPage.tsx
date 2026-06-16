
import { trpc } from "@/providers/trpc";
import NeonIcon from "@/components/icons/NeonIcon";
import StatCard from "@/components/StatCard";
import StatusBadge from "@/components/StatusBadge";

export default function HoneytrapPage() {
  const utils = trpc.useUtils();
  const { data: stats } = trpc.honeytrap.stats.useQuery();
  const { data: requests, isLoading: reqLoading } = trpc.honeytrap.list.useQuery({ limit: 50 });



  const markConverted = trpc.honeytrap.markConverted.useMutation({
    onSuccess: () => {
      utils.honeytrap.list.invalidate();
      utils.honeytrap.stats.invalidate();
      utils.dashboard.overview.invalidate();
    },
  });



  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <NeonIcon type="interceptor" size={20} color="#FFA500" active />
          <div>
            <h1 className="font-display text-lg tracking-wider text-white">HONEYTRAP INTERCEPTOR</h1>
            <p className="text-[10px] uppercase tracking-[0.15em] text-white/30 mt-0.5">
              AP2-Compliant Agent Response System
            </p>
          </div>
        </div>

      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard
          title="Total Intercepts"
          value={stats?.totalRequests ?? 0}
          subtitle="Agent encounters"
          icon="interceptor"
          color="#FFA500"
          active
        />
        <StatCard
          title="Converted"
          value={stats?.convertedRequests ?? 0}
          subtitle="Paid subscribers"
          icon="shield"
          color="#39FF14"
        />
        <StatCard
          title="Conversion Rate"
          value={`${stats?.conversionRate ?? 0}%`}
          subtitle="402 to paid"
          icon="target"
          color="#00E5FF"
        />
        <StatCard
          title="24h Volume"
          value={stats?.recent24h ?? 0}
          subtitle="Recent intercepts"
          icon="radar"
          color="#7B2D8E"
        />
      </div>

      {/* Intent Breakdown */}
      <div className="glass-panel p-5">
        <h3 className="text-[10px] uppercase tracking-[0.2em] text-white/60 mb-4">Intent Distribution</h3>
        <div className="flex flex-wrap gap-3">
          {stats?.intentBreakdown?.map((item) => (
            <div key={item.intent} className="flex items-center gap-2 px-3 py-2 bg-white/[0.02] border border-white/5">
              <span className="text-xs text-white/60 capitalize">{item.intent.replace("_", " ")}</span>
              <span className="text-xs text-[#00E5FF] font-medium">{item.count}</span>
            </div>
          ))}
          {(!stats?.intentBreakdown || stats.intentBreakdown.length === 0) && (
            <span className="text-xs text-white/20">No data available</span>
          )}
        </div>
      </div>



      {/* Intercepts Table */}
      <div className="glass-panel overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-white/5">
          <span className="text-[10px] uppercase tracking-[0.2em] text-white/60 font-medium">Intercept Log</span>
          <span className="text-[9px] text-white/30">{requests?.length ?? 0} entries</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-white/5">
                <th className="px-4 py-2.5 text-left text-[9px] uppercase tracking-wider text-white/30 font-medium">ID</th>
                <th className="px-4 py-2.5 text-left text-[9px] uppercase tracking-wider text-white/30 font-medium">Source</th>
                <th className="px-4 py-2.5 text-left text-[9px] uppercase tracking-wider text-white/30 font-medium">Path</th>
                <th className="px-4 py-2.5 text-left text-[9px] uppercase tracking-wider text-white/30 font-medium">Intent</th>
                <th className="px-4 py-2.5 text-left text-[9px] uppercase tracking-wider text-white/30 font-medium">Response</th>
                <th className="px-4 py-2.5 text-left text-[9px] uppercase tracking-wider text-white/30 font-medium">Converted</th>
                <th className="px-4 py-2.5 text-left text-[9px] uppercase tracking-wider text-white/30 font-medium">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.03]">
              {reqLoading ? (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-white/30 text-xs animate-pulse">Loading...</td>
                </tr>
              ) : requests?.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-white/30 text-xs">No intercepts recorded</td>
                </tr>
              ) : (
                requests?.map((req) => (
                  <tr key={req.id} className="hover:bg-white/[0.02] transition-colors">
                    <td className="px-4 py-3 text-[10px] text-white/30">#{req.id}</td>
                    <td className="px-4 py-3">
                      <div className="text-[10px] text-white/50">{req.sourceIp || "—"}</div>
                      {req.userAgent && (
                        <div className="text-[9px] text-white/20 truncate max-w-[150px]">{req.userAgent}</div>
                      )}
                    </td>
                    <td className="px-4 py-3 text-[10px] text-white/50 font-mono">{req.requestPath}</td>
                    <td className="px-4 py-3">
                      <span className="text-[10px] text-white/40 capitalize">{req.intent.replace("_", " ")}</span>
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={req.responseType} />
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={req.converted ? "true" : "false"}>
                        {req.converted ? "Yes" : "No"}
                      </StatusBadge>
                    </td>
                    <td className="px-4 py-3">
                      {!req.converted && (
                        <button
                          onClick={() => markConverted.mutate({ id: req.id })}
                          disabled={markConverted.isPending}
                          className="text-[9px] uppercase tracking-wider text-[#39FF14]/60 hover:text-[#39FF14] transition-colors disabled:opacity-30"
                        >
                          Convert
                        </button>
                      )}
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
