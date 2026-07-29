"""Plan validation orchestrator — port of packages/engine/src/planning/validate.ts.

Errors (allergy hard fails above all) mean the plan must not be emailed or
saved as-is: re-prompt with the violation list, and if the violation persists,
drop/replace the offending entry deterministically.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from ..allergen.backstop import run_allergen_backstop
from ..schemas.domain import CanonicalItem, Household, HouseholdRecipeState, Recipe
from ..schemas.plan import PlanProposal, Violation
from .perishables import orphaned_perishables
from .variety import DEFAULT_VARIETY_RULES, VarietyRules, validate_variety


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    errors: list[Violation]
    warnings: list[Violation]


def validate_plan(
    proposal: PlanProposal,
    candidates: Mapping[str, Recipe],
    states: Mapping[str, HouseholdRecipeState],
    items: Mapping[str, CanonicalItem],
    household: Household,
    variety_rules: VarietyRules = DEFAULT_VARIETY_RULES,
) -> ValidationResult:
    violations: list[Violation] = []

    for entry_index, entry in enumerate(proposal.entries):
        recipe = candidates.get(entry.recipe_id)
        if recipe is None:
            continue  # reported as unknown_recipe by validate_variety
        violations.extend(
            run_allergen_backstop(
                entry=entry,
                entry_index=entry_index,
                recipe=recipe,
                people=household.people,
                restrictions=household.restrictions,
                items=items,
            )
        )

    violations.extend(
        validate_variety(proposal.entries, candidates, states, variety_rules)
    )

    planned = [
        r for e in proposal.entries if (r := candidates.get(e.recipe_id)) is not None
    ]
    violations.extend(orphaned_perishables(planned, items))

    errors = [v for v in violations if v.severity == "error"]
    warnings = [v for v in violations if v.severity == "warning"]
    return ValidationResult(ok=not errors, errors=errors, warnings=warnings)
