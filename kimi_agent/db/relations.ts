import { relations } from "drizzle-orm";
import { registries, broadcasts, outboundTargets, engagements } from "./schema";

export const registryRelations = relations(registries, ({ many }) => ({
  broadcasts: many(broadcasts),
}));

export const broadcastRelations = relations(broadcasts, ({ one }) => ({
  registry: one(registries, {
    fields: [broadcasts.registryId],
    references: [registries.id],
  }),
}));

export const outboundTargetRelations = relations(outboundTargets, ({ many }) => ({
  engagements: many(engagements),
}));

export const engagementRelations = relations(engagements, ({ one }) => ({
  target: one(outboundTargets, {
    fields: [engagements.targetId],
    references: [outboundTargets.id],
  }),
}));
