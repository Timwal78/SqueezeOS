import { VerdictView } from "@/components/VerdictView";

export default function VerdictPage({ params }: { params: { filingId: string } }) {
  return <VerdictView filingId={params.filingId} />;
}
