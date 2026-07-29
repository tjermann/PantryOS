"""Repair-loop tests for llm/planner.py with fake clients — no live API."""

from datetime import date
from types import SimpleNamespace

from fixtures_helpers import ITEMS, ing, make_household, make_recipe
from mealplanner.llm.planner import propose_plan
from mealplanner.schemas.plan import PlanEntryProposal, PlanProposal, PersonHandling

SAFE = make_recipe(
    "safe",
    ingredients=[ing("chicken-thigh", "1 lb chicken", 1, "lb")],
)
DAIRY = make_recipe(
    "dairy-dish",
    protein="pork",
    cuisine="french",
    ingredients=[ing("heavy-cream", "1 cup cream", 1, "cup", 3)],
)
CANDIDATES = [SAFE, DAIRY]
HOUSEHOLD = make_household(
    restrictions=[{"person_id": "p2", "allergen_class": "dairy", "severity": "allergy"}]
)
WEEK = [date(2026, 8, 3), date(2026, 8, 4)]


def entry(recipe_id, handling=None):
    return PlanEntryProposal(
        recipe_id=recipe_id,
        date="2026-08-03",
        servings=4,
        rationale="test",
        person_handling=handling or [],
    )


class FakeClient:
    """Yields queued PlanProposal objects on successive parse() calls."""

    def __init__(self, proposals):
        self._proposals = list(proposals)
        self.calls = []
        self.messages = SimpleNamespace(parse=self._parse)

    def _parse(self, **kwargs):
        self.calls.append(kwargs)
        proposal = self._proposals.pop(0)
        return SimpleNamespace(
            parsed_output=proposal,
            stop_reason="end_turn",
            usage=SimpleNamespace(
                input_tokens=1000, output_tokens=200, cache_read_input_tokens=500
            ),
        )


def run(client, **overrides):
    kwargs = dict(
        model="claude-opus-5",
        candidates=CANDIDATES,
        states={},
        items=ITEMS,
        household=HOUSEHOLD,
        week_dates=WEEK,
    )
    kwargs.update(overrides)
    return propose_plan(client, **kwargs)


def test_valid_proposal_accepted_first_try():
    client = FakeClient([PlanProposal(entries=[entry("safe")])])
    result = run(client)
    assert result.validation.ok is True
    assert result.dropped_recipe_ids == []
    assert result.usage.calls == 1
    assert result.prompt_version == "v1"
    assert result.model == "claude-opus-5"


def test_repair_loop_fixes_allergy_violation():
    bad = PlanProposal(entries=[entry("dairy-dish")])  # unhandled dairy vs allergy
    fixed = PlanProposal(
        entries=[
            entry(
                "dairy-dish",
                [PersonHandling(person_id="p2", handling="substitute",
                                substitute_item_id="oat-milk")],
            )
        ]
    )
    client = FakeClient([bad, fixed])
    result = run(client)
    assert result.validation.ok is True
    assert result.usage.calls == 2
    # The repair turn carried machine-readable violations back to the model.
    repair_messages = client.calls[1]["messages"]
    assert any("allergy_hard_fail" in str(m.get("content", "")) for m in repair_messages)


def test_unrepairable_entries_dropped_deterministically():
    bad = PlanProposal(entries=[entry("safe"), entry("dairy-dish")])
    client = FakeClient([bad, bad, bad])  # never repairs
    result = run(client, max_repairs=2)
    assert result.usage.calls == 3
    assert result.dropped_recipe_ids == ["dairy-dish"]
    assert [e.recipe_id for e in result.proposal.entries] == ["safe"]
    assert result.validation.ok is True  # the delivered plan is backstop-clean


def test_system_prompt_is_cacheable_prefix():
    client = FakeClient([PlanProposal(entries=[entry("safe")])])
    run(client)
    system = client.calls[0]["system"]
    assert system[0]["cache_control"] == {"type": "ephemeral"}
    # Frozen prefix: no user data leaks into the system prompt.
    assert "Avery" not in system[0]["text"]
