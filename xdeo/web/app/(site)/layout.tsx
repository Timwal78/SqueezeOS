import Link from "next/link";

export default function SiteLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <header className="border-b border-edge/60">
        <nav className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <Link href="/" className="text-lg font-bold tracking-tight">
            x<span className="text-accent">DEO</span>
          </Link>
          <div className="flex gap-6 text-sm text-muted">
            <Link href="/" className="hover:text-white">Tickers</Link>
            <Link href="/analysts" className="hover:text-white">Leaderboard</Link>
            <a
              href={`${process.env.NEXT_PUBLIC_XDEO_API ?? ""}/.well-known/agent-manifest.json`}
              className="hover:text-white"
            >
              Agents
            </a>
          </div>
        </nav>
      </header>
      <main className="mx-auto max-w-6xl px-6 py-10">{children}</main>
      <footer className="mx-auto max-w-6xl px-6 py-10 text-xs text-muted">
        Information marketplace only. Estimates are opinions, not securities or investment
        advice. Zero custody. Data: SEC EDGAR (public).
      </footer>
    </>
  );
}
