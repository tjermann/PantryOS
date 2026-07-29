import type {
  CanonicalItem,
  Household,
  HouseholdRecipeState,
  Recipe,
} from "../schemas/domain.js";
import type { PlanProposal, Violation } from "../schemas/plan.js";
import { runAllergenBackstop } from "../allergen/backstop.js";
import { orphanedPerishables } from "./perishables.js";
import { validateVariety, type VarietyRules, DEFAULT_VARIETY_RULES } from "./variety.js";

export interface ValidatePlanInput {
  proposal: PlanProposal;
  /** Candidate recipes the proposal was allowed to draw from. */
  candidates: ReadonlyMap<string, Recipe>;
  states: ReadonlyMap<string, HouseholdRecipeState>;
  items: ReadonlyMap<string, CanonicalItem>;
  household: Household;
  varietyRules?: VarietyRules;
}

export interface ValidationResult {
  ok: boolean;
  errors: Violation[];
  warnings: Violation[];
}

/**
 * Deterministic validation of a Claude plan proposal. Errors (allergy hard
 * fails above all) mean the plan must not be shown or saved as-is: re-prompt
 * with the violation list, and if the violation persists, drop/replace the
 * offending entry from the pre-filtered safe pool in code.
 */
export function validatePlan(input: ValidatePlanInput): ValidationResult {
  const violations: Violation[] = [];

  input.proposal.entries.forEach((entry, entryIndex) => {
    const recipe = input.candidates.get(entry.recipeId);
    if (!recipe) return; // reported as unknown_recipe by validateVariety
    violations.push(
      ...runAllergenBackstop({
        entry,
        entryIndex,
        recipe,
        people: input.household.people,
        restrictions: input.household.restrictions,
        items: input.items,
      }),
    );
  });

  violations.push(
    ...validateVariety(
      input.proposal.entries,
      input.candidates,
      input.states,
      input.varietyRules ?? DEFAULT_VARIETY_RULES,
    ),
  );

  const plannedRecipes = input.proposal.entries
    .map((e) => input.candidates.get(e.recipeId))
    .filter((r): r is Recipe => r !== undefined);
  violations.push(...orphanedPerishables(plannedRecipes, input.items));

  const errors = violations.filter((v) => v.severity === "error");
  const warnings = violations.filter((v) => v.severity === "warning");
  return { ok: errors.length === 0, errors, warnings };
}
