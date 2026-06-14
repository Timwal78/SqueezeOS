// x402 payment gate (HTTP 402). Implements the Coinbase / x402.org flow:
//
//   1. Client GETs a gated resource with no payment.
//   2. We reply 402 + { x402Version, accepts: [PaymentRequirements] }.
//   3. Client signs a USDC-on-Base payment and retries with `X-PAYMENT` (b64).
//   4. We POST it to the facilitator /verify, then /settle, and on success
//      serve the resource with an `X-PAYMENT-RESPONSE` header (settlement tx).
//
// ZERO CUSTODY: funds move client -> payTo (the analyst or protocol wallet)
// directly on-chain via the facilitator settle call. This worker never holds a
// key and never touches the money.
//
// Spec: https://www.x402.org  •  Facilitator: X402_FACILITATOR_URL

import type { Context, MiddlewareHandler } from "hono";
import type { Env } from "../types.js";

const USDC_DECIMALS = 6;

export interface PaymentTerms {
  /** human price in USDC, e.g. 0.05 */
  priceUsdc: number;
  /** absolute resource URL being purchased */
  resource: string;
  description: string;
  /** receiving wallet (Base). Defaults to the protocol wallet X402_PAY_TO. */
  payTo?: string;
}

export interface SettledPayment {
  payer: string | null;
  txHash: string | null;
  amountUsdc: number;
}

/** What the handler reads off the context once payment succeeds. */
export const PAYMENT_CTX_KEY = "x402Payment";

/** Constant-time string compare (avoids timing side-channels on bearer tokens). */
function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

function toAtomic(usdc: number): string {
  return BigInt(Math.round(usdc * 10 ** USDC_DECIMALS)).toString();
}

function buildRequirements(env: Env, terms: PaymentTerms, payTo: string) {
  return {
    scheme: "exact",
    network: env.X402_NETWORK,
    maxAmountRequired: toAtomic(terms.priceUsdc),
    resource: terms.resource,
    description: terms.description,
    mimeType: "application/json",
    payTo,
    maxTimeoutSeconds: 120,
    asset: env.X402_ASSET,
    extra: { name: "USDC", version: "2" }
  };
}

/**
 * Build a Hono middleware that requires an x402 payment. `terms` may be static
 * or computed per-request (e.g. per-estimate pricing).
 */
export function requirePayment(
  terms:
    | PaymentTerms
    | ((c: Context<{ Bindings: Env }>) => PaymentTerms | Promise<PaymentTerms>)
): MiddlewareHandler<{ Bindings: Env }> {
  return async (c, next) => {
    const env = c.env;
    const resolved = typeof terms === "function" ? await terms(c) : terms;

    // Free resources skip the gate entirely.
    if (resolved.priceUsdc <= 0) {
      c.set(PAYMENT_CTX_KEY as never, {
        payer: null,
        txHash: null,
        amountUsdc: 0
      } as never);
      return next();
    }

    const payTo = resolved.payTo ?? env.X402_PAY_TO;
    if (!payTo) {
      // Mirrors SqueezeOS's ERR_SECRET_NOT_CONFIGURED posture: fail closed.
      return c.json(
        { error: "ERR_PAYTO_NOT_CONFIGURED", message: "X402_PAY_TO unset" },
        503
      );
    }

    const header = c.req.header("X-PAYMENT");
    const requirements = buildRequirements(env, resolved, payTo);

    // Dev/local bypass: ONLY honored when ENVIRONMENT === "dev" AND the secret
    // is configured. In production this branch is dead even if the secret leaks,
    // so a paywall can never be opened by a static bearer on the live worker.
    // Constant-time compare to avoid leaking the token via response timing.
    if (
      env.ENVIRONMENT === "dev" &&
      env.X402_DEV_BYPASS_TOKEN &&
      header &&
      timingSafeEqual(header, env.X402_DEV_BYPASS_TOKEN)
    ) {
      c.set(PAYMENT_CTX_KEY as never, {
        payer: "0xdev",
        txHash: "dev-bypass",
        amountUsdc: resolved.priceUsdc
      } as never);
      return next();
    }

    if (!header) {
      return c.json(
        {
          x402Version: 1,
          error: "X-PAYMENT header required",
          accepts: [requirements]
        },
        402
      );
    }

    // Decode the client payload and ask the facilitator to verify then settle.
    let paymentPayload: unknown;
    try {
      paymentPayload = JSON.parse(atob(header));
    } catch {
      return c.json(
        {
          x402Version: 1,
          error: "Malformed X-PAYMENT (expected base64 JSON)",
          accepts: [requirements]
        },
        402
      );
    }

    const verify = await facilitator(env, "verify", {
      x402Version: 1,
      paymentPayload,
      paymentRequirements: requirements
    });
    if (!verify.ok || verify.body?.isValid !== true) {
      return c.json(
        {
          x402Version: 1,
          error: verify.body?.invalidReason ?? "payment verification failed",
          accepts: [requirements]
        },
        402
      );
    }

    const settle = await facilitator(env, "settle", {
      x402Version: 1,
      paymentPayload,
      paymentRequirements: requirements
    });
    if (!settle.ok || settle.body?.success !== true) {
      return c.json(
        {
          x402Version: 1,
          error: settle.body?.errorReason ?? "settlement failed",
          accepts: [requirements]
        },
        402
      );
    }

    const payment: SettledPayment = {
      payer: settle.body?.payer ?? verify.body?.payer ?? null,
      txHash: settle.body?.transaction ?? null,
      amountUsdc: resolved.priceUsdc
    };
    c.set(PAYMENT_CTX_KEY as never, payment as never);

    // Surface the settlement to the client per x402 spec.
    c.header(
      "X-PAYMENT-RESPONSE",
      btoa(JSON.stringify({ success: true, transaction: payment.txHash }))
    );
    return next();
  };
}

async function facilitator(
  env: Env,
  path: "verify" | "settle",
  body: unknown
): Promise<{ ok: boolean; body: any }> {
  try {
    const res = await fetch(`${env.X402_FACILITATOR_URL}/${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
    const parsed = await res.json().catch(() => null);
    return { ok: res.ok, body: parsed };
  } catch (e) {
    return { ok: false, body: { error: String(e) } };
  }
}

export function readPayment(c: Context): SettledPayment {
  return (
    (c.get(PAYMENT_CTX_KEY as never) as SettledPayment | undefined) ?? {
      payer: null,
      txHash: null,
      amountUsdc: 0
    }
  );
}
