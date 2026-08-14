"""Candidate filtering — port of packages/engine/src/planning/candidates.ts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
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


RejectReason = Literal[
    "out_of_season", "lifecycle_cut", "missing_equipment", "avoided_protein",
    "not_dinner", "made_recently",
]


@dataclass(frozen=True)
class RejectedCandidate:
    recipe_id: str
    reason: RejectReason


def cap_candidates(
    candidates: list[Recipe],
    states: Mapping[str, HouseholdRecipeState],
    week_key: str,
    cap: int = 400,
) -> list[Recipe]:
    """Bound the pool sent to the model: keepers always make the cut; the rest
    rotate weekly (deterministic per week, different across weeks) so a large
    library gets explored over time without blowing up the prompt."""
    if len(candidates) <= cap:
        return candidates
    import hashlib

    keepers = [
        r for r in candidates
        if (s := states.get(r.id)) is not None and s.lifecycle == "keeper"
    ]
    rest = [r for r in candidates if r not in keepers]
    rest.sort(key=lambda r: hashlib.sha1(f"{week_key}:{r.id}".encode()).hexdigest())
    return (keepers + rest)[:max(cap, len(keepers))]


def filter_candidates(
    recipes: list[Recipe],
    states: Mapping[str, HouseholdRecipeState],
    household: Household,
    month: int,
    today: date | None = None,
    repeat_window_days: int = 0,
) -> tuple[list[Recipe], list[RejectedCandidate]]:
    """Deterministic candidate pool: in-season (or year-round), not Cut, and the
    household owns all required equipment."""
    season = season_for_month(month, household.region)
    owned = set(household.equipment)
    avoided = {p.lower() for p in household.avoid_proteins}
    cutoff = (
        (today or date.today()) - timedelta(days=repeat_window_days)
        if repeat_window_days > 0 else None
    )
    candidates: list[Recipe] = []
    rejected: list[RejectedCandidate] = []

    for recipe in recipes:
        state = states.get(recipe.id)
        if state is not None and state.lifecycle == "cut":
            rejected.append(RejectedCandidate(recipe.id, "lifecycle_cut"))
            continue
        if recipe.protein.lower() in avoided:
            rejected.append(RejectedCandidate(recipe.id, "avoided_protein"))
            continue
        if recipe.dish_type != "dinner":
            rejected.append(RejectedCandidate(recipe.id, "not_dinner"))
            continue
        # Hard rule, not a hint: a dish cooked recently is off the table. The
        # model can't talk itself past this the way it could a warning.
        if cutoff is not None and state is not None and state.last_made_at:
            try:
                if date.fromisoformat(state.last_made_at) >= cutoff:
                    rejected.append(RejectedCandidate(recipe.id, "made_recently"))
                    continue
            except ValueError:
                pass
        if "year_round" not in recipe.seasons and season not in recipe.seasons:
            rejected.append(RejectedCandidate(recipe.id, "out_of_season"))
            continue
        if not all(e in owned for e in recipe.equipment):
            rejected.append(RejectedCandidate(recipe.id, "missing_equipment"))
            continue
        candidates.append(recipe)
    return candidates, rejected
