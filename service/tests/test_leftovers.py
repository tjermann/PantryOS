"""Leftovers from earlier orders, and fresh-versus-dried herbs."""

from datetime import date, timedelta

from fixtures_helpers import make_recipe
from mealplanner.allergen.ontology import load_ontology
from mealplanner.grocery.leftovers import Batch, keeps_for, settle
from mealplanner.grocery.pipeline import build_grocery_list

TODAY = date(2026, 9, 20)
LATER = (TODAY + timedelta(days=60)).isoformat()


def items():
    return load_ontology()


def build(ingredients, leftovers=None, staples=None):
    return build_grocery_list(
        recipes=[(make_recipe("r", ingredients=ingredients), 4)], pantry=[], standing=[],
        items=items(), budget_enabled=False, budget_cents=None, substitutions={},
        staples=staples or [], leftovers=leftovers, as_of=TODAY,
    )


def names(result):
    return [l.display_name for l in result.lines]


def ing(item_id, raw, qty, unit):
    return {"canonical_item_id": item_id, "raw": raw, "qty": qty, "unit": unit}


class TestWhatKeeps:
    def test_items_are_tracked_the_way_they_are_sold(self):
        o = items()
        assert (keeps_for(o["sriracha"]).unit, keeps_for(o["sriracha"]).package) == ("tbsp", 34)
        assert keeps_for(o["garlic-powder"]).unit == "tsp"
        assert keeps_for(o["dried-thyme"]).unit == "tsp"
        assert keeps_for(o["yellow-onion"]).unit == "each"
        assert keeps_for(o["cilantro"]).shelf_days == 7
        assert keeps_for(o["thyme"]).shelf_days == 14
        assert keeps_for(o["chicken-breast"]) is None  # not worth guessing about


class TestUsingLeftovers:
    def test_an_opened_bottle_is_not_bought_again(self):
        result = build([ing("sriracha", "1 tbsp sriracha", 1, "tbsp")],
                       leftovers=[Batch("sriracha", "Sriracha", 33, "tbsp", LATER)])
        assert "Sriracha" not in names(result)
        assert [u.item_id for u in result.leftovers_used] == ["sriracha"]

    def test_half_an_onion_means_buying_one_fewer(self):
        result = build([ing("yellow-onion", "1 onion", 1, "each"),
                        ing("yellow-onion", "1/2 onion", 0.5, "each")],
                       leftovers=[Batch("yellow-onion", "Yellow onions", 0.5, "each", LATER)])
        [onion] = [l for l in result.lines if l.display_name == "Yellow onions"]
        assert onion.qty == 1

    def test_a_partly_used_bunch_covers_a_small_measure(self):
        result = build([ing("cilantro", "2 tbsp cilantro", 2, "tbsp")],
                       leftovers=[Batch("cilantro", "Cilantro", 0.75, "bunch", LATER)])
        assert "Cilantro" not in names(result)

    def test_expired_leftovers_are_ignored(self):
        stale = (TODAY - timedelta(days=1)).isoformat()
        result = build([ing("sriracha", "1 tbsp sriracha", 1, "tbsp")],
                       leftovers=[Batch("sriracha", "Sriracha", 33, "tbsp", stale)])
        assert "Sriracha" in names(result)

    def test_units_that_cannot_be_compared_are_never_guessed(self):
        result = build([ing("parmesan", "2 oz parmesan", 2, "oz")],
                       leftovers=[Batch("parmesan", "Parmesan", 1, "cup", LATER)])
        assert any("armesan" in n for n in names(result))
        assert result.leftovers_used == []

    def test_the_callers_ledger_is_left_untouched(self):
        ledger = [Batch("sriracha", "Sriracha", 33, "tbsp", LATER)]
        build([ing("sriracha", "1 tbsp sriracha", 1, "tbsp")], leftovers=ledger)
        assert ledger[0].qty == 33  # previews must not use anything up


class TestSettlingAnOrder:
    def test_a_new_bottle_records_what_is_left(self):
        result = build([ing("sriracha", "1 tbsp sriracha", 1, "tbsp")])
        ledger = settle([], result.leftovers_used, result.lines, items(), TODAY, "2026-W39")
        assert [(b.item_id, b.qty, b.unit) for b in ledger] == [("sriracha", 33.0, "tbsp")]
        assert ledger[0].expires == (TODAY + timedelta(days=180)).isoformat()

    def test_leftovers_are_used_before_a_new_package_is_opened(self):
        old = [Batch("sriracha", "Sriracha", 2, "tbsp", LATER)]
        result = build([ing("sriracha", "5 tbsp sriracha", 5, "tbsp")], leftovers=old)
        ledger = settle(old, result.leftovers_used, result.lines, items(), TODAY, "W")
        assert [(b.qty, b.unit) for b in ledger] == [(31.0, "tbsp")]  # 34 - (5 - 2)

    def test_whole_items_count_what_was_actually_bought(self):
        result = build([ing("yellow-onion", "1 1/2 onions", 1.5, "each")])
        ledger = settle([], result.leftovers_used, result.lines, items(), TODAY, "W")
        assert [(b.item_id, b.qty) for b in ledger] == [("yellow-onion", 0.5)]

    def test_ran_out_clears_the_item(self, tmp_path):
        from mealplanner.state.store import StateStore

        store = StateStore(tmp_path)
        store.save_leftovers([Batch("sriracha", "Sriracha", 33, "tbsp", LATER)])
        assert store.clear_leftover("sriracha")
        assert store.load_leftovers() == []


