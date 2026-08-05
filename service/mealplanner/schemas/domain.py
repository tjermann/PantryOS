"""Domain models — a faithful port of packages/engine/src/schemas/domain.ts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Season = Literal["spring", "summer", "fall", "winter", "year_round"]
Severity = Literal["allergy", "intolerance", "preference"]
# "split": cook normally, pull that person's portion before the restricted
# ingredient is added (requires the ingredient's added_at_step to be known).
Handling = Literal["clear", "substitute", "split", "skip"]
Lifecycle = Literal["to_try", "probation", "keeper", "cut"]
StoreSection = Literal[
    "produce", "meat_seafood", "dairy", "pantry", "frozen", "bakery", "other"
]
Perishability = Literal["tender_herb", "hardy_herb", "perishable", "stable"]
Effort = Literal["easy", "moderate", "involved"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CanonicalItem(StrictModel):
    id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    store_section: StoreSection
    perishability: Perishability
    allergens: list[str] = Field(default_factory=list)
    # Negative assertions: classes this item is explicitly NOT in even though
    # its name suggests otherwise (coconut milk -> not dairy). Documentation +
    # regression data; membership is decided only by `allergens`.
    not_allergens: list[str] = Field(default_factory=list)
    typical_price_cents: int | None = None


class RecipeIngredient(StrictModel):
    canonical_item_id: str | None = None
    raw: str
    qty: float | None = None
    unit: str | None = None
    prep_note: str | None = None
    is_optional: bool = False
    # Component this ingredient belongs to ("Sauce", "Marinade", "For the bowl")
    # when the source recipe groups them; None for ungrouped.
    group: str | None = None
    # 1-based step index at which this ingredient enters the dish; enables Split.
    added_at_step: int | None = None


class RecipeStep(StrictModel):
    order: int
    text: str
    duration_min: int | None = None
    # True for hands-off time (marinating, braising, resting).
    unattended: bool = False


class Recipe(StrictModel):
    id: str
    title: str
    serves: int = Field(gt=0)
    published_time_min: int | None = None
    protein: str
    cuisine: str
    seasons: list[Season] = Field(min_length=1)
    equipment: list[str] = Field(default_factory=list)
    effort: Effort = "moderate"
    ingredients: list[RecipeIngredient] = Field(default_factory=list)
    steps: list[RecipeStep] = Field(default_factory=list)


class DietaryRestriction(StrictModel):
    person_id: str
    # Either an allergen class (e.g. "dairy") or a specific canonical item id.
    allergen_class: str | None = None
    canonical_item_id: str | None = None
    severity: Severity
    notes: str | None = None


class Person(StrictModel):
    id: str
    name: str
    is_child: bool = False
    # Children on standing meals are excluded from dinner planning.
    eats_planned_dinners: bool = True


class HouseholdRecipeState(StrictModel):
    recipe_id: str
    lifecycle: Lifecycle = "to_try"
    last_made_at: str | None = None  # ISO date
    times_made: int = 0
    ratings: list[int] = Field(default_factory=list)
    notes: str | None = None
    # Measured start-to-eating. Never overwrites published_time_min.
    real_time_min: int | None = None


class PantryItem(StrictModel):
    canonical_item_id: str
    qty: float = Field(ge=0)
    unit: str
    confidence: Literal["confirmed", "assumed"] = "assumed"


class StandingOrderLine(StrictModel):
    canonical_item_id: str | None = None
    raw: str
    qty: float | None = None
    unit: str | None = None
    reason: str | None = None  # e.g. "kids' standing meals", "restock"


class Household(StrictModel):
    id: str
    name: str
    region: Literal["northern", "southern"] = "northern"
    people: list[Person] = Field(default_factory=list)
    restrictions: list[DietaryRestriction] = Field(default_factory=list)
    equipment: list[str] = Field(default_factory=list)
    # Proteins the household won't eat (e.g. "pork") — recipes with these
    # protein tags are filtered out deterministically, before planning.
    avoid_proteins: list[str] = Field(default_factory=list)
    # Canonical-item swaps applied to every grocery list (e.g. vegetable-oil
    # -> olive-oil): the banned item is never bought; its quantities aggregate
    # under the substitute instead.
    item_substitutions: dict[str, str] = Field(default_factory=dict)
    dinners_per_week: int = Field(default=5, ge=1, le=7)
    budget_cents_weekly: int | None = None
    budget_enabled: bool = False
