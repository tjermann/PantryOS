"""Build the grocery list for a saved plan — used by the proposal email, the
Friday review page, and Saturday's execution so all three agree exactly."""

from __future__ import annotations

from pathlib import Path

from ..allergen.ontology import load_ontology
from ..config import UserConfig
from ..recipes.merged import apply_source_policy, load_full_library
from ..state.store import StateStore
from .pipeline import GroceryListResult, build_grocery_list


def grocery_for_plan(
    user: str,
    config: UserConfig,
    store: StateStore,
    plan: dict,
    iso_week: str,
    base: Path | None = None,
) -> GroceryListResult:
    library = apply_source_policy(
        load_full_library(user, config.recipe_library, base),
        config.source_policy, config.recipe_sources,
    )
    by_id = {e.recipe.id: e.recipe for e in library}
    # Only what's actually being cooked: on a shortlist that's the picks (or the
    # defaults until they pick), never every option.
    from ..planning.selection import resolve_selection

    recipes = [
        (by_id[e["recipe_id"]], e.get("servings", 4))
        for e in resolve_selection(plan, config.household)
        if e.get("recipe_id") in by_id
    ]
    return build_grocery_list(
        recipes=recipes,
        pantry=store.load_pantry(),
        standing=[*config.standing_orders, *store.load_restock()],
        items=load_ontology(),
        budget_enabled=config.household.budget_enabled,
        budget_cents=config.household.budget_cents_weekly,
        substitutions=config.household.item_substitutions,
        staples=store.load_staples(),
        excluded=store.load_exclusions(iso_week),
    )
