import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "xDEO — Decentralized Earnings Oracle",
  description:
    "A machine-native marketplace for earnings estimates, scored against real SEC EDGAR filings. Zero custody. Not investment advice.",
  openGraph: {
    title: "xDEO — Decentralized Earnings Oracle",
    description:
      "Reputation-ranked analyst earnings estimates, auto-scored against SEC filings. Pay per estimate via x402."
  }
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="font-mono">{children}</body>
    </html>
  );
}
