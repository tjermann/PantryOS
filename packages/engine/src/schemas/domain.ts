import { z } from "zod";

export const Season = z.enum(["spring", "summer", "fall", "winter", "year_round"]);
export type Season = z.infer<typeof Season>;

export const Severity = z.enum(["allergy", "intolerance", "preference"]);
export type Severity = z.infer<typeof Severity>;

/**
 * How a restricted person is handled for a given meal.
 * "split": cook normally, pull that person's portion before the restricted
 * ingredient is added (requires the ingredient to have added_at_step set).
 */
export const Handling = z.enum(["clear", "substitute", "split", "skip"]);
export type Handling = z.infer<typeof Handling>;

export const Lifecycle = z.enum(["to_try", "probation", "keeper", "cut"]);
export type Lifecycle = z.infer<typeof Lifecycle>;

export const StoreSection = z.enum([
  "produce",
  "meat_seafood",
  "dairy",
  "pantry",
  "frozen",
  "bakery",
  "other",
]);
export type StoreSection = z.infer<typeof StoreSection>;

export const Perishability = z.enum([
  "tender_herb", // cilantro, basil, mint, dill — the usual waste
  "hardy_herb", // thyme, rosemary, ginger, scallions — keep well
  "perishable", // fresh greens, sprouts, delicate produce
  "stable", // pantry, frozen, hardy produce
]);
export type Perishability = z.infer<typeof Perishability>;

export const CanonicalItem = z.object({
  id: z.string(),
  name: z.string(),
  aliases: z.array(z.string()).default([]),
  storeSection: StoreSection,
  perishability: Perishability,
  /** Allergen classes this item belongs to. */
  allergens: z.array(z.string()).default([]),
  /**
   * Negative assertions: classes this item is explicitly NOT in, even though
   * its name suggests otherwise (coconut milk → not dairy). Used to defend
   * against regressions if anyone ever adds name-based matching.
   */
  notAllergens: z.array(z.string()).default([]),
  typicalPriceCents: z.number().int().nonnegative().optional(),
});
export type CanonicalItem = z.infer<typeof CanonicalItem>;

export const RecipeIngredient = z.object({
  canonicalItemId: z.string().nullable(),
  /** Raw text as imported; kept for display and for unmatched items. */
  raw: z.string(),
  qty: z.number().positive().nullable(),
  unit: z.string().nullable(),
  prepNote: z.string().optional(),
  isOptional: z.boolean().default(false),
  /** 1-based step index at which this ingredient enters the dish; enables Split. */
  addedAtStep: z.number().int().positive().nullable().default(null),
});
export type RecipeIngredient = z.infer<typeof RecipeIngredient>;

export const RecipeStep = z.object({
  order: z.number().int().positive(),
  text: z.string(),
  durationMin: z.number().int().nonnegative().nullable().default(null),
  /** True for hands-off time (marinating, braising, resting). */
  unattended: z.boolean().default(false),
});
export type RecipeStep = z.infer<typeof RecipeStep>;

export const Recipe = z.object({
  id: z.string(),
  title: z.string(),
  serves: z.number().int().positive(),
  publishedTimeMin: z.number().int().positive().nullable().default(null),
  protein: z.string(),
  cuisine: z.string(),
  seasons: z.array(Season).min(1),
  equipment: z.array(z.string()).default([]),
  effort: z.enum(["easy", "moderate", "involved"]),
  ingredients: z.array(RecipeIngredient),
  steps: z.array(RecipeStep),
});
export type Recipe = z.infer<typeof Recipe>;

export const DietaryRestriction = z.object({
  personId: z.string(),
  /** Either an allergen class (e.g. "dairy") or a specific canonical item id. */
  allergenClass: z.string().nullable(),
  canonicalItemId: z.string().nullable(),
  severity: Severity,
  /** Free-text nuance, e.g. "hard aged cheeses OK; coconut milk is fine". */
  notes: z.string().optional(),
});
export type DietaryRestriction = z.infer<typeof DietaryRestriction>;

export const Person = z.object({
  id: z.string(),
  name: z.string(),
  isChild: z.boolean().default(false),
  /** Children on standing meals are excluded from dinner planning. */
  eatsPlannedDinners: z.boolean().default(true),
});
export type Person = z.infer<typeof Person>;

export const HouseholdRecipeState = z.object({
  recipeId: z.string(),
  lifecycle: Lifecycle,
  lastMadeAt: z.string().nullable().default(null), // ISO date
  timesMade: z.number().int().nonnegative().default(0),
  avgRating: z.number().min(1).max(5).nullable().default(null),
  /** Measured start-to-eating, from cook sessions. Never overwrites publishedTimeMin. */
  realTimeMin: z.number().int().positive().nullable().default(null),
});
export type HouseholdRecipeState = z.infer<typeof HouseholdRecipeState>;

export const PantryItem = z.object({
  canonicalItemId: z.string(),
  qty: z.number().nonnegative(),
  unit: z.string(),
  confidence: z.enum(["confirmed", "assumed"]),
});
export type PantryItem = z.infer<typeof PantryItem>;

export const StandingOrderLine = z.object({
  canonicalItemId: z.string().nullable(),
  raw: z.string(),
  qty: z.number().positive().nullable().default(null),
  unit: z.string().nullable().default(null),
  reason: z.string().optional(), // e.g. "kids' standing meals", "restock"
});
export type StandingOrderLine = z.infer<typeof StandingOrderLine>;

export const Household = z.object({
  id: z.string(),
  name: z.string(),
  /** Hemisphere + climate driver for seasonality; v1: month→season table by region. */
  region: z.enum(["northern", "southern"]).default("northern"),
  people: z.array(Person),
  restrictions: z.array(DietaryRestriction),
  equipment: z.array(z.string()).default([]),
  dinnersPerWeek: z.number().int().min(1).max(7).default(5),
  budgetCentsWeekly: z.number().int().positive().nullable().default(null),
  budgetEnabled: z.boolean().default(false),
});
export type Household = z.infer<typeof Household>;
