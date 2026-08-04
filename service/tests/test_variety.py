"""Port of packages/engine/test/variety.test.ts."""

from fixtures_helpers import make_household, make_recipe, state_map
from mealplanner.planning.candidates import filter_candidates, season_for_month
from mealplanner.planning.variety import validate_variety
from mealplanner.schemas.plan import PlanEntryProposal


def entry(recipe_id: str, date: str) -> PlanEntryProposal:
    return PlanEntryProposal(recipe_id=recipe_id, date=date, servings=4, rationale="")


def recipes_map(*recipes):
    return {r.id: r for r in recipes}


class TestValidateVariety:
    def test_three_same_protein_flagged(self):
        recipes = recipes_map(
            make_recipe("a", protein="chicken"),
            make_recipe("b", protein="chicken", cuisine="thai"),
            make_recipe("c", protein="chicken", cuisine="mexican"),
        )
        violations = validate_variety(
            [entry("a", "2026-08-03"), entry("b", "2026-08-05"), entry("c", "2026-08-07")],
            recipes,
            state_map([]),
        )
        assert any(v.code == "protein_overload" for v in violations)

    def test_back_to_back_cuisine_only_consecutive(self):
        recipes = recipes_map(
            make_recipe("a", cuisine="italian", protein="pork"),
            make_recipe("b", cuisine="italian", protein="beef"),
        )
        consecutive = validate_variety(
            [entry("a", "2026-08-03"), entry("b", "2026-08-04")], recipes, state_map([])
        )
        assert any(v.code == "back_to_back_similar" for v in consecutive)
        spaced = validate_variety(
            [entry("a", "2026-08-03"), entry("b", "2026-08-06")], recipes, state_map([])
        )
        assert not any(v.code == "back_to_back_similar" for v in spaced)

    def test_consecutive_involved_flagged(self):
        recipes = recipes_map(
            make_recipe("a", effort="involved", protein="pork"),
            make_recipe("b", effort="involved", protein="beef", cuisine="french"),
        )
        violations = validate_variety(
            [entry("a", "2026-08-03"), entry("b", "2026-08-04")], recipes, state_map([])
        )
        assert any(v.code == "effort_stacking" for v in violations)

    def test_recent_repeat_flagged(self):
        recipes = recipes_map(make_recipe("a"))
        violations = validate_variety(
            [entry("a", "2026-08-03")],
            recipes,
            state_map([{"recipe_id": "a", "last_made_at": "2026-07-25"}]),
        )
        assert any(v.code == "recent_repeat" for v in violations)

    def test_unknown_recipe_is_error(self):
        violations = validate_variety([entry("ghost", "2026-08-03")], {}, state_map([]))
        assert violations[0].code == "unknown_recipe"
        assert violations[0].severity == "error"


class TestSeasonForMonth:
    def test_northern_meteorological(self):
        assert season_for_month(1, "northern") == "winter"
        assert season_for_month(4, "northern") == "spring"
        assert season_for_month(7, "northern") == "summer"
        assert season_for_month(10, "northern") == "fall"

    def test_hemisphere_flip(self):
        assert season_for_month(1, "southern") == "summer"
        assert season_for_month(7, "southern") == "winter"


class TestFilterCandidates:
    def test_filters_season_lifecycle_equipment(self):
        household = make_household(equipment=["sheet_pan"], avoid_proteins=["Pork"])
        candidates, rejected = filter_candidates(
            [
                make_recipe("in-season", seasons=["summer"]),
                make_recipe("year-round", seasons=["year_round"]),
                make_recipe("wintery", seasons=["winter"]),
                make_recipe("cut-recipe", seasons=["summer"]),
                make_recipe("needs-ip", seasons=["summer"], equipment=["instant_pot"]),
                make_recipe("porky", seasons=["summer"], protein="pork"),
            ],
            state_map([{"recipe_id": "cut-recipe", "lifecycle": "cut"}]),
            household,
            month=7,
        )
        assert sorted(r.id for r in candidates) == ["in-season", "year-round"]
        reasons = {(r.recipe_id, r.reason) for r in rejected}
        assert ("wintery", "out_of_season") in reasons
        assert ("cut-recipe", "lifecycle_cut") in reasons
        assert ("needs-ip", "missing_equipment") in reasons
        assert ("porky", "avoided_protein") in reasons
