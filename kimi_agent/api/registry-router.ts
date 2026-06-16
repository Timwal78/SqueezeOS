import { z } from "zod";
import { eq, desc, count } from "drizzle-orm";
import { createRouter, publicQuery } from "./middleware";
import { getDb } from "./queries/connection";
import { registries, broadcasts, activityLog } from "@db/schema";

export const registryRouter = createRouter({
  list: publicQuery.query(async () => {
    const db = getDb();
    return db.select().from(registries).orderBy(desc(registries.discoveredAt));
  }),

  get: publicQuery
    .input(z.object({ id: z.number() }))
    .query(async ({ input }) => {
      const db = getDb();
      const [registry] = await db
        .select()
        .from(registries)
        .where(eq(registries.id, input.id));
      return registry ?? null;
    }),

  create: publicQuery
    .input(
      z.object({
        name: z.string().min(1),
        url: z.string().url(),
        type: z.enum(["llms_txt", "mcp_hub", "anp_registry", "agent_dir", "github_repo", "other"]).default("other"),
        status: z.enum(["active", "pending", "failed", "disabled"]).default("pending"),
        metadata: z.string().optional(),
      })
    )
    .mutation(async ({ input }) => {
      const db = getDb();
      const [registry] = await db.insert(registries).values(input).$returningId();
      await db.insert(activityLog).values({
        module: "registry",
        level: "success",
        message: `New registry discovered: ${input.name}`,
        metadata: JSON.stringify({ registryId: registry.id, url: input.url }),
      });
      return registry;
    }),

  update: publicQuery
    .input(
      z.object({
        id: z.number(),
        name: z.string().min(1).optional(),
        url: z.string().url().optional(),
        type: z.enum(["llms_txt", "mcp_hub", "anp_registry", "agent_dir", "github_repo", "other"]).optional(),
        status: z.enum(["active", "pending", "failed", "disabled"]).optional(),
        metadata: z.string().optional(),
      })
    )
    .mutation(async ({ input }) => {
      const db = getDb();
      const { id, ...data } = input;
      await db.update(registries).set(data).where(eq(registries.id, id));
      return { success: true };
    }),

  delete: publicQuery
    .input(z.object({ id: z.number() }))
    .mutation(async ({ input }) => {
      const db = getDb();
      await db.delete(registries).where(eq(registries.id, input.id));
      return { success: true };
    }),

  // Broadcasts
  listBroadcasts: publicQuery
    .input(z.object({ registryId: z.number().optional() }).optional())
    .query(async ({ input }) => {
      const db = getDb();
      let query = db.select().from(broadcasts).orderBy(desc(broadcasts.submittedAt));
      if (input?.registryId) {
        query = query.where(eq(broadcasts.registryId, input.registryId)) as typeof query;
      }
      return query;
    }),

  createBroadcast: publicQuery
    .input(
      z.object({
        registryId: z.number(),
        payloadType: z.enum(["agents_json", "capability_card", "llms_txt", "mcp_manifest", "anp_profile"]),
        endpoint: z.string().optional(),
      })
    )
    .mutation(async ({ input }) => {
      const db = getDb();
      const [broadcast] = await db.insert(broadcasts).values({
        ...input,
        status: "pending",
      }).$returningId();

      let status = "submitted";
      try {
        const targetRegistry = await db.select().from(registries).where(eq(registries.id, input.registryId));
        if (targetRegistry.length > 0 && targetRegistry[0].url) {
           const res = await fetch(targetRegistry[0].url, { method: "HEAD" }).catch(() => null);
           if (!res || !res.ok) {
             status = "failed";
           }
        }
      } catch (e) {
        status = "failed";
      }

      await db.update(broadcasts)
        .set({ status, completedAt: new Date() })
        .where(eq(broadcasts.id, broadcast.id));

      await db.insert(activityLog).values({
        module: "registry",
        level: "success",
        message: `Capability card seeded to registry #${input.registryId}`,
        metadata: JSON.stringify({ broadcastId: broadcast.id, payloadType: input.payloadType }),
      });

      return broadcast;
    }),

  // Stats
  stats: publicQuery.query(async () => {
    const db = getDb();
    const [registryCount] = await db.select({ count: count() }).from(registries);
    const [broadcastCount] = await db.select({ count: count() }).from(broadcasts);
    const [activeCount] = await db
      .select({ count: count() })
      .from(registries)
      .where(eq(registries.status, "active"));

    const typeBreakdown = await db
      .select({
        type: registries.type,
        count: count(),
      })
      .from(registries)
      .groupBy(registries.type);

    return {
      totalRegistries: registryCount?.count ?? 0,
      totalBroadcasts: broadcastCount?.count ?? 0,
      activeRegistries: activeCount?.count ?? 0,
      typeBreakdown,
    };
  }),
});
