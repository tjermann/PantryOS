"""Candidate filtering — port of packages/engine/src/planning/candidates.ts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping

from ..schemas.domain import Household, HouseholdRecipeState, Recipe, Season

_FLIP: dict[str, Season] = {
    "spring": "fall",
    "summer": "winter",
    "fall": "spring",
    "winter": "summer",
}


def season_for_month(month: int, region: Literal["northern", "southern"]) -> Season:
    """Meteorological seasons; region flips hemispheres."""
    if 3 <= month <= 5:
        northern: Season = "spring"
    elif 6 <= month <= 8:
        northern = "summer"
    elif 9 <= month <= 11:
        northern = "fall"
    else:
        northern = "winter"
    return northern if region == "northern" else _FLIP[northern]


RejectReason = Literal["out_of_season", "lifecycle_cut", "missing_equipment"]


@dataclass(frozen=True)
class RejectedCandidate:
    recipe_id: str
    reason: RejectReason


def filter_candidates(
    recipes: list[Recipe],
    states: Mapping[str, HouseholdRecipeState],
    household: Household,
    month: int,
) -> tuple[list[Recipe], list[RejectedCandidate]]:
    """Deterministic candidate pool: in-season (or year-round), not Cut, and the
    household owns all required equipment."""
    season = season_for_month(month, household.region)
    owned = set(household.equipment)
    candidates: list[Recipe] = []
    rejected: list[RejectedCandidate] = []

    for recipe in recipes:
        state = states.get(recipe.id)
        if state is not None and state.lifecycle == "cut":
            rejected.append(RejectedCandidate(recipe.id, "lifecycle_cut"))
            continue
        if "year_round" not in recipe.seasons and season not in recipe.seasons:
            rejected.append(RejectedCandidate(recipe.id, "out_of_season"))
            continue
        if not all(e in owned for e in recipe.equipment):
            rejected.append(RejectedCandidate(recipe.id, "missing_equipment"))
            continue
        candidates.append(recipe)
    return candidates, rejected
