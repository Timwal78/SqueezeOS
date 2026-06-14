// Small response/serialization helpers. Keeps handlers terse and consistent.

export function uuid(): string {
  return crypto.randomUUID();
}

export function now(): number {
  return Math.floor(Date.now() / 1000);
}

/** UTC calendar day "YYYY-MM-DD" — used for streak accounting. */
export function utcDay(ts: number = Date.now()): string {
  return new Date(ts).toISOString().slice(0, 10);
}

export function lower(addr: string): string {
  return addr.trim().toLowerCase();
}

/** Basic 0x-address shape check (not a checksum verify — agents send lowercase). */
export function isAddress(addr: unknown): addr is string {
  return typeof addr === "string" && /^0x[0-9a-fA-F]{40}$/.test(addr.trim());
}

export const CORS_HEADERS: Record<string, string> = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
  "Access-Control-Allow-Headers":
    "Content-Type, X-PAYMENT, X-AGENT-ID, Authorization"
};
