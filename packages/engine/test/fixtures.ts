import {
  CanonicalItem,
  type Household,
  type HouseholdRecipeState,
  type Recipe,
} from "../src/index.js";

export const ITEMS: ReadonlyMap<string, CanonicalItem> = new Map(
  (
    [
      { id: "milk", name: "Whole milk", storeSection: "dairy", perishability: "perishable", allergens: ["dairy"] },
      { id: "heavy-cream", name: "Heavy cream", storeSection: "dairy", perishability: "perishable", allergens: ["dairy"] },
      { id: "parmesan", name: "Parmesan", storeSection: "dairy", perishability: "stable", allergens: ["dairy"] },
      // The canonical traps: name suggests an allergen, ontology says no.
      { id: "coconut-milk", name: "Coconut milk", storeSection: "pantry", perishability: "stable", allergens: [], notAllergens: ["dairy", "tree_nut"] },
      { id: "cream-of-tartar", name: "Cream of tartar", storeSection: "pantry", perishability: "stable", allergens: [], notAllergens: ["dairy"] },
      { id: "water-chestnut", name: "Water chestnuts", storeSection: "pantry", perishability: "stable", allergens: [], notAllergens: ["tree_nut"] },
      { id: "buckwheat", name: "Buckwheat groats", storeSection: "pantry", perishability: "stable", allergens: [], notAllergens: ["gluten"] },
      { id: "peanut", name: "Peanuts", storeSection: "pantry", perishability: "stable", allergens: ["peanut"] },
      { id: "shrimp", name: "Shrimp", storeSection: "meat_seafood", perishability: "perishable", allergens: ["shellfish"], typicalPriceCents: 1299 },
      { id: "chicken-thigh", name: "Chicken thighs", storeSection: "meat_seafood", perishability: "perishable", allergens: [], typicalPriceCents: 899 },
      { id: "cilantro", name: "Cilantro", storeSection: "produce", perishability: "tender_herb", allergens: [], typicalPriceCents: 149 },
      { id: "basil", name: "Basil", storeSection: "produce", perishability: "tender_herb", allergens: [], typicalPriceCents: 249 },
      { id: "ginger", name: "Ginger", storeSection: "produce", perishability: "hardy_herb", allergens: [], typicalPriceCents: 99 },
      { id: "rice", name: "Jasmine rice", storeSection: "pantry", perishability: "stable", allergens: [], typicalPriceCents: 599 },
      { id: "oat-milk", name: "Oat milk", storeSection: "dairy", perishability: "perishable", allergens: [], notAllergens: ["dairy"], typicalPriceCents: 449 },
      { id: "cherry-tomatoes", name: "Cherry tomatoes", storeSection: "produce", perishability: "perishable", allergens: [], typicalPriceCents: 399 },
    ] as const
  ).map((raw) => {
    const item = CanonicalItem.parse(raw);
    return [item.id, item];
  }),
);

export function makeRecipe(overrides: Partial<Recipe> & { id: string }): Recipe {
  return {
    title: overrides.id,
    serves: 4,
    publishedTimeMin: 40,
    protein: "chicken",
    cuisine: "american",
    seasons: ["year_round"],
    equipment: [],
    effort: "moderate",
    ingredients: [],
    steps: [
      { order: 1, text: "Prep.", durationMin: 10, unattended: false },
      { order: 2, text: "Cook.", durationMin: 20, unattended: false },
    ],
    ...overrides,
  };
}

export function ing(
  canonicalItemId: string | null,
  raw: string,
  qty: number | null = 1,
  unit: string | null = "each",
  addedAtStep: number | null = null,
): Recipe["ingredients"][number] {
  return { canonicalItemId, raw, qty, unit, isOptional: false, addedAtStep };
}

export function makeHousehold(overrides: Partial<Household> = {}): Household {
  return {
    id: "h1",
    name: "Test household",
    region: "northern",
    people: [
      { id: "p1", name: "Avery", isChild: false, eatsPlannedDinners: true },
      { id: "p2", name: "Sam", isChild: false, eatsPlannedDinners: true },
    ],
    restrictions: [],
    equipment: ["sheet_pan"],
    dinnersPerWeek: 5,
    budgetCentsWeekly: null,
    budgetEnabled: false,
    ...overrides,
  };
}

export function stateMap(
  entries: Array<Partial<HouseholdRecipeState> & { recipeId: string }>,
): ReadonlyMap<string, HouseholdRecipeState> {
  return new Map(
    entries.map((e) => [
      e.recipeId,
      {
        lifecycle: "keeper" as const,
        lastMadeAt: null,
        timesMade: 0,
        avgRating: null,
        realTimeMin: null,
        ...e,
      },
    ]),
  );
}
