"""Picking a subset of a shortlist proposal."""

from fixtures_helpers import make_household
from mealplanner.planning.selection import resolve_selection

WEEK = ["2026-08-16", "2026-08-17", "2026-08-18", "2026-08-19"]


def plan(selected=None, dinners=7, lunches=2):
    entries = [
        {"recipe_id": f"d{i}", "date": f"2026-08-{16 + i}", "meal_type": "dinner",
         "servings": 4, "rationale": ""}
        for i in range(dinners)
    ] + [
        {"recipe_id": f"l{i}", "date": "2026-08-16", "meal_type": "lunch",
         "servings": 4, "rationale": ""}
        for i in range(lunches)
    ]
    return {"entries": entries, "week_dates": WEEK, "selected": selected}


def household(dinners=4, lunches=1):
    h = make_household()
    h.dinners_per_week = dinners
    h.lunches_per_week = lunches
    return h


class TestResolveSelection:
    def test_picks_are_honored_and_redated(self):
        chosen = resolve_selection(plan(["d1", "d3", "d5", "d6", "l1"]), household())
        dinners = [e for e in chosen if e["meal_type"] == "dinner"]
        assert [e["recipe_id"] for e in dinners] == ["d1", "d3", "d5", "d6"]
        # placeholder option dates are replaced by the real nights, in order
        assert [e["date"] for e in dinners] == WEEK
        lunch = [e for e in chosen if e["meal_type"] == "lunch"]
        assert [e["recipe_id"] for e in lunch] == ["l1"]
        assert lunch[0]["date"] == WEEK[0]  # batch-cooked at the start

    def test_no_pick_falls_back_to_the_top_options(self):
        chosen = resolve_selection(plan(None), household())
        assert [e["recipe_id"] for e in chosen] == ["d0", "d1", "d2", "d3", "l0"]

    def test_partial_pick_is_topped_up_in_planner_order(self):
        chosen = resolve_selection(plan(["d5", "l1"]), household())
        dinners = [e["recipe_id"] for e in chosen if e["meal_type"] == "dinner"]
        assert dinners[0] == "d5"  # their pick leads
        assert dinners[1:] == ["d0", "d1", "d2"]  # filled from the top
        assert len(dinners) == 4

    def test_unknown_ids_in_selection_are_ignored(self):
        chosen = resolve_selection(plan(["ghost", "d2"]), household())
        assert [e["recipe_id"] for e in chosen if e["meal_type"] == "dinner"][0] == "d2"
        assert len([e for e in chosen if e["meal_type"] == "dinner"]) == 4

    def test_plain_proposal_is_untouched_apart_from_dates(self):
        """No shortlist configured: 4 dinners in, the same 4 out."""
        chosen = resolve_selection(plan(None, dinners=4, lunches=1), household())
        assert [e["recipe_id"] for e in chosen] == ["d0", "d1", "d2", "d3", "l0"]

    def test_a_cut_dish_is_backfilled_not_left_missing(self):
        """weekly.py strips 'never again' entries before resolving; the week
        still gets a full four dinners."""
        p = plan(["d0", "d1", "d2", "d3"])
        p["entries"] = [e for e in p["entries"] if e["recipe_id"] != "d2"]
        dinners = [e["recipe_id"] for e in resolve_selection(p, household())
                   if e["meal_type"] == "dinner"]
        assert dinners == ["d0", "d1", "d3", "d4"]
        assert len(dinners) == 4


class TestHouseholdShortlistFlags:
    def test_offers_choice_only_when_options_exceed_the_week(self):
        h = household()
        assert not h.offers_choice
        assert h.shortlist_dinners == 4
        h.dinner_options = 7
        assert h.offers_choice and h.shortlist_dinners == 7
        assert h.shortlist_lunches == 1  # untouched


class TestWeekDates:
    """Cooking starts the day after the cart is loaded, whenever we plan."""

    def test_proposal_and_shopping_run_name_the_same_nights(self):
        from datetime import date

        from mealplanner.jobs.common import next_week_dates

        friday, sunday = date(2026, 8, 14), date(2026, 8, 16)
        from_proposal = next_week_dates(friday, 4, "sunday")
        from_shopping = next_week_dates(sunday, 4, "sunday")
        assert from_proposal == from_shopping
        assert from_proposal[0] == date(2026, 8, 17)  # Monday

    def test_two_day_review_window(self):
        from datetime import date

        from mealplanner.jobs.common import next_week_dates

        # Proposed Friday, carted Sunday: Friday and Saturday are for choosing.
        assert next_week_dates(date(2026, 8, 14), 1, "sunday")[0] == date(2026, 8, 17)

    def test_one_day_window_still_works(self):
        from datetime import date

        from mealplanner.jobs.common import next_week_dates

        assert next_week_dates(date(2026, 8, 14), 1, "saturday")[0] == date(2026, 8, 16)


