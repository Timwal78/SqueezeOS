import { Leaderboard } from "@/components/Leaderboard";

export default function AnalystsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Global leaderboard</h1>
        <p className="text-muted">
          Ranked by compounding reputation: accuracy × timeliness, scored against SEC filings.
        </p>
      </div>
      <Leaderboard limit={100} />
      <p className="text-xs text-muted">
        Embed this anywhere: <code className="text-white">/embed/leaderboard</code> (iframe-friendly).
      </p>
    </div>
  );
}
