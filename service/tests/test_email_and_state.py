"""Email rendering golden checks + state-store round trips."""

from datetime import date
from pathlib import Path

from fixtures_helpers import ITEMS, ing, make_household, make_recipe
from mealplanner.emailer.sender import SmtpSettings, build_message
from mealplanner.emailer.weekly import build_weekly_email_context, render_weekly_email
from mealplanner.grocery.pipeline import build_grocery_list
from mealplanner.llm.planner import LlmUsage, PlanRunResult
from mealplanner.planning.validate import ValidationResult
from mealplanner.schemas.domain import RecipeStep
from mealplanner.schemas.plan import PlanEntryProposal, PlanProposal, PersonHandling
from mealplanner.state.store import StateStore

BRINED = make_recipe(
    "brined-pork",
    title="Brined Pork Chops",
    protein="pork",
    published_time_min=50,
    ingredients=[ing("pork-chop", "4 pork chops", 4, "each") if "pork-chop" in ITEMS
                 else ing("chicken-thigh", "4 chops", 4, "each"),
                 ing("cilantro", "1 bunch cilantro", 1, "bunch")],
    steps=[
        RecipeStep(order=1, text="Brine 4 hours.", duration_min=240, unattended=True),
        RecipeStep(order=2, text="Sear.", duration_min=15, unattended=False),
    ],
)
CURRY = make_recipe(
    "coconut-curry",
    title="Coconut Chicken Curry",
    ingredients=[
        ing("chicken-thigh", "1 lb chicken thighs", 1, "lb"),
        ing("coconut-milk", "1 can coconut milk", 1, "can", 2),
        ing("cilantro", "1 bunch cilantro", 1, "bunch"),
    ],
)
RECIPES = {r.id: r for r in (BRINED, CURRY)}
HOUSEHOLD = make_household()


def make_plan_result() -> PlanRunResult:
    proposal = PlanProposal(
        entries=[
            PlanEntryProposal(recipe_id="brined-pork", date="2026-08-03", servings=4,
                              rationale="Sunday has time for the brine."),
            PlanEntryProposal(
                recipe_id="coconut-curry", date="2026-08-04", servings=4,
                rationale="Finishes the cilantro.",
                person_handling=[PersonHandling(person_id="p2", handling="split")],
            ),
        ],
        perishable_pairings=[{"canonical_item_id": "cilantro",
                              "recipe_ids": ["brined-pork", "coconut-curry"]}],
    )
    return PlanRunResult(
        proposal=proposal,
        validation=ValidationResult(ok=True, errors=[], warnings=[]),
        dropped_recipe_ids=[],
        usage=LlmUsage(1000, 200, 500, 1),
        prompt_version="v1",
        model="claude-opus-5",
    )


def test_weekly_email_renders_both_parts():
    plan = make_plan_result()
    grocery = build_grocery_list(
        recipes=[(BRINED, 4), (CURRY, 4)],
        pantry=[], standing=[], items=ITEMS,
        budget_enabled=True, budget_cents=20000,
    )
    context = build_weekly_email_context(
        plan=plan, grocery=grocery, recipes=RECIPES, items=ITEMS,
        household=HOUSEHOLD, week_start=date(2026, 8, 3),
        carts=[{"store": "amazon-fresh", "summary": "12 added, 1 not found",
                "url": "https://www.amazon.com/cart", "not_found": ["saffron"],
                "action_needed": None}],
        feedback_url="http://box:8321/u/test?t=tok",
    )
    text, html = render_weekly_email(context)

    for body in (text, html):
        assert "Brined Pork Chops" in body
        assert "Coconut Chicken Curry" in body
        assert "4 hr of unattended lead time" in body       # long-lead flagged up top
        assert "pull their portion" in body                 # split reminder
        assert "Cilantro across" in body                    # perishable pairing
        assert "Review" in body and "amazon.com/cart" in body
        assert "never submitted automatically" in body
    assert "Estimated total" in text                        # fully priced → budget line


def test_mime_message_has_both_alternatives():
    settings = SmtpSettings(user="planner@example.com", password="x")
    msg = build_message(settings, ["a@example.com"], [], "Test", "text body", "<p>html</p>")
    parts = [p.get_content_type() for p in msg.walk()]
    assert "text/plain" in parts and "text/html" in parts


class TestStateStore:
    def test_rating_lifecycle_and_real_time(self, tmp_path: Path):
        store = StateStore(tmp_path)
        store.record_rating("dish", score=4, made_on=date(2026, 8, 3))
        state = store.record_rating("dish", score=5, real_time_min=65,
                                    note="double the sauce", made_on=date(2026, 8, 20))
        assert state.lifecycle == "keeper"          # two ratings >= 4
        assert state.real_time_min == 65
        assert state.times_made == 2
        assert state.last_made_at == "2026-08-20"
        assert "double the sauce" in (state.notes or "")

        bad = store.record_rating("dish", score=2)
        assert bad.lifecycle == "probation"         # any rating <= 2

        reloaded = StateStore(tmp_path).load_recipe_states()["dish"]
        assert reloaded.ratings == [4, 5, 2]

    def test_feedback_fingerprint_changes_with_feedback(self, tmp_path: Path):
        store = StateStore(tmp_path)
        before = store.feedback_fingerprint()
        assert store.feedback_fingerprint() == before  # stable when nothing changes
        store.append_learning("less spicy please")
        after_learning = store.feedback_fingerprint()
        assert after_learning != before
        store.record_rating("some-dish", score=5)
        assert store.feedback_fingerprint() != after_learning

    def test_plans_orders_learnings_roundtrip(self, tmp_path: Path):
        store = StateStore(tmp_path)
        store.save_plan("2026-W32", {"week": "2026-W32", "entries": []})
        store.save_order("2026-W32", {"week": "2026-W32", "carts": []})
        store.append_learning("Shrimp always need deveining despite the label")
        assert store.latest_plan()[0] == "2026-W32"
        assert store.load_orders()[0][0] == "2026-W32"
        assert "deveining" in store.load_learnings()
        store.add_restock("distilled white vinegar")
        assert store.load_restock()[0].raw == "distilled white vinegar"
