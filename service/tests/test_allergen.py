"""Port of packages/engine/test/allergen.test.ts — same cases, same expected
violation codes and severities."""

from fixtures_helpers import ITEMS, ing, make_household, make_recipe
from mealplanner.allergen.backstop import run_allergen_backstop, split_feasible
from mealplanner.allergen.ontology import item_in_allergen_class
from mealplanner.schemas.plan import PlanEntryProposal, PersonHandling

DAIRY_ALLERGY_HH = make_household(
    restrictions=[{"person_id": "p2", "allergen_class": "dairy", "severity": "allergy"}]
)


def entry_for(recipe_id: str, handling: list[PersonHandling] | None = None) -> PlanEntryProposal:
    return PlanEntryProposal(
        recipe_id=recipe_id,
        date="2026-08-03",
        servings=4,
        rationale="",
        person_handling=handling or [],
    )


def backstop(recipe, entry, household=DAIRY_ALLERGY_HH):
    return run_allergen_backstop(
        entry=entry,
        entry_index=0,
        recipe=recipe,
        people=household.people,
        restrictions=household.restrictions,
        items=ITEMS,
    )


class TestOntologyMembership:
    def test_real_dairy_is_dairy(self):
        assert item_in_allergen_class(ITEMS["milk"], "dairy") == "member"
        assert item_in_allergen_class(ITEMS["heavy-cream"], "dairy") == "member"

    def test_name_traps_are_not_members(self):
        assert item_in_allergen_class(ITEMS["coconut-milk"], "dairy") == "non_member"
        assert item_in_allergen_class(ITEMS["cream-of-tartar"], "dairy") == "non_member"
        assert item_in_allergen_class(ITEMS["water-chestnut"], "tree_nut") == "non_member"
        assert item_in_allergen_class(ITEMS["buckwheat"], "gluten") == "non_member"

    def test_missing_item_is_unknown(self):
        assert item_in_allergen_class(None, "dairy") == "unknown"

    def test_negative_assertions_recorded(self):
        # Regression guard: the traps carry explicit not_allergens documentation.
        assert "dairy" in ITEMS["coconut-milk"].not_allergens
        assert "gluten" in ITEMS["buckwheat"].not_allergens


class TestHardFails:
    def test_dairy_allergy_meets_cream_no_handling(self):
        recipe = make_recipe(
            "r1", ingredients=[ing("heavy-cream", "1 cup heavy cream", 1, "cup", 2)]
        )
        violations = backstop(recipe, entry_for("r1"))
        assert len(violations) == 1
        assert violations[0].code == "allergy_hard_fail"
        assert violations[0].severity == "error"

    def test_coconut_milk_no_false_positive(self):
        recipe = make_recipe(
            "r2", ingredients=[ing("coconut-milk", "1 can coconut milk", 1, "can")]
        )
        assert backstop(recipe, entry_for("r2")) == []

    def test_unmatched_ingredient_fails_closed_for_allergy(self):
        recipe = make_recipe("r3", ingredients=[ing(None, "1 jar mystery sauce")])
        violations = backstop(recipe, entry_for("r3"))
        assert any(v.severity == "error" for v in violations)

    def test_unmatched_ingredient_warns_for_intolerance(self):
        household = make_household(
            restrictions=[
                {"person_id": "p2", "allergen_class": "dairy", "severity": "intolerance"}
            ]
        )
        recipe = make_recipe("r4", ingredients=[ing(None, "1 jar mystery sauce")])
        violations = backstop(recipe, entry_for("r4"), household)
        assert violations and all(v.severity == "warning" for v in violations)

    def test_optional_conflicting_ingredient_ignored(self):
        recipe = make_recipe(
            "r5",
            ingredients=[ing("parmesan", "parmesan to serve", 1, "oz", is_optional=True)],
        )
        assert backstop(recipe, entry_for("r5")) == []


class TestHandlingVerification:
    CREAM = make_recipe(
        "rc", ingredients=[ing("heavy-cream", "1 cup heavy cream", 1, "cup", 3)]
    )

    def test_valid_substitute_accepted(self):
        entry = entry_for(
            "rc",
            [PersonHandling(person_id="p2", handling="substitute",
                            substitute_item_id="oat-milk", substitute_note="1:1")],
        )
        assert backstop(self.CREAM, entry) == []

    def test_conflicting_substitute_rejected(self):
        entry = entry_for(
            "rc",
            [PersonHandling(person_id="p2", handling="substitute", substitute_item_id="milk")],
        )
        v = backstop(self.CREAM, entry)[0]
        assert v.code == "invalid_substitute" and v.severity == "error"

    def test_unknown_substitute_rejected(self):
        entry = entry_for(
            "rc",
            [PersonHandling(person_id="p2", handling="substitute", substitute_item_id="nope")],
        )
        assert backstop(self.CREAM, entry)[0].code == "invalid_substitute"

    def test_split_after_step_one_accepted(self):
        entry = entry_for("rc", [PersonHandling(person_id="p2", handling="split")])
        assert backstop(self.CREAM, entry) == []

    def test_split_at_step_one_rejected(self):
        recipe = make_recipe("rs", ingredients=[ing("milk", "2 cups milk", 2, "cup", 1)])
        entry = entry_for("rs", [PersonHandling(person_id="p2", handling="split")])
        v = backstop(recipe, entry)[0]
        assert v.code == "split_not_feasible" and v.severity == "error"

    def test_split_with_unknown_step_rejected(self):
        recipe = make_recipe("ru", ingredients=[ing("milk", "2 cups milk", 2, "cup", None)])
        entry = entry_for("ru", [PersonHandling(person_id="p2", handling="split")])
        assert backstop(recipe, entry)[0].code == "split_not_feasible"

    def test_skip_accepted(self):
        entry = entry_for("rc", [PersonHandling(person_id="p2", handling="skip")])
        assert backstop(self.CREAM, entry) == []

    def test_preference_conflict_is_warning(self):
        household = make_household(
            restrictions=[
                {"person_id": "p1", "canonical_item_id": "shrimp", "severity": "preference"}
            ]
        )
        recipe = make_recipe("rp", ingredients=[ing("shrimp", "1 lb shrimp", 1, "lb")])
        violations = backstop(recipe, entry_for("rp"), household)
        assert len(violations) == 1 and violations[0].severity == "warning"

    def test_non_dinner_people_skipped(self):
        household = make_household(
            people=[{"id": "p2", "name": "Kid", "is_child": True, "eats_planned_dinners": False}],
            restrictions=[{"person_id": "p2", "allergen_class": "dairy", "severity": "allergy"}],
        )
        recipe = make_recipe("rk", ingredients=[ing("milk", "milk", 1, "cup", 1)])
        assert backstop(recipe, entry_for("rk"), household) == []


def test_split_feasible_no_conflicts():
    assert split_feasible(make_recipe("x"), []) is True
