import NeonIcon from "./icons/NeonIcon";

interface StatCardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  icon: "satellite" | "radar" | "broadcast" | "shield" | "agent" | "transaction" | "target" | "interceptor";
  color?: string;
  active?: boolean;
}

export default function StatCard({ title, value, subtitle, icon, color = "#00E5FF", active = false }: StatCardProps) {
  return (
    <div className="glass-panel-hover p-5 relative overflow-hidden group">
      <div className="absolute top-0 right-0 p-3 opacity-30 group-hover:opacity-60 transition-opacity">
        <NeonIcon type={icon} size={24} color={color} active={active} />
      </div>

      <div className="relative z-10">
        <span className="text-[9px] uppercase tracking-[0.2em] text-white/40 font-medium">
          {title}
        </span>

        <div className="mt-3 font-display text-2xl sm:text-3xl text-white tracking-tight">
          {value}
        </div>

        {subtitle && (
          <p className="mt-1.5 text-[11px] text-white/30 leading-relaxed">
            {subtitle}
          </p>
        )}
      </div>

      {/* Bottom accent line */}
      <div
        className="absolute bottom-0 left-0 h-[1px] transition-all duration-500 group-hover:w-full"
        style={{
          width: active ? "60%" : "30%",
          background: `linear-gradient(90deg, ${color}40, transparent)`,
        }}
      />
    </div>
  );
}
