import { describe, expect, it } from "vitest";
import { buildGroceryList, convert, normalizeUnit, detectLongLead } from "../src/index.js";
import { ITEMS, ing, makeRecipe } from "./fixtures.js";

describe("units", () => {
  it("normalizes aliases", () => {
    expect(normalizeUnit("Tablespoons")).toBe("tbsp");
    expect(normalizeUnit("LBS")).toBe("lb");
    expect(normalizeUnit(null)).toBe("each");
  });

  it("converts within a dimension", () => {
    expect(convert(1, "lb", "oz")).toBeCloseTo(16, 1);
    expect(convert(3, "tsp", "tbsp")).toBeCloseTo(1, 2);
    expect(convert(2, "cup", "ml")).toBeCloseTo(473.2, 0);
  });

  it("refuses cross-dimension conversion without density", () => {
    expect(convert(1, "cup", "lb")).toBeNull();
    expect(convert(2, "bunch", "oz")).toBeNull();
  });
});

describe("buildGroceryList", () => {
  const riceBowl = makeRecipe({
    id: "rice-bowl",
    serves: 4,
    ingredients: [
      ing("rice", "1 cup rice", 1, "cup"),
      ing("chicken-thigh", "1 lb chicken thighs", 1, "lb"),
      ing("cilantro", "1 bunch cilantro", 1, "bunch"),
    ],
  });
  const curry = makeRecipe({
    id: "curry",
    serves: 4,
    ingredients: [
      ing("rice", "2 cups rice", 2, "cup"),
      ing("coconut-milk", "1 can coconut milk", 1, "can"),
      ing("cilantro", "1 bunch cilantro", 1, "bunch"),
    ],
  });

  it("aggregates the same item across recipes with unit conversion", () => {
    const result = buildGroceryList({
      recipes: [
        { recipe: riceBowl, servings: 4 },
        { recipe: curry, servings: 4 },
      ],
      pantry: [],
      standing: [],
      items: ITEMS,
      budgetEnabled: false,
      budgetCents: null,
    });
    const rice = result.lines.find((l) => l.canonicalItemId === "rice");
    expect(rice?.qty).toBeCloseTo(3, 5);
    expect(rice?.sourceRecipeIds).toEqual(["rice-bowl", "curry"]);
    const cilantro = result.lines.find((l) => l.canonicalItemId === "cilantro");
    expect(cilantro?.qty).toBe(2);
  });

  it("scales quantities for requested servings", () => {
    const result = buildGroceryList({
      recipes: [{ recipe: riceBowl, servings: 8 }],
      pantry: [],
      standing: [],
      items: ITEMS,
      budgetEnabled: false,
      budgetCents: null,
    });
    const chicken = result.lines.find((l) => l.canonicalItemId === "chicken-thigh");
    expect(chicken?.qty).toBeCloseTo(2, 5);
  });

  it("subtracts confirmed pantry stock but ignores assumed stock", () => {
    const result = buildGroceryList({
      recipes: [{ recipe: curry, servings: 4 }],
      pantry: [
        { canonicalItemId: "rice", qty: 1, unit: "cup", confidence: "confirmed" },
        { canonicalItemId: "coconut-milk", qty: 1, unit: "can", confidence: "assumed" },
      ],
      standing: [],
      items: ITEMS,
      budgetEnabled: false,
      budgetCents: null,
    });
    const rice = result.lines.find((l) => l.canonicalItemId === "rice");
    expect(rice?.qty).toBeCloseTo(1, 5);
    expect(rice?.pantryAdjusted).toBe(true);
    const coconut = result.lines.find((l) => l.canonicalItemId === "coconut-milk");
    expect(coconut?.qty).toBe(1);
  });

  it("drops fully-stocked lines and keeps unmatched ingredients verbatim", () => {
    const withMystery = makeRecipe({
      id: "mystery",
      ingredients: [ing("rice", "1 cup rice", 1, "cup"), ing(null, "1 jar special sauce", null, null)],
    });
    const result = buildGroceryList({
      recipes: [{ recipe: withMystery, servings: 4 }],
      pantry: [{ canonicalItemId: "rice", qty: 5, unit: "cup", confidence: "confirmed" }],
      standing: [],
      items: ITEMS,
      budgetEnabled: false,
      budgetCents: null,
    });
    expect(result.lines.find((l) => l.canonicalItemId === "rice")).toBeUndefined();
    const mystery = result.lines.find((l) => l.displayName === "1 jar special sauce");
    expect(mystery).toBeDefined();
    expect(mystery?.section).toBe("other");
  });

  it("adds standing lines and groups by store section", () => {
    const result = buildGroceryList({
      recipes: [{ recipe: riceBowl, servings: 4 }],
      pantry: [],
      standing: [
        { canonicalItemId: null, raw: "Chicken nuggets (kids)", qty: 1, unit: "each", reason: "kids' standing meals" },
        { canonicalItemId: "oat-milk", raw: "oat milk", qty: 1, unit: "each", reason: "restock" },
      ],
      items: ITEMS,
      budgetEnabled: false,
      budgetCents: null,
    });
    expect(result.sections.produce?.some((l) => l.canonicalItemId === "cilantro")).toBe(true);
    expect(result.sections.dairy?.some((l) => l.origin === "restock")).toBe(true);
    expect(result.sections.other?.some((l) => l.origin === "standing")).toBe(true);
  });

  it("reports budget headroom only when every line is priced", () => {
    const pricedOnly = makeRecipe({
      id: "priced",
      ingredients: [ing("chicken-thigh", "1 lb chicken", 1, "lb"), ing("cilantro", "1 bunch", 1, "bunch")],
    });
    const result = buildGroceryList({
      recipes: [{ recipe: pricedOnly, servings: 4 }],
      pantry: [],
      standing: [],
      items: ITEMS,
      budgetEnabled: true,
      budgetCents: 5000,
    });
    expect(result.estTotalCents).toBe(899 + 149);
    expect(result.budget.underBudgetCents).toBe(5000 - 1048);

    const withUnpriced = buildGroceryList({
      recipes: [{ recipe: riceBowl, servings: 4 }, { recipe: curry, servings: 4 }],
      pantry: [],
      standing: [{ canonicalItemId: null, raw: "mystery", qty: null, unit: null }],
      items: ITEMS,
      budgetEnabled: true,
      budgetCents: 5000,
    });
    expect(withUnpriced.estTotalCents).toBeNull();
    expect(withUnpriced.budget.underBudgetCents).toBeNull();
  });
});

describe("detectLongLead", () => {
  it("flags unattended steps over 30 minutes only", () => {
    const recipe = makeRecipe({
      id: "brine",
      steps: [
        { order: 1, text: "Brine the pork 4 hours.", durationMin: 240, unattended: true },
        { order: 2, text: "Rest 10 minutes.", durationMin: 10, unattended: true },
        { order: 3, text: "Sear 30+ minutes attended.", durationMin: 40, unattended: false },
      ],
    });
    const flags = detectLongLead(recipe);
    expect(flags).toHaveLength(1);
    expect(flags[0]).toMatchObject({ stepOrder: 1, leadMin: 240 });
  });
});
