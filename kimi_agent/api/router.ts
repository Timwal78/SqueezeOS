import { authRouter } from "./auth-router";
import { registryRouter } from "./registry-router";
import { honeytrapRouter } from "./honeytrap-router";
import { hustlerRouter } from "./hustler-router";
import { dashboardRouter, activityRouter } from "./dashboard-router";
import { createRouter, publicQuery } from "./middleware";

export const appRouter = createRouter({
  ping: publicQuery.query(() => ({ ok: true, ts: Date.now() })),
  auth: authRouter,
  registry: registryRouter,
  honeytrap: honeytrapRouter,
  hustler: hustlerRouter,
  dashboard: dashboardRouter,
  activity: activityRouter,
});

export type AppRouter = typeof appRouter;
