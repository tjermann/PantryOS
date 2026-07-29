import type {
  CanonicalItem,
  DietaryRestriction,
  Person,
  Recipe,
} from "../schemas/domain.js";
import type { PlanEntryProposal, Violation } from "../schemas/plan.js";
import { itemInAllergenClass, lookupItem } from "./ontology.js";

/**
 * The deterministic allergen backstop.
 *
 * Runs over every proposed plan entry AFTER the LLM, regardless of what the
 * LLM claimed about safety. Policy:
 *  - severity "allergy": any conflicting ingredient is an ERROR unless the
 *    proposed handling provably resolves it (valid substitute for that exact
 *    ingredient, feasible split point, or skip). Unknown ingredients
 *    (unmatched to the ontology) are ALSO errors for allergy severity — we
 *    fail closed.
 *  - severity "intolerance": conflicts must be handled, but unknown
 *    ingredients produce warnings rather than errors.
 *  - severity "preference": conflicts produce warnings only.
 */
export interface BackstopInput {
  entry: PlanEntryProposal;
  entryIndex: number;
  recipe: Recipe;
  people: Person[];
  restrictions: DietaryRestriction[];
  items: ReadonlyMap<string, CanonicalItem>;
}

function ingredientConflicts(
  recipe: Recipe,
  restriction: DietaryRestriction,
  items: ReadonlyMap<string, CanonicalItem>,
): { conflicting: number[]; unknown: number[] } {
  const conflicting: number[] = [];
  const unknown: number[] = [];
  recipe.ingredients.forEach((ing, i) => {
    if (ing.isOptional) return;
    if (restriction.canonicalItemId) {
      if (ing.canonicalItemId === restriction.canonicalItemId) conflicting.push(i);
      else if (ing.canonicalItemId === null) unknown.push(i);
      return;
    }
    if (restriction.allergenClass) {
      const item = lookupItem(items, ing.canonicalItemId);
      const membership = itemInAllergenClass(item, restriction.allergenClass);
      if (membership === "member") conflicting.push(i);
      else if (membership === "unknown") unknown.push(i);
    }
  });
  return { conflicting, unknown };
}

/**
 * A split is feasible only if EVERY conflicting ingredient enters the dish at
 * a known step > 1 — i.e. there is a real moment to pull a clean portion.
 */
export function splitFeasible(recipe: Recipe, conflictingIdx: number[]): boolean {
  if (conflictingIdx.length === 0) return true;
  return conflictingIdx.every((i) => {
    const ing = recipe.ingredients[i];
    return ing !== undefined && ing.addedAtStep !== null && ing.addedAtStep > 1;
  });
}

export function runAllergenBackstop(input: BackstopInput): Violation[] {
  const { entry, entryIndex, recipe, people, restrictions, items } = input;
  const violations: Violation[] = [];

  for (const person of people) {
    if (!person.eatsPlannedDinners) continue;
    const personRestrictions = restrictions.filter((r) => r.personId === person.id);
    for (const restriction of personRestrictions) {
      const { conflicting, unknown } = ingredientConflicts(recipe, restriction, items);
      const handling = entry.personHandling.find((h) => h.personId === person.id);
      const isAllergy = restriction.severity === "allergy";

      // Unknown ingredients: fail closed for allergies, warn otherwise.
      if (unknown.length > 0 && restriction.allergenClass) {
        violations.push({
          code: "allergy_hard_fail",
          severity: isAllergy ? "error" : "warning",
          entryIndex,
          message: `${recipe.title}: ${unknown.length} ingredient(s) not matched to the ontology (${unknown
            .map((i) => recipe.ingredients[i]?.raw)
            .filter(Boolean)
            .join("; ")}) — cannot verify against ${person.name}'s ${restriction.severity} (${restriction.allergenClass}).`,
        });
      }

      if (conflicting.length === 0) continue;

      const conflictNames = conflicting
        .map((i) => recipe.ingredients[i]?.raw)
        .filter(Boolean)
        .join("; ");
      const baseMsg = `${recipe.title}: contains ${conflictNames}, conflicting with ${person.name}'s ${restriction.severity}`;

      if (restriction.severity === "preference") {
        if (!handling || handling.handling === "clear") {
          violations.push({
            code: "allergy_hard_fail",
            severity: "warning",
            entryIndex,
            message: `${baseMsg} (preference — flag to user).`,
          });
        }
        continue;
      }

      // allergy / intolerance: handling must exist and actually resolve it.
      const errSeverity = isAllergy ? ("error" as const) : ("warning" as const);
      if (!handling || handling.handling === "clear") {
        violations.push({
          code: "allergy_hard_fail",
          severity: errSeverity,
          entryIndex,
          message: `${baseMsg}, but handling is missing or "clear".`,
        });
        continue;
      }
      if (handling.handling === "substitute") {
        const sub = handling.substituteItemId
          ? items.get(handling.substituteItemId)
          : undefined;
        const subOk =
          sub !== undefined &&
          (restriction.allergenClass
            ? itemInAllergenClass(sub, restriction.allergenClass) === "non_member"
            : sub.id !== restriction.canonicalItemId);
        if (!subOk) {
          violations.push({
            code: "invalid_substitute",
            severity: errSeverity,
            entryIndex,
            message: `${baseMsg}; proposed substitute is missing, unknown, or itself conflicting.`,
          });
        }
        continue;
      }
      if (handling.handling === "split") {
        if (!splitFeasible(recipe, conflicting)) {
          violations.push({
            code: "split_not_feasible",
            severity: errSeverity,
            entryIndex,
            message: `${baseMsg}; split proposed but a conflicting ingredient enters at step 1 or an unknown step — no clean pull point.`,
          });
        }
        continue;
      }
      // handling === "skip" resolves the conflict for that person.
    }
  }
  return violations;
}