class TestCarriedOverMeals:
    """A dish moved from a week it never got cooked: on the menu, off the list."""

    def test_on_hand_meals_are_excluded_from_shopping_only(self):
        from mealplanner.planning.selection import needs_shopping, resolve_selection

        p = plan(["d0", "d1", "l0"], dinners=3, lunches=1)
        p["select_dinners"] = 3
        p["entries"][2]["ingredients_on_hand"] = True  # d2, topped up into the week
        menu = resolve_selection(p, household(dinners=4))
        assert [e["recipe_id"] for e in menu if e["meal_type"] == "dinner"] == \
            ["d0", "d1", "d2"]
        assert [e["recipe_id"] for e in needs_shopping(menu)] == ["d0", "d1", "l0"]

    def test_plan_level_count_overrides_the_household_default(self):
        """Cooking three dinners this week shouldn't rewrite standing config."""
        p = plan(["d0", "d1", "d5"])
        p["select_dinners"] = 3
        dinners = [e for e in resolve_selection(p, household(dinners=4))
                   if e["meal_type"] == "dinner"]
        assert [e["recipe_id"] for e in dinners] == ["d0", "d1", "d5"]
        assert [e["date"] for e in dinners] == WEEK[:3]  # only three nights used


class TestIterateRespectsPicks:
    """A machine revision must never overrule a person's choice."""

    def _setup(self, tmp_path, selected, entries_extra=()):
        from mealplanner.config import EmailConfig, UserConfig, save_user_config, user_dir
        from mealplanner.schemas.domain import Household
        from mealplanner.state.store import StateStore

        config = UserConfig(
            name="T", email=EmailConfig(to=["a@b.c"]),
            recipe_library=str(tmp_path / "lib"), proposal_day="friday",
            household=Household(id="t", name="T", dinners_per_week=2),
        )
        save_user_config("t", config, tmp_path)
        store = StateStore(user_dir("t", tmp_path))
        store.save_plan("2026-W35", {
            "week": "2026-W35", "status": "proposed", "iteration": 1,
            "fingerprint": "stale", "week_dates": ["2026-08-24", "2026-08-25"],
            "select_dinners": 2, "selected": selected,
            "entries": [
                {"recipe_id": "a", "date": "2026-08-24", "meal_type": "dinner",
                 "servings": 4, "rationale": "", "person_handling": []},
                *entries_extra,
            ],
        })
        return store

    def test_new_feedback_does_not_rewrite_a_plan_with_picks(self, tmp_path):
        from mealplanner.jobs.propose import run_iterate

        store = self._setup(tmp_path, selected=["a"])
        # No LLM is stubbed: if this tried to re-plan it would blow up.
        assert run_iterate("t", base=tmp_path, today=__import__("datetime").date(2026, 8, 22)) == 0
        plan = store.load_plan("2026-W35")
        assert plan["selected"] == ["a"]
        assert plan["iteration"] == 1
        assert plan["fingerprint"] != "stale"  # settled, so it stops re-firing

    def test_carried_over_meals_are_kept_for_the_revision(self, tmp_path):
        """Food already in the fridge survives a re-plan even with no picks."""
        carried = {"recipe_id": "leftover", "date": "2026-08-25",
                   "meal_type": "dinner", "servings": 4, "rationale": "",
                   "person_handling": [], "ingredients_on_hand": True}
        store = self._setup(tmp_path, selected=None, entries_extra=[carried])
        plan = store.load_plan("2026-W35")
        kept = [e for e in plan["entries"] if e.get("ingredients_on_hand")]
        assert kept == [carried]


class TestStaleReferences:
    """A sentence about a dish nobody picked doesn't belong in the final email."""

    KEPT = ["30-Minute Chicken Peanut Noodles", "30-Minute Mediterranean Chicken Bowls",
            "3 garlic cloves, minced", "2 cups spinach"]
    DROPPED = ["Turkey Sweet Potato Chili", "Thai Coconut Mussels with Garlic Lemongrass Toast",
               "Sheet Pan Harissa Chicken with Chickpeas and Sweet Potatoes"]

    def _drop(self, text):
        from mealplanner.planning.selection import drop_stale_references

        return drop_stale_references(text, self.KEPT, self.DROPPED)

    def test_sentence_naming_an_unpicked_dish_is_removed(self):
        text = ("The quick Asian noodle night, done in 30 minutes. "
                "It uses up the rest of the chili's bell peppers.")
        assert self._drop(text) == "The quick Asian noodle night, done in 30 minutes."

    def test_words_shared_with_the_chosen_meals_never_cost_a_sentence(self):
        """'garlic' is in a dropped title but also in what's being cooked."""
        text = "Lots of garlic and chicken, ready in half an hour."
        assert self._drop(text) == text

    def test_plural_forms_are_recognised(self):
        assert self._drop("Pairs well with the leftover sweet potatoes.") == ""

    def test_nothing_dropped_means_nothing_changes(self):
        from mealplanner.planning.selection import drop_stale_references

        text = "It uses up the chili's bell peppers."
        assert drop_stale_references(text, self.KEPT, []) == text
