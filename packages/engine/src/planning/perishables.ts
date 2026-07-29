import type { CanonicalItem, Recipe } from "../schemas/domain.js";
import type { Violation } from "../schemas/plan.js";

/**
 * Perishable-overlap analysis. The planner should deliberately cluster dishes
 * that share short-lived ingredients (tender herbs above all) so one bunch is
 * consumed across two or more meals. Code computes the overlap sets; Claude
 * uses them when composing; this validator warns when a tender herb ends up
 * single-use ("orphaned").
 */
export interface PerishableUsage {
  canonicalItemId: string;
  itemName: string;
  perishability: "tender_herb" | "perishable";
  recipeIds: string[];
}

export function perishableUsage(
  recipes: Recipe[],
  items: ReadonlyMap<string, CanonicalItem>,
): PerishableUsage[] {
  const usage = new Map<string, Set<string>>();
  for (const recipe of recipes) {
    for (const ing of recipe.ingredients) {
      if (!ing.canonicalItemId) continue;
      const item = items.get(ing.canonicalItemId);
      if (!item) continue;
      if (item.perishability === "tender_herb" || item.perishability === "perishable") {
        const set = usage.get(item.id) ?? new Set<string>();
        set.add(recipe.id);
        usage.set(item.id, set);
      }
    }
  }
  return [...usage.entries()].map(([id, recipeIds]) => {
    const item = items.get(id)!;
    return {
      canonicalItemId: id,
      itemName: item.name,
      perishability: item.perishability as "tender_herb" | "perishable",
      recipeIds: [...recipeIds],
    };
  });
}

/** Warn on tender herbs used by exactly one planned dish. */
export function orphanedPerishables(
  recipes: Recipe[],
  items: ReadonlyMap<string, CanonicalItem>,
): Violation[] {
  return perishableUsage(recipes, items)
    .filter((u) => u.perishability === "tender_herb" && u.recipeIds.length === 1)
    .map((u) => ({
      code: "orphaned_perishable" as const,
      severity: "warning" as const,
      entryIndex: null,
      message: `${u.itemName} is used by only one dish this week — suggest a second dish that finishes it.`,
    }));
}
