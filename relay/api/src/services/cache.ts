/**
 * Redis cache service — <20ms loyalty endpoint SLA.
 *
 * Gracefully degrades: if Redis is unavailable the `getOrCompute` helper
 * falls through to the database query without throwing.  Cache misses are
 * silent — callers never need to handle cache errors.
 *
 * TTL guidelines:
 *   Loyalty status   : 60 s  (frequent reads, rarely changes)
 *   Analytics stats  : 60 s
 *   Leaderboard      : 300 s (5 min)
 */

import { createClient, RedisClientType } from "redis";
import { logger } from "./logger";

let _client: RedisClientType | null = null;
let _connecting = false;
let _unavailable = false; // latched after first permanent failure

async function getClient(): Promise<RedisClientType | null> {
  if (_unavailable) return null;
  if (_client?.isReady) return _client;
  if (_connecting) return null;

  const url = process.env.REDIS_URL;
  if (!url) return null;

  _connecting = true;
  try {
    const client = createClient({ url }) as RedisClientType;
    client.on("error", (err: unknown) => {
      logger.warn("Redis error — cache disabled", { err });
      _unavailable = true;
      _client = null;
    });
    await client.connect();
    _client = client;
    logger.info("Redis cache connected");
  } catch (err) {
    logger.warn("Redis unavailable — running without cache", { err });
    _unavailable = true;
  } finally {
    _connecting = false;
  }

  return _client;
}

export async function cacheGet<T>(key: string): Promise<T | null> {
  const client = await getClient();
  if (!client) return null;
  try {
    const raw = await client.get(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

export async function cacheSet(
  key: string,
  value: unknown,
  ttlSeconds: number
): Promise<void> {
  const client = await getClient();
  if (!client) return;
  try {
    await client.set(key, JSON.stringify(value), { EX: ttlSeconds });
  } catch {
    // non-fatal
  }
}

export async function cacheDel(key: string): Promise<void> {
  const client = await getClient();
  if (!client) return;
  try {
    await client.del(key);
  } catch {
    // non-fatal
  }
}

/**
 * Cache-aside helper.  If the key exists in Redis, returns the cached value.
 * Otherwise calls `fn()`, caches the result, and returns it.
 * Never throws — on any cache error falls through to `fn()`.
 */
export async function getOrCompute<T>(
  key: string,
  fn: () => Promise<T>,
  ttlSeconds: number
): Promise<T> {
  const cached = await cacheGet<T>(key);
  if (cached !== null) return cached;
  const value = await fn();
  await cacheSet(key, value, ttlSeconds);
  return value;
}
