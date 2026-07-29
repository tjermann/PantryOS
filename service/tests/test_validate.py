"""Port of packages/engine/test/validate.test.ts."""

from fixtures_helpers import ITEMS, ing, make_household, make_recipe, state_map
from mealplanner.planning.perishables import orphaned_perishables
from mealplanner.planning.validate import validate_plan
from mealplanner.schemas.plan import PlanEntryProposal, PlanProposal

SAFE = make_recipe(
    "safe",
    ingredients=[ing("chicken-thigh", "1 lb chicken", 1, "lb"), ing("cilantro", "cilantro", 1, "bunch")],
)
DAIRY_DISH = make_recipe(
    "dairy-dish",
    protein="pork",
    cuisine="french",
    ingredients=[ing("heavy-cream", "1 cup cream", 1, "cup", 1)],
)
CANDIDATES = {SAFE.id: SAFE, DAIRY_DISH.id: DAIRY_DISH}
HOUSEHOLD = make_household(
    restrictions=[{"person_id": "p2", "allergen_class": "dairy", "severity": "allergy"}]
)


def proposal(entries):
    return PlanProposal(entries=entries)


def test_unresolved_allergy_rejected():
    result = validate_plan(
        proposal([PlanEntryProposal(recipe_id="dairy-dish", date="2026-08-03",
                                    servings=4, rationale="")]),
        CANDIDATES,
        state_map([]),
        ITEMS,
        HOUSEHOLD,
    )
    assert result.ok is False
    assert any(v.code == "allergy_hard_fail" for v in result.errors)


def test_clean_plan_ok_with_warnings():
    result = validate_plan(
        proposal([PlanEntryProposal(recipe_id="safe", date="2026-08-03",
                                    servings=4, rationale="")]),
        CANDIDATES,
        state_map([]),
        ITEMS,
        HOUSEHOLD,
    )
    assert result.ok is True
    # cilantro used once → orphaned-perishable warning, not an error
    assert any(v.code == "orphaned_perishable" for v in result.warnings)


def test_shared_tender_herb_not_flagged():
    a = make_recipe("a", ingredients=[ing("cilantro", "cilantro", 1, "bunch")])
    b = make_recipe("b", ingredients=[ing("cilantro", "cilantro", 1, "bunch")])
    assert orphaned_perishables([a, b], ITEMS) == []


def test_hardy_herbs_never_flagged():
    a = make_recipe("a", ingredients=[ing("ginger", "ginger", 1, "each")])
    assert orphaned_perishables([a], ITEMS) == []
