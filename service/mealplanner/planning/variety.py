"""Variety rules — port of packages/engine/src/planning/variety.ts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Mapping

from ..schemas.domain import HouseholdRecipeState, Recipe
from ..schemas.plan import PlanEntryProposal, Violation


@dataclass(frozen=True)
class VarietyRules:
    # Source rule: "not three chicken dinners".
    max_same_protein_per_week: int = 2
    # "No back-to-back pasta" generalized to same-cuisine consecutive nights.
    no_back_to_back_cuisine: bool = True
    no_consecutive_involved: bool = True
    repeat_window_days: int = 21


DEFAULT_VARIETY_RULES = VarietyRules()


def validate_variety(
    entries: list[PlanEntryProposal],
    recipes: Mapping[str, Recipe],
    states: Mapping[str, HouseholdRecipeState],
    rules: VarietyRules = DEFAULT_VARIETY_RULES,
) -> list[Violation]:
    violations: list[Violation] = []
    indexed = sorted(
        ((entry, i, recipes.get(entry.recipe_id)) for i, entry in enumerate(entries)),
        key=lambda x: x[0].date,
    )

    for entry, i, recipe in indexed:
        if recipe is None:
            violations.append(
                Violation(
                    code="unknown_recipe",
                    severity="error",
                    entry_index=i,
                    message=f"Proposed recipe {entry.recipe_id} is not in the candidate set.",
                )
            )

    known = [(e, i, r) for e, i, r in indexed if r is not None]

    # Protein cap across the week.
    by_protein: dict[str, list[int]] = {}
    for _, i, recipe in known:
        by_protein.setdefault(recipe.protein, []).append(i)
    for protein, idxs in by_protein.items():
        if len(idxs) > rules.max_same_protein_per_week:
            violations.append(
                Violation(
                    code="protein_overload",
                    severity="warning",
                    entry_index=idxs[-1],
                    message=(
                        f"{len(idxs)} {protein} dinners in one week "
                        f"(max {rules.max_same_protein_per_week})."
                    ),
                )
            )

    # Consecutive-night rules.
    for (prev_e, _prev_i, prev_r), (curr_e, curr_i, curr_r) in zip(known, known[1:]):
        gap_days = (date.fromisoformat(curr_e.date) - date.fromisoformat(prev_e.date)).days
        if gap_days != 1:
            continue
        if rules.no_back_to_back_cuisine and prev_r.cuisine == curr_r.cuisine:
            violations.append(
                Violation(
                    code="back_to_back_similar",
                    severity="warning",
                    entry_index=curr_i,
                    message=(
                        f"{prev_r.title} and {curr_r.title} are back-to-back "
                        f"{curr_r.cuisine} nights."
                    ),
                )
            )
        if (
            rules.no_consecutive_involved
            and prev_r.effort == "involved"
            and curr_r.effort == "involved"
        ):
            violations.append(
                Violation(
                    code="effort_stacking",
                    severity="warning",
                    entry_index=curr_i,
                    message=(
                        f"Two demanding recipes on consecutive nights "
                        f"({prev_r.title} → {curr_r.title})."
                    ),
                )
            )

    # Cross-week repeat window via last-made dates.
    for entry, i, recipe in known:
        state = states.get(recipe.id)
        if state is None or state.last_made_at is None:
            continue
        gap_days = (
            date.fromisoformat(entry.date) - date.fromisoformat(state.last_made_at)
        ).days
        if 0 <= gap_days < rules.repeat_window_days:
            violations.append(
                Violation(
                    code="recent_repeat",
                    severity="warning",
                    entry_index=i,
                    message=(
                        f"{recipe.title} was last made {gap_days} days before this "
                        f"plan date (window: {rules.repeat_window_days})."
                    ),
                )
            )

    return violations
