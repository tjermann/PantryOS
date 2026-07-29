"""Shared test fixtures — port of packages/engine/test/fixtures.ts, but backed
by the real packaged ontology so tests double as ontology regression checks."""

from __future__ import annotations

from mealplanner.allergen.ontology import load_ontology
from mealplanner.schemas.domain import (
    Household,
    HouseholdRecipeState,
    Recipe,
    RecipeIngredient,
    RecipeStep,
)

ITEMS = load_ontology()


def make_recipe(id: str, **overrides) -> Recipe:
    defaults = dict(
        id=id,
        title=id,
        serves=4,
        published_time_min=40,
        protein="chicken",
        cuisine="american",
        seasons=["year_round"],
        equipment=[],
        effort="moderate",
        ingredients=[],
        steps=[
            RecipeStep(order=1, text="Prep.", duration_min=10, unattended=False),
            RecipeStep(order=2, text="Cook.", duration_min=20, unattended=False),
        ],
    )
    defaults.update(overrides)
    return Recipe.model_validate(defaults)


def ing(
    canonical_item_id: str | None,
    raw: str,
    qty: float | None = 1,
    unit: str | None = "each",
    added_at_step: int | None = None,
    is_optional: bool = False,
) -> RecipeIngredient:
    return RecipeIngredient(
        canonical_item_id=canonical_item_id,
        raw=raw,
        qty=qty,
        unit=unit,
        added_at_step=added_at_step,
        is_optional=is_optional,
    )


def make_household(**overrides) -> Household:
    defaults = dict(
        id="h1",
        name="Test household",
        region="northern",
        people=[
            {"id": "p1", "name": "Avery"},
            {"id": "p2", "name": "Sam"},
        ],
        restrictions=[],
        equipment=["sheet_pan"],
        dinners_per_week=5,
    )
    defaults.update(overrides)
    return Household.model_validate(defaults)


def state_map(entries: list[dict]) -> dict[str, HouseholdRecipeState]:
    return {
        e["recipe_id"]: HouseholdRecipeState.model_validate(
            {"lifecycle": "keeper", **e}
        )
        for e in entries
    }
