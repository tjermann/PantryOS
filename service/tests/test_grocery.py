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
        # Unmatched items are never dropped — now parsed into name + quantity.
        mystery_line = next(
            l for l in result.lines if "special sauce" in l.display_name.lower()
        )
        assert mystery_line.section == "other"
        assert mystery_line.qty == 1

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

    def test_item_substitutions_redirect_purchases(self):
        fry = make_recipe(
            "fry",
            ingredients=[
                ing("vegetable-oil", "3 tbsp vegetable oil", 3, "tbsp"),
                ing("olive-oil", "1 tbsp olive oil", 1, "tbsp"),
            ],
        )
        result = build_grocery_list(
            recipes=[(fry, 4)], pantry=[], standing=[], items=ITEMS,
            budget_enabled=False, budget_cents=None,
            substitutions={"vegetable-oil": "olive-oil"},
        )
        assert line_for(result, "vegetable-oil") is None
        olive = line_for(result, "olive-oil")
        assert olive.qty == pytest.approx(4)  # 3 subbed + 1 native, aggregated

    def test_staples_assumed_on_hand_except_restock(self):
        seasoned = make_recipe(
            "seasoned",
            ingredients=[
                ing("chicken-thigh", "1 lb chicken thighs", 1, "lb"),
                ing("olive-oil", "2 tbsp olive oil", 2, "tbsp"),
                ing(None, "1 tsp smoked paprika", 1, "tsp"),
                ing(None, "salt and black pepper", None, None),
            ],
        )
        result = build_grocery_list(
            recipes=[(seasoned, 4)],
            pantry=[],
            standing=[StandingOrderLine(canonical_item_id="olive-oil", raw="olive oil",
                                        qty=1, unit="each", reason="restock")],
            items=ITEMS,
            budget_enabled=False, budget_cents=None,
            staples=["olive oil", "smoked paprika", "salt"],
        )
        names = [l.display_name for l in result.lines]
        assert any("chicken" in n.lower() for n in names)      # real item bought
        assert not any("paprika" in n.lower() for n in names)  # staple dropped
        assert not any("salt" in n.lower() for n in names)
        # restock bypasses the staple filter — we explicitly ran out
        assert any(l.origin == "restock" for l in result.lines)
        assert "Olive oil" in result.assumed_on_hand or "2 tbsp olive oil" in str(result.assumed_on_hand)

    def test_unmatched_ingredients_aggregate_by_name(self):
        from mealplanner.grocery.parse import aggregation_key, parse_qty_unit

        assert parse_qty_unit("2 lemons, juiced") == (2, "each", "lemons")
        assert parse_qty_unit("1 lemon") == (1, "each", "lemon")
        assert parse_qty_unit("1 1/2 lb shrimp, peeled") == (1.5, "lb", "shrimp")
        assert parse_qty_unit("1/4 cup olive oil") == (0.25, "cup", "olive oil")
        assert aggregation_key("2 Lemons") == aggregation_key("lemon")

        a = make_recipe("a", ingredients=[ing(None, "2 lemons, juiced", None, None)])
        b = make_recipe("b", ingredients=[ing(None, "1 lemon", None, None)])
        result = build_grocery_list(
            recipes=[(a, 4), (b, 4)], pantry=[], standing=[], items=ITEMS,
            budget_enabled=False, budget_cents=None,
        )
        lemons = [l for l in result.lines if "lemon" in l.display_name.lower()]
        assert len(lemons) == 1, [l.display_name for l in result.lines]
        assert lemons[0].qty == 3

    def test_herbs_collapse_to_one_bunch_across_measures(self):
        a = make_recipe("a", ingredients=[ing("dill", "1 1/2 sprigs dill", 1.5, "sprigs")])
        b = make_recipe("b", ingredients=[ing("dill", "2 tbsp fresh dill", 2, "tbsp")])
        c = make_recipe("c", ingredients=[ing("dill", "1 tbsp dill", 1, "tbsp")])
        result = build_grocery_list(
            recipes=[(a, 4), (b, 4), (c, 4)], pantry=[], standing=[], items=ITEMS,
            budget_enabled=False, budget_cents=None,
        )
        dill = [l for l in result.lines if (l.canonical_item_id == "dill")]
        assert len(dill) == 1, [l.display_name for l in result.lines]
        assert dill[0].unit == "bunch" and dill[0].qty == 1
        assert set(dill[0].source_recipe_ids) == {"a", "b", "c"}

    def test_same_item_same_dimension_merges(self):
        a = make_recipe("a", ingredients=[ing("chicken-thigh", "1 lb chicken", 1, "lb")])
        b = make_recipe("b", ingredients=[ing("chicken-thigh", "8 oz chicken", 8, "oz")])
        result = build_grocery_list(
            recipes=[(a, 4), (b, 4)], pantry=[], standing=[], items=ITEMS,
            budget_enabled=False, budget_cents=None,
        )
        chicken = [l for l in result.lines if l.canonical_item_id == "chicken-thigh"]
        assert len(chicken) == 1
        assert chicken[0].qty == pytest.approx(1.5)  # 1 lb + 8 oz

    def test_household_exclusions_drop_items_for_the_week(self):
        result = build_grocery_list(
            recipes=[(RICE_BOWL, 4)], pantry=[], standing=[], items=ITEMS,
            budget_enabled=False, budget_cents=None,
            excluded=["Jasmine rice", "  CILANTRO "],  # case/space tolerant
        )
        names = [l.display_name for l in result.lines]
        assert "Jasmine rice" not in names and "Cilantro" not in names
        assert any("Chicken" in n for n in names)  # untouched items still bought
        assert set(result.removed_by_household) == {"Jasmine rice", "Cilantro"}

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


