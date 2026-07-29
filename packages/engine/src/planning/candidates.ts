import type {
  Household,
  HouseholdRecipeState,
  Recipe,
  Season,
} from "../schemas/domain.js";

/** Meteorological seasons; region flips hemispheres. */
export function seasonForMonth(month: number, region: "northern" | "southern"): Season {
  const northern: Season =
    month >= 3 && month <= 5
      ? "spring"
      : month >= 6 && month <= 8
        ? "summer"
        : month >= 9 && month <= 11
          ? "fall"
          : "winter";
  if (region === "northern") return northern;
  const flip: Record<string, Season> = {
    spring: "fall",
    summer: "winter",
    fall: "spring",
    winter: "summer",
  };
  return flip[northern] ?? northern;
}

export interface CandidateFilterInput {
  recipes: Recipe[];
  states: ReadonlyMap<string, HouseholdRecipeState>;
  household: Household;
  /** Month 1-12 of the week being planned. */
  month: number;
}

export interface RejectedCandidate {
  recipeId: string;
  reason: "out_of_season" | "lifecycle_cut" | "missing_equipment";
}

/**
 * Deterministic candidate pool: in-season (or year-round), not Cut, and the
 * household owns all required equipment. Equipment the household hasn't
 * confirmed counts as missing — unchecked means unconfirmed, not absent, but
 * for planning we don't schedule around appliances we can't verify.
 */
export function filterCandidates(input: CandidateFilterInput): {
  candidates: Recipe[];
  rejected: RejectedCandidate[];
} {
  const season = seasonForMonth(input.month, input.household.region);
  const owned = new Set(input.household.equipment);
  const candidates: Recipe[] = [];
  const rejected: RejectedCandidate[] = [];

  for (const recipe of input.recipes) {
    const state = input.states.get(recipe.id);
    if (state?.lifecycle === "cut") {
      rejected.push({ recipeId: recipe.id, reason: "lifecycle_cut" });
      continue;
    }
    const inSeason =
      recipe.seasons.includes("year_round") || recipe.seasons.includes(season);
    if (!inSeason) {
      rejected.push({ recipeId: recipe.id, reason: "out_of_season" });
      continue;
    }
    if (!recipe.equipment.every((e) => owned.has(e))) {
      rejected.push({ recipeId: recipe.id, reason: "missing_equipment" });
      continue;
    }
    candidates.push(recipe);
  }
  return { candidates, rejected };
}
