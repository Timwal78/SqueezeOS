/**
 * agentWallet() — client-side autonomous XRPL signer.
 *
 * Usage:
 *   const wallet = agentWallet({
 *     seed: process.env.AGENT_SEED!,
 *     network: "xrpl_testnet",
 *     maxSpendPerCallRlusd: 1.0,
 *   });
 *
 *   // Transparent auto-pay: catches 402, pays, retries
 *   const result = await wallet.callWithPayment(
 *     (name, args) => client.callTool({ name, arguments: args }),
 *     "fetch-data",
 *     { query: "latest prices" }
 *   );
 *
 * SECURITY INVARIANTS (enforced by this module):
 *   - `seed` is accessed only at call time — never stored after wallet construction
 *   - `seed` is never logged, serialised, or included in any network request
 *   - Spending is hard-capped at `maxSpendPerCallRlusd` per call
 *   - Reputation gate: if `relayApiUrl` + `minServerReputationScore` are set,
 *     the server's on-chain score is verified before any payment is signed
 */
import type { AgentWalletConfig, CallToolResult } from "./types";
export type CallToolFn = (name: string, args: Record<string, unknown>) => Promise<CallToolResult>;
export interface AgentWallet {
    /** The XRPL address of the agent's wallet. */
    readonly address: string;
    /**
     * Call an MCP tool, automatically handling 402 challenges.
     *
     * Flow:
     *   1. Call tool without payment
     *   2. If 402: verify price ≤ limit, optional reputation check, sign + retry
     *   3. If still 402 after retry: throw
     */
    callWithPayment(callTool: CallToolFn, toolName: string, toolArgs: Record<string, unknown>): Promise<CallToolResult>;
}
export declare function agentWallet(config: AgentWalletConfig): AgentWallet;
//# sourceMappingURL=agent-wallet.d.ts.map