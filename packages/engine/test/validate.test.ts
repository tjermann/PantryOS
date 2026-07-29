import { describe, expect, it } from "vitest";
import { validatePlan, orphanedPerishables, type PlanProposal } from "../src/index.js";
import { ITEMS, ing, makeHousehold, makeRecipe, stateMap } from "./fixtures.js";

describe("validatePlan", () => {
  const safe = makeRecipe({
    id: "safe",
    ingredients: [ing("chicken-thigh", "1 lb chicken", 1, "lb"), ing("cilantro", "cilantro", 1, "bunch")],
  });
  const dairy = makeRecipe({
    id: "dairy-dish",
    protein: "pork",
    cuisine: "french",
    ingredients: [ing("heavy-cream", "1 cup cream", 1, "cup", 1)],
  });
  const candidates = new Map([
    [safe.id, safe],
    [dairy.id, dairy],
  ]);
  const household = makeHousehold({
    restrictions: [
      { personId: "p2", allergenClass: "dairy", canonicalItemId: null, severity: "allergy" },
    ],
  });

  function proposal(entries: PlanProposal["entries"]): PlanProposal {
    return { entries, perishablePairings: [], treatSuggestions: [], notes: null };
  }

  it("rejects a plan with an unresolved allergy conflict", () => {
    const result = validatePlan({
      proposal: proposal([
        { recipeId: "dairy-dish", date: "2026-08-03", servings: 4, rationale: "", personHandling: [] },
      ]),
      candidates,
      states: stateMap([]),
      items: ITEMS,
      household,
    });
    expect(result.ok).toBe(false);
    expect(result.errors.some((v) => v.code === "allergy_hard_fail")).toBe(true);
  });

  it("accepts a clean plan, surfacing only warnings", () => {
    const result = validatePlan({
      proposal: proposal([
        { recipeId: "safe", date: "2026-08-03", servings: 4, rationale: "", personHandling: [] },
      ]),
      candidates,
      states: stateMap([]),
      items: ITEMS,
      household,
    });
    expect(result.ok).toBe(true);
    // cilantro used once → orphaned-perishable warning, not an error
    expect(result.warnings.some((v) => v.code === "orphaned_perishable")).toBe(true);
  });
});

describe("orphanedPerishables", () => {
  it("does not flag tender herbs shared across two dishes", () => {
    const a = makeRecipe({ id: "a", ingredients: [ing("cilantro", "cilantro", 1, "bunch")] });
    const b = makeRecipe({ id: "b", ingredients: [ing("cilantro", "cilantro", 1, "bunch")] });
    expect(orphanedPerishables([a, b], ITEMS)).toHaveLength(0);
  });

  it("does not flag hardy herbs at all", () => {
    const a = makeRecipe({ id: "a", ingredients: [ing("ginger", "ginger", 1, "each")] });
    expect(orphanedPerishables([a], ITEMS)).toHaveLength(0);
  });
});