class TestDisplayCollapse:
    """One item, one row — even when its quantities can't be added together."""

    def test_same_item_different_dimensions_becomes_one_row(self):
        from mealplanner.grocery.display import collapse_rows

        class L:
            def __init__(self, name, qty, unit):
                self.display_name, self.qty, self.unit = name, qty, unit

        rows = collapse_rows([
            L("Yellow onions", 1, "cup"),
            L("Yellow onions", 1, None),
            L("Limes", 3, None),
        ])
        assert rows == [("Yellow onions", "1 cup + 1"), ("Limes", "3")]

    def test_identical_quantities_are_not_repeated(self):
        from mealplanner.grocery.display import collapse_rows

        class L:
            def __init__(self, name, qty, unit):
                self.display_name, self.qty, self.unit = name, qty, unit

        assert collapse_rows([L("Dill", 1, "bunch"), L("Dill", 1, "bunch")]) == [
            ("Dill", "1 bunch")
        ]


class TestAmountlessKnownItems:
    """'Cilantro, for garnish' is cilantro, not a mystery row."""

    def _line_names(self, recipes):
        from mealplanner.allergen.ontology import load_ontology
        from mealplanner.grocery.pipeline import build_grocery_list

        result = build_grocery_list(
            recipes=recipes, pantry=[], standing=[], items=load_ontology(),
            budget_enabled=False, budget_cents=None, substitutions={},
        )
        return [(l.display_name, l.section, l.qty) for l in result.lines]

    def test_it_merges_with_a_measured_mention_of_the_same_item(self):
        from fixtures_helpers import make_recipe

        garnish = make_recipe("a", ingredients=[
            {"canonical_item_id": "cilantro", "raw": "Chopped cilantro, for garnish",
             "qty": None, "unit": None},
        ])
        measured = make_recipe("b", ingredients=[
            {"canonical_item_id": "cilantro", "raw": "2 tbsp minced cilantro",
             "qty": 2, "unit": "tbsp"},
        ])
        names = self._line_names([(garnish, 4), (measured, 4)])
        cilantro = [n for n in names if "ilantro" in n[0]]
        assert len(cilantro) == 1, cilantro
        assert cilantro[0][0] == "Cilantro"
        assert cilantro[0][1] == "produce"  # its real aisle, not 'other'

    def test_an_amountless_mention_does_not_erase_a_quantity(self):
        """Herbs collapse to bunches, so use something bought by weight."""
        from fixtures_helpers import make_recipe

        measured = make_recipe("b", ingredients=[
            {"canonical_item_id": "chicken-breast", "raw": "2 lb chicken breasts",
             "qty": 2, "unit": "lb"},
        ])
        garnish = make_recipe("a", ingredients=[
            {"canonical_item_id": "chicken-breast", "raw": "chicken breast, to serve",
             "qty": None, "unit": None},
        ])
        rows = [l for l in self._line_names([(measured, 4), (garnish, 4)])
                if "hicken" in l[0]]
        assert sum(q for _, _, q in rows if q) == 2


