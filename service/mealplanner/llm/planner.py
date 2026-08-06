"""The weekly planning call: candidate context → Claude structured output →
deterministic validation → bounded repair loop → deterministic drop.

The plan a user ever sees is always backstop-clean: if Claude cannot repair an
allergy-level violation in `max_repairs` attempts, the offending entries are
dropped in code. The client is duck-typed so tests inject fakes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping, Protocol

from ..planning.long_lead import detect_long_lead
from ..planning.perishables import perishable_usage
from ..planning.validate import ValidationResult, validate_plan
from ..planning.variety import VarietyRules
from ..prompts.v1.planning import PLANNING_SYSTEM_PROMPT, PROMPT_VERSION, repair_prompt
from ..schemas.domain import CanonicalItem, Household, HouseholdRecipeState, Recipe
from ..schemas.plan import PlanProposal


class SupportsParse(Protocol):
    """The slice of anthropic.Anthropic the planner uses (duck-typed for tests)."""

    class _Messages(Protocol):  # pragma: no cover - typing only
        def parse(self, **kwargs: Any) -> Any: ...

    @property
    def messages(self) -> Any: ...


@dataclass(frozen=True)
class LlmUsage:
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int
    calls: int


@dataclass(frozen=True)
class PlanRunResult:
    proposal: PlanProposal
    validation: ValidationResult
    dropped_recipe_ids: list[str]
    usage: LlmUsage
    prompt_version: str
    model: str


def build_candidate_context(
    candidates: list[Recipe],
    states: Mapping[str, HouseholdRecipeState],
    items: Mapping[str, CanonicalItem],
    household: Household,
    week_dates: list[date],
    learnings: str = "",
) -> str:
    """Compact JSON context for the user turn. The system prompt is the frozen
    cacheable prefix; everything volatile goes here."""
    perishables = {
        u.canonical_item_id: list(u.recipe_ids)
        for u in perishable_usage(candidates, items)
    }
    candidate_rows = []
    for r in candidates:
        state = states.get(r.id)
        candidate_rows.append(
            {
                "recipe_id": r.id,
                "title": r.title,
                "protein": r.protein,
                "cuisine": r.cuisine,
                "effort": r.effort,
                "serves": r.serves,
                "published_time_min": r.published_time_min,
                "real_time_min": state.real_time_min if state else None,
                "last_made_at": state.last_made_at if state else None,
                "lifecycle": state.lifecycle if state else "to_try",
                "avg_rating": (
                    round(sum(state.ratings) / len(state.ratings), 1)
                    if state and state.ratings
                    else None
                ),
                "long_lead": [
                    {"step": f.step_order, "lead_min": f.lead_min}
                    for f in detect_long_lead(r)
                ],
                "ingredient_items": [
                    {
                        "item": ing.canonical_item_id,
                        "raw": ing.raw,
                        "added_at_step": ing.added_at_step,
                    }
                    for ing in r.ingredients
                ],
            }
        )
    context = {
        "household": {
            "people": [p.model_dump() for p in household.people],
            "restrictions": [r.model_dump() for r in household.restrictions],
            "dinners_per_week": household.dinners_per_week,
            "budget_cents_weekly": (
                household.budget_cents_weekly if household.budget_enabled else None
            ),
        },
        "week_dates": [d.isoformat() for d in week_dates],
        "candidates": candidate_rows,
        "perishable_overlap_sets": perishables,
        "learnings": learnings.strip() or None,
    }
    return json.dumps(context, sort_keys=True)


def propose_plan(
    client: Any,
    *,
    model: str,
    candidates: list[Recipe],
    states: Mapping[str, HouseholdRecipeState],
    items: Mapping[str, CanonicalItem],
    household: Household,
    week_dates: list[date],
    learnings: str = "",
    variety_rules: VarietyRules | None = None,
    max_repairs: int = 2,
    revision_context: str | None = None,
) -> PlanRunResult:
    candidate_map = {r.id: r for r in candidates}
    context = build_candidate_context(
        candidates, states, items, household, week_dates, learnings
    )
    if revision_context:
        context += (
            "\n\n[REVISION] You previously proposed the plan below and the household "
            "has since given feedback (see the newest learnings entries and any "
            "rating/lifecycle changes). Revise the proposal: keep dishes the feedback "
            "doesn't object to in place, and change what it targets.\nPrevious "
            f"proposal: {revision_context}"
        )
    system = [
        {
            "type": "text",
            "text": PLANNING_SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }
    ]
    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": f"Plan this week. Context:\n{context}",
        }
    ]

    usage_in = usage_out = usage_cached = calls = 0
    proposal: PlanProposal | None = None
    validation: ValidationResult | None = None

    for attempt in range(max_repairs + 1):
        response = client.messages.parse(
            model=model,
            max_tokens=16000,
            system=system,
            messages=messages,
            output_format=PlanProposal,
        )
        calls += 1
        usage = getattr(response, "usage", None)
        if usage is not None:
            usage_in += getattr(usage, "input_tokens", 0) or 0
            usage_out += getattr(usage, "output_tokens", 0) or 0
            usage_cached += getattr(usage, "cache_read_input_tokens", 0) or 0
        if getattr(response, "stop_reason", None) == "refusal":
            raise RuntimeError("Planning request was refused by the model")
        proposal = response.parsed_output
        if proposal is None:
            raise RuntimeError("Planning call returned no structured output")

        kwargs: dict[str, Any] = {}
        if variety_rules is not None:
            kwargs["variety_rules"] = variety_rules
        validation = validate_plan(
            proposal, candidate_map, states, items, household, **kwargs
        )
        if validation.ok or attempt == max_repairs:
            break
        # Repair turn: echo the assistant output, append machine-readable errors.
        messages.append(
            {"role": "assistant", "content": proposal.model_dump_json()}
        )
        messages.append(
            {
                "role": "user",
                "content": repair_prompt(
                    json.dumps([v.model_dump() for v in validation.errors])
                ),
            }
        )

    assert proposal is not None and validation is not None

    # Deterministic last resort: drop entries still carrying errors so the
    # persisted/emailed plan is always backstop-clean.
    dropped: list[str] = []
    if not validation.ok:
        bad_indices = {v.entry_index for v in validation.errors if v.entry_index is not None}
        dropped = [
            e.recipe_id for i, e in enumerate(proposal.entries) if i in bad_indices
        ]
        proposal = proposal.model_copy(
            update={
                "entries": [
                    e for i, e in enumerate(proposal.entries) if i not in bad_indices
                ]
            }
        )
        validation = validate_plan(
            proposal, candidate_map, states, items, household,
            **({"variety_rules": variety_rules} if variety_rules is not None else {}),
        )

    return PlanRunResult(
        proposal=proposal,
        validation=validation,
        dropped_recipe_ids=dropped,
        usage=LlmUsage(usage_in, usage_out, usage_cached, calls),
        prompt_version=PROMPT_VERSION,
        model=model,
    )
