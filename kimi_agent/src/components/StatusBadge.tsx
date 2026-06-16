const statusStyles: Record<string, string> = {
  active: "status-badge status-active",
  pending: "status-badge status-pending",
  failed: "status-badge status-failed",
  disabled: "status-badge border-white/10 text-white/30 bg-white/5",
  accepted: "status-badge status-active",
  submitted: "status-badge border-[#00E5FF]/30 text-[#00E5FF] bg-[#00E5FF]/10",
  rejected: "status-badge status-failed",
  discovered: "status-badge border-white/10 text-white/30 bg-white/5",
  contacted: "status-badge status-pending",
  "sample_sent": "status-badge border-[#00E5FF]/30 text-[#00E5FF] bg-[#00E5FF]/10",
  engaged: "status-badge border-purple-500/30 text-purple-400 bg-purple-500/10",
  converted: "status-badge status-converted",
  blacklisted: "status-badge status-failed",
  success: "status-badge status-active",
  info: "status-badge border-white/10 text-white/50 bg-white/5",
  warning: "status-badge border-yellow-500/30 text-yellow-400 bg-yellow-500/10",
  error: "status-badge status-failed",
  delivered: "status-badge status-active",
  verified: "status-badge status-converted",
  sent: "status-badge status-pending",
  true: "status-badge status-converted",
  false: "status-badge border-white/10 text-white/30 bg-white/5",
};

interface StatusBadgeProps {
  status: string;
  children?: React.ReactNode;
}

export default function StatusBadge({ status, children }: StatusBadgeProps) {
  const style = statusStyles[status] || statusStyles.info;

  return (
    <span className={style}>
      <span className="w-1.5 h-1.5 rounded-full bg-current opacity-60" />
      {children || status}
    </span>
  );
}