class TestHerbBunches:
    def test_a_few_tablespoons_are_one_bunch_not_several(self):
        """The old herb rule read '2 tbsp dill' as two bunches."""
        result = build([ing("dill", "2 tbsp dill", 2, "tbsp")])
        [dill] = [l for l in result.lines if l.display_name.lower().startswith("dill")]
        assert (dill.qty, dill.unit) == (1.0, "bunch")

    def test_two_cups_of_basil_is_two_bunches(self):
        result = build([ing("basil", "2 cups basil", 2, "cup")])
        [basil] = [l for l in result.lines if l.display_name.lower().startswith("basil")]
        assert basil.qty == 2


class TestDriedHerbs:
    def match(self, raw):
        from mealplanner.recipes.canonicalize import match_line

        return match_line(raw, items())

    def test_a_recipe_that_asks_for_dried_gets_dried(self):
        assert self.match("1/2 teaspoon dried thyme") == "dried-thyme"
        assert self.match("1 tsp rosemary, dried, crushed") == "dried-rosemary"
        assert self.match("1 tsp dried mint") == "dried-mint"

    def test_fresh_wins_when_the_recipe_offers_a_choice(self):
        assert self.match("2 teaspoons fresh dill (or 1/2 teaspoon dried dill)") == "dill"
        assert self.match("1/4 cup fresh basil, chopped ((or 2 tsp dried))") == "basil"
        assert self.match("1 tbsp fresh or 1 tsp dried thyme") == "thyme"

    def test_an_unspecified_herb_is_fresh(self):
        assert self.match("2 tablespoons chopped parsley") == "parsley"

    def test_old_matches_move_only_when_dried_is_specific(self):
        from mealplanner.recipes.canonicalize import rematch_herb_forms

        recipe = {"ingredients": [
            {"canonical_item_id": "thyme", "raw": "1/2 teaspoon dried thyme"},
            {"canonical_item_id": "dill", "raw": "2 tsp fresh dill (or 1/2 tsp dried)"},
        ]}
        assert rematch_herb_forms([recipe], items()) == 1
        assert [i["canonical_item_id"] for i in recipe["ingredients"]] == ["dried-thyme", "dill"]

    def test_dried_herbs_are_pantry_jars_not_bunches(self):
        result = build([ing("dried-thyme", "1/2 tsp dried thyme", 0.5, "tsp")])
        [line] = [l for l in result.lines if l.display_name == "Dried thyme"]
        assert line.unit == "tsp" and line.section == "pantry"

    def test_a_dried_staple_is_not_bought(self):
        result = build([ing("dried-oregano", "1 tsp dried oregano", 1, "tsp")],
                       staples=["oregano"])
        assert "Dried oregano" not in names(result)

    def test_the_cart_buys_dried_only_when_asked(self):
        from mealplanner.carts.selector_driver import form_score

        assert form_score("Dried thyme", "McCormick Thyme Leaves, Dried") > \
            form_score("Dried thyme", "Fresh Thyme Bunch")
        assert form_score("Thyme", "Fresh Thyme Bunch") > \
            form_score("Thyme", "McCormick Thyme Leaves, Dried")


class TestWhichWeeksCount:
    def test_a_week_never_counts_its_own_leftovers(self):
        """Viewing an already-ordered week must not shrink its list by what that
        very order left over."""
        from mealplanner.grocery.leftovers import from_before

        ledger = [Batch("sriracha", "Sriracha", 33, "tbsp", LATER, week="2026-W38"),
                  Batch("ketchup", "Ketchup", 50, "tbsp", LATER, week="2026-W37"),
                  Batch("honey", "Honey", 10, "tbsp", LATER, week="")]
        assert [b.item_id for b in from_before(ledger, "2026-W38")] == ["ketchup", "honey"]
        assert [b.item_id for b in from_before(ledger, "2026-W39")] == \
            ["sriracha", "ketchup", "honey"]


class TestDriedHerbEdgeCases:
    def test_fresh_herb_with_a_different_dried_alternative_stays_fresh(self):
        from mealplanner.recipes.canonicalize import match_line

        raw = "1 teaspoon finely chopped fresh flat-leaf parsley, or a light sprinkle of dried oregano"
        assert match_line(raw, items()) == "parsley"

    def test_migration_never_swaps_one_herb_for_another(self):
        from mealplanner.recipes.canonicalize import rematch_herb_forms

        recipe = {"ingredients": [{
            "canonical_item_id": "parsley",
            "raw": "chopped parsley, or a sprinkle of dried oregano",
        }]}
        assert rematch_herb_forms([recipe], items()) == 0
        assert recipe["ingredients"][0]["canonical_item_id"] == "parsley"
