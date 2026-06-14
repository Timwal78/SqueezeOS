// Minimal D1Database shim over Node's built-in node:sqlite, so integration
// tests exercise the REAL migration SQL + queries (not a mock). Implements only
// the subset of the D1 API the code uses: prepare().bind().all()/first()/run()
// and batch().
//
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

// node:sqlite is a recent built-in with no bundled types and isn't in Vite's
// static builtin list, so load it through createRequire to bypass the bundler.
const require = createRequire(import.meta.url);
const { DatabaseSync } = require("node:sqlite") as { DatabaseSync: any };

/** Normalize node:sqlite rows: convert any BigInt integers to Number. */
function norm<T>(row: any): T {
  if (row == null) return row;
  const out: any = {};
  for (const k of Object.keys(row)) {
    const v = row[k];
    out[k] = typeof v === "bigint" ? Number(v) : v;
  }
  return out as T;
}

class D1Stmt {
  constructor(
    private db: any,
    private sql: string,
    private params: unknown[] = []
  ) {}

  bind(...args: unknown[]): D1Stmt {
    // D1 forbids undefined binds; map to null to mirror its behavior.
    return new D1Stmt(this.db, this.sql, args.map((a) => (a === undefined ? null : a)));
  }

  async all<T = unknown>(): Promise<{ results: T[] }> {
    const rows = this.db.prepare(this.sql).all(...this.params);
    return { results: rows.map((r: any) => norm<T>(r)) };
  }

  async first<T = unknown>(): Promise<T | null> {
    const row = this.db.prepare(this.sql).get(...this.params);
    return row === undefined ? null : norm<T>(row);
  }

  async run(): Promise<{ success: boolean }> {
    this.db.prepare(this.sql).run(...this.params);
    return { success: true };
  }
}

export class D1Shim {
  private db: any;
  constructor() {
    this.db = new DatabaseSync(":memory:");
    // Cloudflare D1 does not enforce foreign keys by default; match that so the
    // shim emulates the production runtime rather than stock SQLite.
    this.db.exec("PRAGMA foreign_keys = OFF;");
  }
  exec(sql: string): void {
    this.db.exec(sql);
  }
  applyMigration(path: string): void {
    this.db.exec(readFileSync(path, "utf8"));
  }
  prepare(sql: string): D1Stmt {
    return new D1Stmt(this.db, sql);
  }
  async batch(stmts: D1Stmt[]): Promise<unknown[]> {
    const out: unknown[] = [];
    for (const s of stmts) out.push(await s.run());
    return out;
  }
}

/** Build an Env-like object backed by an in-memory SQLite running the schema. */
export function makeTestEnv(): { DB: any } {
  const db = new D1Shim();
  db.applyMigration(new URL("../../migrations/0001_init.sql", import.meta.url).pathname);
  return { DB: db };
}
