"""Port of packages/engine/test/grocery.test.ts."""

import pytest
from fixtures_helpers import ITEMS, ing, make_recipe
from mealplanner.grocery.pipeline import build_grocery_list
from mealplanner.grocery.units import convert, normalize_unit
from mealplanner.planning.long_lead import detect_long_lead
from mealplanner.schemas.domain import PantryItem, RecipeStep, StandingOrderLine


class TestUnits:
    def test_normalize_aliases(self):
        assert normalize_unit("Tablespoons") == "tbsp"
        assert normalize_unit("LBS") == "lb"
        assert normalize_unit(None) == "each"

    def test_convert_within_dimension(self):
        assert convert(1, "lb", "oz") == pytest.approx(16, rel=0.01)
        assert convert(3, "tsp", "tbsp") == pytest.approx(1, rel=0.01)
        assert convert(2, "cup", "ml") == pytest.approx(473.2, abs=0.5)

    def test_cross_dimension_refused(self):
        assert convert(1, "cup", "lb") is None
        assert convert(2, "bunch", "oz") is None


RICE_BOWL = make_recipe(
    "rice-bowl",
    serves=4,
    ingredients=[
        ing("rice", "1 cup rice", 1, "cup"),
        ing("chicken-thigh", "1 lb chicken thighs", 1, "lb"),
        ing("cilantro", "1 bunch cilantro", 1, "bunch"),
    ],
)
CURRY = make_recipe(
    "curry",
    serves=4,
    ingredients=[
        ing("rice", "2 cups rice", 2, "cup"),
        ing("coconut-milk", "1 can coconut milk", 1, "can"),
        ing("cilantro", "1 bunch cilantro", 1, "bunch"),
    ],
)


def build(recipes, pantry=(), standing=(), budget_enabled=False, budget_cents=None):
    return build_grocery_list(
        recipes=list(recipes),
        pantry=list(pantry),
        standing=list(standing),
        items=ITEMS,
        budget_enabled=budget_enabled,
        budget_cents=budget_cents,
    )


def line_for(result, item_id):
    return next((l for l in result.lines if l.canonical_item_id == item_id), None)


class TestBuildGroceryList:
    def test_aggregates_across_recipes_with_conversion(self):
        result = build([(RICE_BOWL, 4), (CURRY, 4)])
        rice = line_for(result, "rice")
        assert rice.qty == pytest.approx(3)
        assert rice.source_recipe_ids == ["rice-bowl", "curry"]
        assert line_for(result, "cilantro").qty == 2

    def test_scales_for_servings(self):
        result = build([(RICE_BOWL, 8)])
        assert line_for(result, "chicken-thigh").qty == pytest.approx(2)

    def test_pantry_confirmed_subtracted_assumed_ignored(self):
        result = build(
            [(CURRY, 4)],
            pantry=[
                PantryItem(canonical_item_id="rice", qty=1, unit="cup", confidence="confirmed"),
                PantryItem(canonical_item_id="coconut-milk", qty=1, unit="can", confidence="assumed"),
            ],
        )
        rice = line_for(result, "rice")
        assert rice.qty == pytest.approx(1)
        assert rice.pantry_adjusted is True
        assert line_for(result, "coconut-milk").qty == 1

    def test_fully_stocked_dropped_unmatched_kept_verbatim(self):
        mystery = make_recipe(
            "mystery",
            ingredients=[
                ing("rice", "1 cup rice", 1, "cup"),
                ing(None, "1 jar special sauce", None, None),
            ],
        )
        result = build(
            [(mystery, 4)],
            pantry=[PantryItem(canonical_item_id="rice", qty=5, unit="cup", confidence="confirmed")],
        )
        assert line_for(result, "rice") is None
        mystery_line = next(l for l in result.lines if l.display_name == "1 jar special sauce")
        assert mystery_line.section == "other"

    def test_standing_lines_and_sections(self):
        result = build(
            [(RICE_BOWL, 4)],
            standing=[
                StandingOrderLine(raw="Chicken nuggets (kids)", qty=1, unit="each",
                                  reason="kids' standing meals"),
                StandingOrderLine(canonical_item_id="oat-milk", raw="oat milk", qty=1,
                                  unit="each", reason="restock"),
            ],
        )
        assert any(l.canonical_item_id == "cilantro" for l in result.sections["produce"])
        assert any(l.origin == "restock" for l in result.sections["dairy"])
        assert any(l.origin == "standing" for l in result.sections["other"])

    def test_budget_only_when_fully_priced(self):
        priced = make_recipe(
            "priced",
            ingredients=[
                ing("chicken-thigh", "1 lb chicken", 1, "lb"),
                ing("cilantro", "1 bunch", 1, "bunch"),
            ],
        )
        result = build([(priced, 4)], budget_enabled=True, budget_cents=5000)
        assert result.est_total_cents == 899 + 149
        assert result.budget.under_budget_cents == 5000 - 1048

        with_unpriced = build(
            [(RICE_BOWL, 4), (CURRY, 4)],
            standing=[StandingOrderLine(raw="mystery")],
            budget_enabled=True,
            budget_cents=5000,
        )
        assert with_unpriced.est_total_cents is None
        assert with_unpriced.budget.under_budget_cents is None


def test_detect_long_lead_threshold():
    recipe = make_recipe(
        "brine",
        steps=[
            RecipeStep(order=1, text="Brine the pork 4 hours.", duration_min=240, unattended=True),
            RecipeStep(order=2, text="Rest 10 minutes.", duration_min=10, unattended=True),
            RecipeStep(order=3, text="Sear 40 min attended.", duration_min=40, unattended=False),
        ],
    )
    flags = detect_long_lead(recipe)
    assert len(flags) == 1
    assert flags[0].step_order == 1 and flags[0].lead_min == 240
