import { describe, expect, it } from "vitest";
import type { GroceryLine } from "@meal-planner/engine";
import { formatShareList } from "../src/index.js";

function line(overrides: Partial<GroceryLine>): GroceryLine {
  return {
    canonicalItemId: null,
    displayName: "item",
    qty: 1,
    unit: "each",
    section: "other",
    origin: "recipe",
    sourceRecipeIds: [],
    estPriceCents: null,
    pantryAdjusted: false,
    ...overrides,
  };
}

describe("formatShareList", () => {
  it("groups by section in store-walk order and formats quantities", () => {
    const text = formatShareList([
      line({ displayName: "Jasmine rice", qty: 3, unit: "cup", section: "pantry" }),
      line({ displayName: "Cilantro", qty: 2, unit: "bunch", section: "produce" }),
      line({ displayName: "Chicken thighs", qty: 1.5, unit: "lb", section: "meat_seafood" }),
      line({ displayName: "Mystery sauce", qty: null, unit: null }),
    ]);
    const sections = text.split("\n\n");
    expect(sections[0]).toContain("Produce");
    expect(sections[0]).toContain("☐ Cilantro — 2 bunch");
    expect(sections[1]).toContain("Meat & Seafood");
    expect(sections[1]).toContain("☐ Chicken thighs — 1.5 lb");
    expect(text).toContain("☐ Mystery sauce");
    expect(text).not.toContain("null");
  });

  it("omits empty sections", () => {
    const text = formatShareList([line({ displayName: "Rice", section: "pantry" })]);
    expect(text).not.toContain("Produce");
    expect(text).toContain("Pantry");
  });
});
