"""Plan-proposal + violation models — port of packages/engine/src/schemas/plan.ts.

PlanProposal is the strict output schema for the Claude planning call.
Everything here is a PROPOSAL — deterministic validators run before anything
is emailed or saved.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .domain import Handling, StrictModel

ViolationCode = Literal[
    "allergy_hard_fail",
    "invalid_substitute",
    "split_not_feasible",
    "out_of_season",
    "missing_equipment",
    "lifecycle_cut",
    "back_to_back_similar",
    "protein_overload",
    "effort_stacking",
    "recent_repeat",
    "unknown_recipe",
    "orphaned_perishable",
    "over_budget",
]


class PersonHandling(StrictModel):
    person_id: str
    handling: Handling
    substitute_item_id: str | None = None  # required when handling == "substitute"
    substitute_note: str | None = None


class PlanEntryProposal(StrictModel):
    recipe_id: str
    date: str  # ISO date the dish is scheduled for
    servings: int = Field(gt=0)
    rationale: str
    person_handling: list[PersonHandling] = Field(default_factory=list)


class PerishablePairing(StrictModel):
    canonical_item_id: str
    recipe_ids: list[str] = Field(min_length=2)


class PlanProposal(StrictModel):
    entries: list[PlanEntryProposal]
    perishable_pairings: list[PerishablePairing] = Field(default_factory=list)
    treat_suggestions: list[str] = Field(default_factory=list)
    notes: str | None = None


class Violation(StrictModel):
    """Machine-readable validator output, fed back to Claude on repair loops."""

    code: ViolationCode
    severity: Literal["error", "warning"]
    entry_index: int | None = None
    message: str
