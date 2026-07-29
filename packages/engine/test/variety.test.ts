import { describe, expect, it } from "vitest";
import { validateVariety, seasonForMonth, filterCandidates } from "../src/index.js";
import { makeHousehold, makeRecipe, stateMap } from "./fixtures.js";

function recipesMap(...recipes: ReturnType<typeof makeRecipe>[]) {
  return new Map(recipes.map((r) => [r.id, r]));
}

function entry(recipeId: string, date: string) {
  return { recipeId, date, servings: 4, rationale: "", personHandling: [] };
}

describe("validateVariety", () => {
  it("flags three same-protein dinners", () => {
    const recipes = recipesMap(
      makeRecipe({ id: "a", protein: "chicken" }),
      makeRecipe({ id: "b", protein: "chicken", cuisine: "thai" }),
      makeRecipe({ id: "c", protein: "chicken", cuisine: "mexican" }),
    );
    const violations = validateVariety(
      [entry("a", "2026-08-03"), entry("b", "2026-08-05"), entry("c", "2026-08-07")],
      recipes,
      stateMap([]),
    );
    expect(violations.some((v) => v.code === "protein_overload")).toBe(true);
  });

  it("flags back-to-back same cuisine only on consecutive days", () => {
    const recipes = recipesMap(
      makeRecipe({ id: "a", cuisine: "italian", protein: "pork" }),
      makeRecipe({ id: "b", cuisine: "italian", protein: "beef" }),
    );
    const consecutive = validateVariety(
      [entry("a", "2026-08-03"), entry("b", "2026-08-04")],
      recipes,
      stateMap([]),
    );
    expect(consecutive.some((v) => v.code === "back_to_back_similar")).toBe(true);

    const spaced = validateVariety(
      [entry("a", "2026-08-03"), entry("b", "2026-08-06")],
      recipes,
      stateMap([]),
    );
    expect(spaced.some((v) => v.code === "back_to_back_similar")).toBe(false);
  });

  it("flags consecutive involved-effort nights", () => {
    const recipes = recipesMap(
      makeRecipe({ id: "a", effort: "involved", protein: "pork" }),
      makeRecipe({ id: "b", effort: "involved", protein: "beef", cuisine: "french" }),
    );
    const violations = validateVariety(
      [entry("a", "2026-08-03"), entry("b", "2026-08-04")],
      recipes,
      stateMap([]),
    );
    expect(violations.some((v) => v.code === "effort_stacking")).toBe(true);
  });

  it("flags recipes made within the repeat window", () => {
    const recipes = recipesMap(makeRecipe({ id: "a" }));
    const violations = validateVariety(
      [entry("a", "2026-08-03")],
      recipes,
      stateMap([{ recipeId: "a", lastMadeAt: "2026-07-25" }]),
    );
    expect(violations.some((v) => v.code === "recent_repeat")).toBe(true);
  });

  it("errors on recipe ids outside the candidate set", () => {
    const violations = validateVariety([entry("ghost", "2026-08-03")], recipesMap(), stateMap([]));
    expect(violations[0]).toMatchObject({ code: "unknown_recipe", severity: "error" });
  });
});

describe("seasonForMonth", () => {
  it("maps meteorological seasons in the northern hemisphere", () => {
    expect(seasonForMonth(1, "northern")).toBe("winter");
    expect(seasonForMonth(4, "northern")).toBe("spring");
    expect(seasonForMonth(7, "northern")).toBe("summer");
    expect(seasonForMonth(10, "northern")).toBe("fall");
  });

  it("flips hemispheres", () => {
    expect(seasonForMonth(1, "southern")).toBe("summer");
    expect(seasonForMonth(7, "southern")).toBe("winter");
  });
});

describe("filterCandidates", () => {
  it("filters by season, lifecycle, and equipment", () => {
    const household = makeHousehold({ equipment: ["sheet_pan"] });
    const { candidates, rejected } = filterCandidates({
      recipes: [
        makeRecipe({ id: "in-season", seasons: ["summer"] }),
        makeRecipe({ id: "year-round", seasons: ["year_round"] }),
        makeRecipe({ id: "wintery", seasons: ["winter"] }),
        makeRecipe({ id: "cut-recipe", seasons: ["summer"] }),
        makeRecipe({ id: "needs-ip", seasons: ["summer"], equipment: ["instant_pot"] }),
      ],
      states: stateMap([{ recipeId: "cut-recipe", lifecycle: "cut" }]),
      household,
      month: 7,
    });
    expect(candidates.map((r) => r.id).sort()).toEqual(["in-season", "year-round"]);
    expect(rejected).toEqual(
      expect.arrayContaining([
        { recipeId: "wintery", reason: "out_of_season" },
        { recipeId: "cut-recipe", reason: "lifecycle_cut" },
        { recipeId: "needs-ip", reason: "missing_equipment" },
      ]),
    );
  });
});
