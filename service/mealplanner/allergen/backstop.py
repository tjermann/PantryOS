"""Deterministic allergen backstop — port of packages/engine/src/allergen/backstop.ts.

Runs over every proposed plan entry AFTER the LLM, regardless of what the LLM
claimed about safety. Policy:
 - severity "allergy": any conflicting ingredient is an ERROR unless the
   proposed handling provably resolves it (valid substitute, feasible split
   point, or skip). Unknown ingredients (unmatched to the ontology) are ALSO
   errors for allergy severity — fail closed.
 - severity "intolerance": conflicts must be handled, but unknown ingredients
   produce warnings rather than errors.
 - severity "preference": conflicts produce warnings only.
"""

from __future__ import annotations

from typing import Mapping

from ..schemas.domain import (
    CanonicalItem,
    DietaryRestriction,
    Person,
    Recipe,
)
from ..schemas.plan import PlanEntryProposal, Violation
from .ontology import item_in_allergen_class, lookup_item


def _ingredient_conflicts(
    recipe: Recipe,
    restriction: DietaryRestriction,
    items: Mapping[str, CanonicalItem],
) -> tuple[list[int], list[int]]:
    conflicting: list[int] = []
    unknown: list[int] = []
    for i, ing in enumerate(recipe.ingredients):
        if ing.is_optional:
            continue
        if restriction.canonical_item_id:
            if ing.canonical_item_id == restriction.canonical_item_id:
                conflicting.append(i)
            elif ing.canonical_item_id is None:
                unknown.append(i)
            continue
        if restriction.allergen_class:
            item = lookup_item(items, ing.canonical_item_id)
            membership = item_in_allergen_class(item, restriction.allergen_class)
            if membership == "member":
                conflicting.append(i)
            elif membership == "unknown":
                unknown.append(i)
    return conflicting, unknown


def split_feasible(recipe: Recipe, conflicting_idx: list[int]) -> bool:
    """A split is feasible only if EVERY conflicting ingredient enters the dish
    at a known step > 1 — i.e. there is a real moment to pull a clean portion."""
    if not conflicting_idx:
        return True
    return all(
        (ing := recipe.ingredients[i]).added_at_step is not None
        and ing.added_at_step > 1
        for i in conflicting_idx
    )


def run_allergen_backstop(
    *,
    entry: PlanEntryProposal,
    entry_index: int,
    recipe: Recipe,
    people: list[Person],
    restrictions: list[DietaryRestriction],
    items: Mapping[str, CanonicalItem],
) -> list[Violation]:
    violations: list[Violation] = []

    for person in people:
        if not person.eats_planned_dinners:
            continue
        for restriction in (r for r in restrictions if r.person_id == person.id):
            conflicting, unknown = _ingredient_conflicts(recipe, restriction, items)
            handling = next(
                (h for h in entry.person_handling if h.person_id == person.id), None
            )
            is_allergy = restriction.severity == "allergy"

            # Unknown ingredients: fail closed for allergies, warn otherwise.
            if unknown and restriction.allergen_class:
                unknown_names = "; ".join(
                    recipe.ingredients[i].raw for i in unknown
                )
                violations.append(
                    Violation(
                        code="allergy_hard_fail",
                        severity="error" if is_allergy else "warning",
                        entry_index=entry_index,
                        message=(
                            f"{recipe.title}: {len(unknown)} ingredient(s) not matched to "
                            f"the ontology ({unknown_names}) — cannot verify against "
                            f"{person.name}'s {restriction.severity} ({restriction.allergen_class})."
                        ),
                    )
                )

            if not conflicting:
                continue

            conflict_names = "; ".join(recipe.ingredients[i].raw for i in conflicting)
            base_msg = (
                f"{recipe.title}: contains {conflict_names}, conflicting with "
                f"{person.name}'s {restriction.severity}"
            )

            if restriction.severity == "preference":
                if handling is None or handling.handling == "clear":
                    violations.append(
                        Violation(
                            code="allergy_hard_fail",
                            severity="warning",
                            entry_index=entry_index,
                            message=f"{base_msg} (preference — flag to user).",
                        )
                    )
                continue

            # allergy / intolerance: handling must exist and actually resolve it.
            err_severity = "error" if is_allergy else "warning"
            if handling is None or handling.handling == "clear":
                violations.append(
                    Violation(
                        code="allergy_hard_fail",
                        severity=err_severity,
                        entry_index=entry_index,
                        message=f'{base_msg}, but handling is missing or "clear".',
                    )
                )
                continue
            if handling.handling == "substitute":
                sub = (
                    items.get(handling.substitute_item_id)
                    if handling.substitute_item_id
                    else None
                )
                if restriction.allergen_class:
                    sub_ok = (
                        sub is not None
                        and item_in_allergen_class(sub, restriction.allergen_class)
                        == "non_member"
                    )
                else:
                    sub_ok = sub is not None and sub.id != restriction.canonical_item_id
                if not sub_ok:
                    violations.append(
                        Violation(
                            code="invalid_substitute",
                            severity=err_severity,
                            entry_index=entry_index,
                            message=(
                                f"{base_msg}; proposed substitute is missing, unknown, "
                                f"or itself conflicting."
                            ),
                        )
                    )
                continue
            if handling.handling == "split":
                if not split_feasible(recipe, conflicting):
                    violations.append(
                        Violation(
                            code="split_not_feasible",
                            severity=err_severity,
                            entry_index=entry_index,
                            message=(
                                f"{base_msg}; split proposed but a conflicting ingredient "
                                f"enters at step 1 or an unknown step — no clean pull point."
                            ),
                        )
                    )
                continue
            # handling == "skip" resolves the conflict for that person.

    return violations