class TestNonPurchases:
    """Tap water and 'For the sauce:' headers are not shopping."""

    def test_water_and_headers_are_skipped(self):
        from mealplanner.grocery.pipeline import is_purchasable

        for raw in ["2 cups water", "1 cup cold water", "water",
                    "To garnish:", "For the sauce:", ":", "  "]:
            assert not is_purchasable(raw), raw

    def test_real_ingredients_survive(self):
        from mealplanner.grocery.pipeline import is_purchasable

        for raw in ["1 lb chicken breasts", "Cotija cheese", "1 water chestnut can",
                    "2 cups watermelon"]:
            assert is_purchasable(raw), raw


class TestCanonicalMatching:
    def _items(self):
        from mealplanner.allergen.ontology import load_ontology

        return load_ontology()

    def test_matches_despite_accents_and_padding(self):
        from mealplanner.recipes.canonicalize import match_line

        assert match_line("1/2 large jalapeño, seeded and minced", self._items()) == "jalapeno"

    def test_a_modifier_is_not_mistaken_for_the_product(self):
        """avocado oil is not an avocado; garlic powder is not garlic."""
        from mealplanner.recipes.canonicalize import match_line

        items = self._items()
        assert match_line("1 teaspoon avocado oil", items) == "avocado-oil"
        assert match_line("1 tsp garlic powder", items) == "garlic-powder"
        assert match_line("2 cloves garlic, minced", items) == "garlic"
        # a usage word still means buying the whole thing
        assert match_line("2 tablespoons lime juice", items) == "lime"

    def test_backfill_never_overwrites_an_existing_id(self):
        from mealplanner.recipes.canonicalize import backfill

        recipe = {"ingredients": [
            {"canonical_item_id": "chicken-thigh", "raw": "1 lb chicken breasts"},
            {"canonical_item_id": None, "raw": "1 lb chicken breasts"},
        ]}
        assert backfill([recipe], self._items()) == 1
        assert recipe["ingredients"][0]["canonical_item_id"] == "chicken-thigh"
        assert recipe["ingredients"][1]["canonical_item_id"] == "chicken-breast"


class TestOntologyAllergenSafety:
    """The backstop trusts this data, so cheese must declare dairy."""

    def _items(self):
        from mealplanner.allergen.ontology import load_ontology

        return load_ontology()

    def test_dairy_sounding_items_either_declare_it_or_deny_it(self):
        """Silence is the bug: an item that reads as dairy must say which it is,
        so 'coconut cream' stays safe for a dairy allergy and ricotta does not."""
        for item in self._items().values():
            name = item.name.lower()
            if any(w in name for w in ("cheese", "ricotta", "cotija", "cream")):
                assert ("dairy" in item.allergens) or ("dairy" in item.not_allergens), \
                    f"{item.id} says nothing about dairy"

    def test_wheat_staples_declare_gluten(self):
        items = self._items()
        for item_id in ("pasta", "lasagna-noodles", "breadcrumbs", "bread",
                        "flour-tortilla", "farro", "couscous"):
            assert "gluten" in items[item_id].allergens, item_id

    def test_nuts_declare_tree_nut(self):
        items = self._items()
        for item_id in ("pecans", "walnuts", "almond", "cashew"):
            assert "tree_nut" in items[item_id].allergens, item_id

    def test_ids_are_unique(self):
        import yaml
        from pathlib import Path

        raw = yaml.safe_load(
            Path("mealplanner/allergen/ontology_data.yaml").read_text())
        ids = [i["id"] for group in raw.values() for i in group] \
            if isinstance(raw, dict) else [i["id"] for i in raw]
        assert len(ids) == len(set(ids))
