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
