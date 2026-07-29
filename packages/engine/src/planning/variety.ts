import type { HouseholdRecipeState, Recipe } from "../schemas/domain.js";
import type { PlanEntryProposal, Violation } from "../schemas/plan.js";

export interface VarietyRules {
  /** Max meals sharing one protein per week. Source rule: "not three chicken dinners". */
  maxSameProteinPerWeek: number;
  /** Disallow same cuisine on consecutive nights ("no back-to-back pasta"). */
  noBackToBackCuisine: boolean;
  /** Disallow "involved" effort on consecutive nights. */
  noConsecutiveInvolved: boolean;
  /** Warn if a recipe was made within this many days ("last made" recency). */
  repeatWindowDays: number;
}

export const DEFAULT_VARIETY_RULES: VarietyRules = {
  maxSameProteinPerWeek: 2,
  noBackToBackCuisine: true,
  noConsecutiveInvolved: true,
  repeatWindowDays: 21,
};

const DAY_MS = 24 * 60 * 60 * 1000;

export function validateVariety(
  entries: PlanEntryProposal[],
  recipes: ReadonlyMap<string, Recipe>,
  states: ReadonlyMap<string, HouseholdRecipeState>,
  rules: VarietyRules = DEFAULT_VARIETY_RULES,
): Violation[] {
  const violations: Violation[] = [];
  const sorted = entries
    .map((entry, entryIndex) => ({ entry, entryIndex, recipe: recipes.get(entry.recipeId) }))
    .sort((a, b) => a.entry.date.localeCompare(b.entry.date));

  for (const { entry, entryIndex, recipe } of sorted) {
    if (!recipe) {
      violations.push({
        code: "unknown_recipe",
        severity: "error",
        entryIndex,
        message: `Proposed recipe ${entry.recipeId} is not in the candidate set.`,
      });
    }
  }

  const known = sorted.filter(
    (x): x is typeof x & { recipe: Recipe } => x.recipe !== undefined,
  );

  // Protein cap across the week.
  const byProtein = new Map<string, number[]>();
  for (const { entryIndex, recipe } of known) {
    const list = byProtein.get(recipe.protein) ?? [];
    list.push(entryIndex);
    byProtein.set(recipe.protein, list);
  }
  for (const [protein, idxs] of byProtein) {
    if (idxs.length > rules.maxSameProteinPerWeek) {
      violations.push({
        code: "protein_overload",
        severity: "warning",
        entryIndex: idxs[idxs.length - 1] ?? null,
        message: `${idxs.length} ${protein} dinners in one week (max ${rules.maxSameProteinPerWeek}).`,
      });
    }
  }

  // Consecutive-night rules.
  for (let i = 1; i < known.length; i++) {
    const prev = known[i - 1]!;
    const curr = known[i]!;
    const gapDays =
      (Date.parse(curr.entry.date) - Date.parse(prev.entry.date)) / DAY_MS;
    if (gapDays !== 1) continue;
    if (rules.noBackToBackCuisine && prev.recipe.cuisine === curr.recipe.cuisine) {
      violations.push({
        code: "back_to_back_similar",
        severity: "warning",
        entryIndex: curr.entryIndex,
        message: `${prev.recipe.title} and ${curr.recipe.title} are back-to-back ${curr.recipe.cuisine} nights.`,
      });
    }
    if (
      rules.noConsecutiveInvolved &&
      prev.recipe.effort === "involved" &&
      curr.recipe.effort === "involved"
    ) {
      violations.push({
        code: "effort_stacking",
        severity: "warning",
        entryIndex: curr.entryIndex,
        message: `Two demanding recipes on consecutive nights (${prev.recipe.title} → ${curr.recipe.title}).`,
      });
    }
  }

  // Cross-week repeat window via last-made dates.
  for (const { entry, entryIndex, recipe } of known) {
    const lastMade = states.get(recipe.id)?.lastMadeAt;
    if (!lastMade) continue;
    const gapDays = (Date.parse(entry.date) - Date.parse(lastMade)) / DAY_MS;
    if (gapDays >= 0 && gapDays < rules.repeatWindowDays) {
      violations.push({
        code: "recent_repeat",
        severity: "warning",
        entryIndex,
        message: `${recipe.title} was last made ${Math.round(gapDays)} days before this plan date (window: ${rules.repeatWindowDays}).`,
      });
    }
  }

  return violations;
}
