// Small helpers for loading / error / empty states. Per the project's data
// honesty rules: never invent numbers — show an em dash, "Awaiting data", or a
// real error.

export function Loading({ label = "Loading…" }: { label?: string }) {
  return <div className="animate-pulse text-muted">{label}</div>;
}

export function ErrorBox({ error }: { error: string }) {
  return (
    <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-300">
      Unavailable — {error}
    </div>
  );
}

export function Empty({ label = "Awaiting data" }: { label?: string }) {
  return <div className="text-muted">{label}</div>;
}

export function Dash() {
  return <span className="text-muted">—</span>;
}
