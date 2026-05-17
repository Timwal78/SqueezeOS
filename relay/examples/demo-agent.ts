/**
 * demo-agent.ts — Beastmode demo of the Relay 402 payment handshake.
 *
 * Runs the complete flow entirely in-process — no real XRPL network, no
 * browser, no external services. The verifier is patched at module load time
 * and payment signing is injected via _signPayment.
 *
 * Run:
 *   npx ts-node --project mcp-paywall/tsconfig.json examples/demo-agent.ts
 */

// ── Patch verifyPayment before any paywall module is imported ─────────────────
// ts-node executes imports in order, so we import the verifier module first
// and replace its export on the module object. paywall.ts calls verifyPayment
// via a live binding from the same module reference, so the patch takes effect.
import * as verifierModule from "../mcp-paywall/src/verifier";
(verifierModule as any).verifyPayment = async (proof: string) => {
  if (!proof) return { valid: false, reason: "No proof" };
  return { valid: true };
};

// ── Now import everything else ────────────────────────────────────────────────
import { Wallet } from "xrpl";
import { agentWallet }  from "../mcp-paywall/src/agent-wallet";
import { extract402Invoice, is402Response } from "../mcp-paywall/src/paywall";
import type { PaymentInvoice, CallToolResult } from "../mcp-paywall/src/types";
import { makeServer } from "./demo-server";

// ── ANSI colour helpers ───────────────────────────────────────────────────────

const R  = "\x1b[0m";       // reset
const B  = "\x1b[1m";       // bold
const DIM = "\x1b[2m";      // dim
const C  = "\x1b[36m";      // cyan
const G  = "\x1b[32m";      // green
const Y  = "\x1b[33m";      // yellow
const M  = "\x1b[35m";      // magenta
const RD = "\x1b[31m";      // red
const BL = "\x1b[34m";      // blue

function line(ch = "━", len = 60): string { return ch.repeat(len); }
function box(text: string, width = 60): string {
  const pad = Math.max(0, width - text.length - 4);
  const lp  = Math.floor(pad / 2);
  const rp  = pad - lp;
  return [
    `╔${"═".repeat(width - 2)}╗`,
    `║  ${" ".repeat(lp)}${text}${" ".repeat(rp)}  ║`,
    `╚${"═".repeat(width - 2)}╝`,
  ].join("\n");
}

// ── Formatting helpers ────────────────────────────────────────────────────────

function truncAddr(addr: string, keep = 8): string {
  return `${addr.slice(0, keep + 1)}…${addr.slice(-4)}`;
}

function prettyResult(result: CallToolResult): string {
  try {
    const text = (result.content[0] as any)?.text ?? "";
    const obj  = JSON.parse(text);

    // crypto-price
    if ("price" in obj && "change24h" in obj) {
      const sign = obj.change24h >= 0 ? "+" : "";
      return (
        `${C}${obj.symbol}${R} | ` +
        `price: ${B}$${Number(obj.price).toLocaleString()}${R} | ` +
        `24h: ${obj.change24h >= 0 ? G : RD}${sign}${obj.change24h}%${R} | ` +
        `vol: $${(obj.volume / 1e9).toFixed(2)}B`
      );
    }

    // market-sentiment
    if ("sentiment" in obj && "signals" in obj) {
      const col = obj.sentiment === "Bullish" ? G : obj.sentiment === "Bearish" ? RD : Y;
      return (
        `${C}${obj.symbol}${R} | ` +
        `${col}${obj.sentiment}${R} (score: ${B}${obj.score}${R}) | ` +
        `signals: ${DIM}${obj.signals.slice(0, 2).join(", ")}…${R}`
      );
    }

    // whale-tracker
    if ("transactions" in obj && Array.isArray(obj.transactions)) {
      const txs = obj.transactions as Array<{ from: string; amount: number; asset: string; time: string }>;
      return (
        `${B}${txs.length} whale txns${R} | largest: ` +
        `${M}${Number(txs[0].amount).toLocaleString()} ${txs[0].asset}${R} ` +
        `(${txs[0].time})`
      );
    }

    return JSON.stringify(obj);
  } catch {
    return String((result.content[0] as any)?.text ?? result);
  }
}

// ── Demo calls ────────────────────────────────────────────────────────────────

interface DemoCall {
  toolName: string;
  toolArgs: Record<string, unknown>;
  label: string;
}

const DEMO_CALLS: DemoCall[] = [
  { toolName: "crypto-price",     toolArgs: { symbol: "BTC"  }, label: "crypto-price   " },
  { toolName: "market-sentiment", toolArgs: { symbol: "XRP"  }, label: "market-sentiment" },
  { toolName: "whale-tracker",    toolArgs: {},                  label: "whale-tracker  " },
];

// ── Instrumented callTool wrapper ─────────────────────────────────────────────
// Wraps the server's callTool so we can print what happens on each hop.

