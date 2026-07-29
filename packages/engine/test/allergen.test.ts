import { describe, expect, it } from "vitest";
import {
  itemInAllergenClass,
  runAllergenBackstop,
  splitFeasible,
  type PlanEntryProposal,
} from "../src/index.js";
import { ITEMS, ing, makeHousehold, makeRecipe } from "./fixtures.js";

const dairyAllergyHousehold = makeHousehold({
  restrictions: [
    { personId: "p2", allergenClass: "dairy", canonicalItemId: null, severity: "allergy" },
  ],
});

function entryFor(
  recipeId: string,
  handling: PlanEntryProposal["personHandling"] = [],
): PlanEntryProposal {
  return { recipeId, date: "2026-08-03", servings: 4, rationale: "", personHandling: handling };
}

function backstop(recipe: ReturnType<typeof makeRecipe>, entry: PlanEntryProposal, household = dairyAllergyHousehold) {
  return runAllergenBackstop({
    entry,
    entryIndex: 0,
    recipe,
    people: household.people,
    restrictions: household.restrictions,
    items: ITEMS,
  });
}

describe("ontology membership", () => {
  it("classifies real dairy as dairy", () => {
    expect(itemInAllergenClass(ITEMS.get("milk"), "dairy")).toBe("member");
    expect(itemInAllergenClass(ITEMS.get("heavy-cream"), "dairy")).toBe("member");
  });

  it("does NOT classify name-trap items by substring", () => {
    expect(itemInAllergenClass(ITEMS.get("coconut-milk"), "dairy")).toBe("non_member");
    expect(itemInAllergenClass(ITEMS.get("cream-of-tartar"), "dairy")).toBe("non_member");
    expect(itemInAllergenClass(ITEMS.get("water-chestnut"), "tree_nut")).toBe("non_member");
    expect(itemInAllergenClass(ITEMS.get("buckwheat"), "gluten")).toBe("non_member");
  });

  it("returns unknown for missing items", () => {
    expect(itemInAllergenClass(undefined, "dairy")).toBe("unknown");
  });
});

describe("allergen backstop — hard fails", () => {
  it("errors when a dairy allergy meets cream with no handling", () => {
    const recipe = makeRecipe({
      id: "r1",
      ingredients: [ing("heavy-cream", "1 cup heavy cream", 1, "cup", 2)],
    });
    const violations = backstop(recipe, entryFor("r1"));
    expect(violations).toHaveLength(1);
    expect(violations[0]).toMatchObject({ code: "allergy_hard_fail", severity: "error" });
  });

  it("passes coconut milk against a dairy allergy (no false positive)", () => {
    const recipe = makeRecipe({
      id: "r2",
      ingredients: [ing("coconut-milk", "1 can coconut milk", 1, "can")],
    });
    expect(backstop(recipe, entryFor("r2"))).toHaveLength(0);
  });

  it("fails closed on unmatched ingredients for allergy severity", () => {
    const recipe = makeRecipe({
      id: "r3",
      ingredients: [ing(null, "1 jar mystery sauce")],
    });
    const violations = backstop(recipe, entryFor("r3"));
    expect(violations.some((v) => v.severity === "error")).toBe(true);
  });

  it("downgrades unmatched ingredients to warnings for intolerance severity", () => {
    const household = makeHousehold({
      restrictions: [
        { personId: "p2", allergenClass: "dairy", canonicalItemId: null, severity: "intolerance" },
      ],
    });
    const recipe = makeRecipe({ id: "r4", ingredients: [ing(null, "1 jar mystery sauce")] });
    const violations = backstop(recipe, entryFor("r4"), household);
    expect(violations.every((v) => v.severity === "warning")).toBe(true);
  });

  it("ignores optional conflicting ingredients", () => {
    const recipe = makeRecipe({
      id: "r5",
      ingredients: [{ ...ing("parmesan", "parmesan to serve", 1, "oz"), isOptional: true }],
    });
    expect(backstop(recipe, entryFor("r5"))).toHaveLength(0);
  });
});

