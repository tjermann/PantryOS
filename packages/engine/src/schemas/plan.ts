import { z } from "zod";
import { Handling } from "./domain.js";

/**
 * Strict output schema for the Claude planning call.
 * Everything here is a PROPOSAL — deterministic validators run before
 * anything is shown to the user or saved.
 */
export const PersonHandling = z.object({
  personId: z.string(),
  handling: Handling,
  /** Required when handling === "substitute". */
  substituteItemId: z.string().nullable().default(null),
  substituteNote: z.string().nullable().default(null),
});
export type PersonHandling = z.infer<typeof PersonHandling>;

export const PlanEntryProposal = z.object({
  recipeId: z.string(),
  /** ISO date the dish is scheduled for. */
  date: z.string(),
  servings: z.number().int().positive(),
  rationale: z.string(),
  personHandling: z.array(PersonHandling),
});
export type PlanEntryProposal = z.infer<typeof PlanEntryProposal>;

export const PlanProposal = z.object({
  entries: z.array(PlanEntryProposal),
  /** Recipe-id pairs sharing perishables, with the shared item named. */
  perishablePairings: z
    .array(
      z.object({
        canonicalItemId: z.string(),
        recipeIds: z.array(z.string()).min(2),
      }),
    )
    .default([]),
  treatSuggestions: z.array(z.string()).default([]),
  notes: z.string().nullable().default(null),
});
export type PlanProposal = z.infer<typeof PlanProposal>;

/** Machine-readable validator output, fed back to Claude on repair loops. */
export const Violation = z.object({
  code: z.enum([
    "allergy_hard_fail",
    "invalid_substitute",
    "split_not_feasible",
    "out_of_season",
    "missing_equipment",
    "lifecycle_cut",
    "back_to_back_similar",
    "protein_overload",
    "effort_stacking",
    "recent_repeat",
    "unknown_recipe",
    "orphaned_perishable",
    "over_budget",
  ]),
  severity: z.enum(["error", "warning"]),
  entryIndex: z.number().int().nonnegative().nullable(),
  message: z.string(),
});
export type Violation = z.infer<typeof Violation>;
