import { Link, useLocation } from "react-router";
import { useAuth } from "@/hooks/useAuth";
import NeonIcon from "./icons/NeonIcon";

const navItems = [
  { path: "/", label: "Command", icon: "radar" as const },
  { path: "/registry", label: "Broadcaster", icon: "broadcast" as const },
  { path: "/honeytrap", label: "Interceptor", icon: "interceptor" as const },
  { path: "/hustler", label: "Hustler", icon: "agent" as const },
];

export default function AppShell({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  const { user, logout } = useAuth();

  return (
    <div className="min-h-screen bg-[#050505] grid-pattern relative">
      {/* Fixed Header */}
      <header className="fixed top-6 left-1/2 -translate-x-1/2 z-50 w-auto">
        <nav className="flex items-center gap-1 px-2 py-2 rounded-full bg-white/[0.03] border border-white/10 backdrop-blur-xl shadow-2xl">
          <div className="flex items-center gap-2 px-4 mr-2">
            <NeonIcon type="radar" size={16} color="#00E5FF" active />
            <span className="font-display text-[10px] tracking-[0.2em] text-white/80 uppercase">
              Orion
            </span>
          </div>

          {navItems.map((item) => {
            const isActive = location.pathname === item.path;
            return (
              <Link
                key={item.path}
                to={item.path}
                className={`
                  flex items-center gap-2 px-4 py-2 rounded-full text-xs font-medium tracking-wide transition-all duration-300
                  ${isActive
                    ? "bg-[#00E5FF]/10 text-[#00E5FF] border border-[#00E5FF]/20"
                    : "text-white/50 hover:text-white/80 hover:bg-white/[0.05]"
                  }
                `}
              >
                <NeonIcon type={item.icon} size={14} color={isActive ? "#00E5FF" : "rgba(255,255,255,0.4)"} active={isActive} />
                {item.label}
              </Link>
            );
          })}

          <div className="w-px h-5 bg-white/10 mx-2" />

          {user ? (
            <div className="flex items-center gap-2 px-2">
              <span className="text-[10px] text-white/40 uppercase tracking-wider hidden sm:block">
                {user.name || "Operator"}
              </span>
              <button
                onClick={() => logout()}
                className="px-3 py-1.5 text-[10px] text-white/40 hover:text-white/80 uppercase tracking-wider transition-colors"
              >
                End
              </button>
            </div>
          ) : (
            <Link
              to="/login"
              className="px-3 py-1.5 text-[10px] text-[#00E5FF] hover:text-white uppercase tracking-wider transition-colors"
            >
              Auth
            </Link>
          )}
        </nav>
      </header>

      {/* Main Content */}
      <main className="pt-24 pb-12 px-4 sm:px-6 lg:px-8 max-w-[1440px] mx-auto">
        {children}
      </main>
    </div>
  );
}