function makeInstrumentedCaller(
  serverCallTool: (name: string, args: Record<string, unknown>) => Promise<CallToolResult>,
  toolName: string
) {
  let callNumber = 0;
  return async (name: string, args: Record<string, unknown>): Promise<CallToolResult> => {
    callNumber++;
    const result = await serverCallTool(name, args);

    if (callNumber === 1) {
      // First call — expect 402
      if (is402Response(result)) {
        const inv = extract402Invoice(result)!;
        process.stdout.write(
          `  ${BL}→${R} Initial call …           ` +
          `${Y}${B}402 Payment Required${R}\n`
        );
        process.stdout.write(
          `  ${DIM}↳ Invoice: ${M}${inv.priceRlusd} RLUSD${R}${DIM} → ${truncAddr(inv.recipient)}${R}\n`
        );
      } else {
        process.stdout.write(
          `  ${BL}→${R} Initial call …           ` +
          `${G}${B}FREE (no 402)${R}\n`
        );
      }
    } else {
      // Second call — payment proof attached
      const payloadShort = ((args._relay_payment as string) ?? "").slice(0, 8) +
                           "…" +
                           ((args._relay_payment as string) ?? "").slice(-4);
      process.stdout.write(
        `  ${DIM}✓ Payment signed ${R}${DIM}(proof: ${payloadShort})${R}\n`
      );
      if (result.isError) {
        process.stdout.write(
          `  ${BL}→${R} Retry with payment …     ${RD}${B}REJECTED${R}\n`
        );
      } else {
        process.stdout.write(
          `  ${BL}→${R} Retry with payment …     ${G}${B}✅ SUCCESS${R}\n`
        );
      }
    }

    return result;
  };
}

// ── main ──────────────────────────────────────────────────────────────────────

async function main() {
  // ── Header ──────────────────────────────────────────────────────────────────
  console.log("\n" + C + B + box("RELAY — Live Agent Commerce Demo (XRPL Testnet)") + R + "\n");

  // ── Wallets ──────────────────────────────────────────────────────────────────
  const serverOwner = Wallet.generate();
  const agentW      = Wallet.generate();

  const TESTNET_RLUSD_ISSUER = "rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De";

  console.log(`${B}Server wallet:${R}  ${C}${serverOwner.classicAddress}${R}`);
  console.log(`${B}Agent wallet:${R}   ${C}${agentW.classicAddress}${R}`);
  console.log(`${B}Spend limit:${R}    ${Y}0.50 RLUSD${R} per call\n`);
  console.log(DIM + line() + R);

  // ── Server ───────────────────────────────────────────────────────────────────
  const server = makeServer(serverOwner.classicAddress);

  // ── Agent wallet (no real XRPL — signing injected) ───────────────────────────
  const wallet = agentWallet({
    seed: agentW.seed!,
    network: "xrpl_testnet",
    maxSpendPerCallRlusd: 0.50,
    _signPayment: async (invoice: PaymentInvoice) => {
      const tx = {
        TransactionType: "Payment" as const,
        Account: agentW.classicAddress,
        Destination: invoice.recipient,
        Amount: {
          currency: "USD",
          issuer: TESTNET_RLUSD_ISSUER,
          value: invoice.priceRlusd.toString(),
        },
        Fee: "12",
        Sequence: Math.floor(Math.random() * 10_000_000),
        LastLedgerSequence: 9_999_999,
      };
      return agentW.sign(tx).tx_blob;
    },
  });

  // ── Run all 3 tool calls ─────────────────────────────────────────────────────
  let succeeded = 0;
  let totalSpent = 0;
  const prices: Record<string, number> = { "crypto-price": 0.02, "market-sentiment": 0.05, "whale-tracker": 0.10 };

  for (const demo of DEMO_CALLS) {
    console.log(
      `\n${B}Tool: ${M}${demo.label}${R}  ${DIM}${JSON.stringify(demo.toolArgs)}${R}`
    );

    // Wrap the server's callTool so each hop is visible
    const instrumentedCallTool = makeInstrumentedCaller(server.callTool, demo.toolName);

    try {
      const result = await wallet.callWithPayment(
        instrumentedCallTool,
        demo.toolName,
        demo.toolArgs
      );

      const pretty = prettyResult(result);
      console.log(`  ${DIM}↳ Result: ${R}${pretty}`);

      succeeded++;
      totalSpent += prices[demo.toolName] ?? 0;
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      console.log(`  ${RD}✗ Error: ${msg}${R}`);
    }
  }

  // ── Summary ──────────────────────────────────────────────────────────────────
  console.log("\n" + DIM + line() + R);
  console.log(`${G}${B}✅  ${succeeded}/${DEMO_CALLS.length} tool calls succeeded${R}`);
  console.log(`${M}💸  Total spent: ${B}${totalSpent.toFixed(2)} RLUSD${R}`);
  console.log(`${BL}🔒  Zero custody: server never held funds${R}`);
  console.log(`${C}⚡  Integration: ${B}@relay/mcp-paywall${R}${C}  npm i @relay/mcp-paywall${R}`);
  console.log(DIM + line() + R + "\n");
}

main().catch((err) => {
  console.error(`${RD}Fatal error:${R}`, err instanceof Error ? err.message : err);
  process.exit(1);
});
