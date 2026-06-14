import { TickerView } from "@/components/TickerView";

export default function TickerPage({ params }: { params: { ticker: string } }) {
  return <TickerView ticker={params.ticker.toUpperCase()} />;
}