describe("allergen backstop — handling verification", () => {
  const creamRecipe = makeRecipe({
    id: "rc",
    ingredients: [ing("heavy-cream", "1 cup heavy cream", 1, "cup", 3)],
  });

  it("accepts a valid non-conflicting substitute", () => {
    const entry = entryFor("rc", [
      { personId: "p2", handling: "substitute", substituteItemId: "oat-milk", substituteNote: "1:1" },
    ]);
    expect(backstop(creamRecipe, entry)).toHaveLength(0);
  });

  it("rejects a substitute that itself conflicts", () => {
    const entry = entryFor("rc", [
      { personId: "p2", handling: "substitute", substituteItemId: "milk", substituteNote: null },
    ]);
    expect(backstop(creamRecipe, entry)[0]).toMatchObject({
      code: "invalid_substitute",
      severity: "error",
    });
  });

  it("rejects an unknown substitute id", () => {
    const entry = entryFor("rc", [
      { personId: "p2", handling: "substitute", substituteItemId: "nope", substituteNote: null },
    ]);
    expect(backstop(creamRecipe, entry)[0]?.code).toBe("invalid_substitute");
  });

  it("accepts split when the conflicting ingredient enters after step 1", () => {
    const entry = entryFor("rc", [
      { personId: "p2", handling: "split", substituteItemId: null, substituteNote: null },
    ]);
    expect(backstop(creamRecipe, entry)).toHaveLength(0);
  });

  it("rejects split when the conflicting ingredient enters at step 1", () => {
    const step1Recipe = makeRecipe({
      id: "rs",
      ingredients: [ing("milk", "2 cups milk", 2, "cup", 1)],
    });
    const entry = entryFor("rs", [
      { personId: "p2", handling: "split", substituteItemId: null, substituteNote: null },
    ]);
    expect(backstop(step1Recipe, entry)[0]).toMatchObject({
      code: "split_not_feasible",
      severity: "error",
    });
  });

  it("rejects split when the entry step is unknown", () => {
    const unknownStepRecipe = makeRecipe({
      id: "ru",
      ingredients: [ing("milk", "2 cups milk", 2, "cup", null)],
    });
    const entry = entryFor("ru", [
      { personId: "p2", handling: "split", substituteItemId: null, substituteNote: null },
    ]);
    expect(backstop(unknownStepRecipe, entry)[0]?.code).toBe("split_not_feasible");
  });

  it("accepts skip", () => {
    const entry = entryFor("rc", [
      { personId: "p2", handling: "skip", substituteItemId: null, substituteNote: null },
    ]);
    expect(backstop(creamRecipe, entry)).toHaveLength(0);
  });

  it("treats preference conflicts as warnings, never errors", () => {
    const household = makeHousehold({
      restrictions: [
        { personId: "p1", allergenClass: null, canonicalItemId: "shrimp", severity: "preference" },
      ],
    });
    const recipe = makeRecipe({ id: "rp", ingredients: [ing("shrimp", "1 lb shrimp", 1, "lb")] });
    const violations = backstop(recipe, entryFor("rp"), household);
    expect(violations).toHaveLength(1);
    expect(violations[0]?.severity).toBe("warning");
  });

  it("skips people who don't eat planned dinners", () => {
    const household = makeHousehold({
      people: [{ id: "p2", name: "Kid", isChild: true, eatsPlannedDinners: false }],
      restrictions: [
        { personId: "p2", allergenClass: "dairy", canonicalItemId: null, severity: "allergy" },
      ],
    });
    const recipe = makeRecipe({ id: "rk", ingredients: [ing("milk", "milk", 1, "cup", 1)] });
    expect(backstop(recipe, entryFor("rk"), household)).toHaveLength(0);
  });
});

describe("splitFeasible", () => {
  it("is feasible with no conflicts", () => {
    expect(splitFeasible(makeRecipe({ id: "x" }), [])).toBe(true);
  });
});
