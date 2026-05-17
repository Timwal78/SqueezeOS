import { Client, Wallet } from "xrpl";
import { Network, RelayConfig } from "./types";
import { XRPL_NODES } from "./constants";

// Singleton client pool — one connection per network per process
const clients = new Map<Network, Client>();

export async function getClient(network: Network, customNode?: string): Promise<Client> {
  const existing = clients.get(network);
  if (existing?.isConnected()) return existing;

  const url = customNode ?? XRPL_NODES[network];
  const client = new Client(url);
  await client.connect();
  clients.set(network, client);
  return client;
}

export async function disconnectAll(): Promise<void> {
  const pending = Array.from(clients.values())
    .filter((c) => c.isConnected())
    .map((c) => c.disconnect());
  await Promise.all(pending);
  clients.clear();
}

export function dropsToRlusd(drops: string): number {
  return parseFloat(drops) / 1_000_000;
}

export function rlusdToDrops(amount: number): string {
  return (BigInt(Math.round(amount * 1_000_000))).toString();
}

export function xrpToDrops(xrp: number): string {
  return (BigInt(Math.round(xrp * 1_000_000))).toString();
}

export function dropsToXrp(drops: string): number {
  return parseInt(drops, 10) / 1_000_000;
}

// Validate XRPL address format (classic address, starts with 'r', 25-34 chars)
export function isValidXrplAddress(address: string): boolean {
  return /^r[1-9A-HJ-NP-Za-km-z]{24,33}$/.test(address);
}

export function makeError(code: string, message: string, details?: unknown): Error {
  const err = new Error(message) as Error & { code: string; details?: unknown };
  err.code = code;
  err.details = details;
  return err;
}
