"""Perishable-overlap analysis — port of packages/engine/src/planning/perishables.ts.

The planner deliberately clusters dishes that share short-lived ingredients
(tender herbs above all) so one bunch is consumed across two or more meals.
Code computes the overlap sets; Claude uses them when composing; the validator
warns when a tender herb ends up single-use ("orphaned").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping

from ..schemas.domain import CanonicalItem, Recipe
from ..schemas.plan import Violation


@dataclass(frozen=True)
class PerishableUsage:
    canonical_item_id: str
    item_name: str
    perishability: Literal["tender_herb", "perishable"]
    recipe_ids: tuple[str, ...]


def perishable_usage(
    recipes: list[Recipe], items: Mapping[str, CanonicalItem]
) -> list[PerishableUsage]:
    usage: dict[str, list[str]] = {}
    for recipe in recipes:
        for ing in recipe.ingredients:
            if ing.canonical_item_id is None:
                continue
            item = items.get(ing.canonical_item_id)
            if item is None:
                continue
            if item.perishability in ("tender_herb", "perishable"):
                bucket = usage.setdefault(item.id, [])
                if recipe.id not in bucket:
                    bucket.append(recipe.id)
    return [
        PerishableUsage(
            canonical_item_id=item_id,
            item_name=items[item_id].name,
            perishability=items[item_id].perishability,  # type: ignore[arg-type]
            recipe_ids=tuple(recipe_ids),
        )
        for item_id, recipe_ids in usage.items()
    ]


def orphaned_perishables(
    recipes: list[Recipe], items: Mapping[str, CanonicalItem]
) -> list[Violation]:
    """Warn on tender herbs used by exactly one planned dish."""
    return [
        Violation(
            code="orphaned_perishable",
            severity="warning",
            entry_index=None,
            message=(
                f"{u.item_name} is used by only one dish this week — "
                f"suggest a second dish that finishes it."
            ),
        )
        for u in perishable_usage(recipes, items)
        if u.perishability == "tender_herb" and len(u.recipe_ids) == 1
    ]
