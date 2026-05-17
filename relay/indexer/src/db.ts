/**
 * Minimal Postgres pool for the indexer.
 * Financial source of truth is XRPL — this DB is an idempotent cache.
 * All upserts use ON CONFLICT DO NOTHING / DO UPDATE to be replay-safe.
 */

import { Pool, QueryResult } from "pg";
import * as dotenv from "dotenv";

dotenv.config();

let _pool: Pool | null = null;

export function getPool(): Pool {
  if (!_pool) {
    _pool = new Pool({ connectionString: process.env.DATABASE_URL });
  }
  return _pool;
}

export async function query<T extends Record<string, unknown>>(
  sql: string,
  params?: unknown[]
): Promise<T[]> {
  const result: QueryResult<T> = await getPool().query(sql, params);
  return result.rows;
}

export async function queryOne<T extends Record<string, unknown>>(
  sql: string,
  params?: unknown[]
): Promise<T | null> {
  const rows = await query<T>(sql, params);
  return rows[0] ?? null;
}
