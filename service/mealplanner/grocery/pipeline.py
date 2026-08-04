"""Grocery pipeline — port of packages/engine/src/grocery/pipeline.ts.

 1. Aggregate the same ingredient across recipes into one line.
 2. Subtract confirmed pantry stock.
 3. Add standing order lines (kids' meals, restocks).
 4. Group by store section.
 5. Report budget status if enabled.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping

from ..schemas.domain import (
    CanonicalItem,
    PantryItem,
    Recipe,
    StandingOrderLine,
    StoreSection,
)
from .units import convert, normalize_unit

Origin = Literal["recipe", "standing", "restock"]


@dataclass
class GroceryLine:
    canonical_item_id: str | None
    display_name: str
    qty: float | None
    unit: str | None
    section: StoreSection
    origin: Origin
    source_recipe_ids: list[str] = field(default_factory=list)
    est_price_cents: int | None = None
    pantry_adjusted: bool = False
    checked: bool = False


@dataclass(frozen=True)
class BudgetStatus:
    enabled: bool
    budget_cents: int | None
    under_budget_cents: int | None


@dataclass(frozen=True)
class GroceryListResult:
    sections: dict[StoreSection, list[GroceryLine]]
    lines: list[GroceryLine]
    est_total_cents: int | None
    budget: BudgetStatus


def build_grocery_list(
    recipes: list[tuple[Recipe, int]],
    pantry: list[PantryItem],
    standing: list[StandingOrderLine],
    items: Mapping[str, CanonicalItem],
    budget_enabled: bool,
    budget_cents: int | None,
    substitutions: Mapping[str, str] | None = None,
) -> GroceryListResult:
    lines: dict[str, GroceryLine] = {}
    unmatched: list[GroceryLine] = []
    substitutions = substitutions or {}

    # 1. Aggregate matched ingredients.
    for recipe, servings in recipes:
        scale = servings / recipe.serves
        for raw_ing in recipe.ingredients:
            ing = raw_ing
            if ing.canonical_item_id and ing.canonical_item_id in substitutions:
                sub_id = substitutions[ing.canonical_item_id]
                sub_item = items.get(sub_id)
                ing = ing.model_copy(update={
                    "canonical_item_id": sub_id,
                    "raw": f"{sub_item.name if sub_item else sub_id} (subbed for {ing.raw})",
                })
            if ing.is_optional:
                continue
            if ing.canonical_item_id is None or ing.qty is None:
                # Unmatched or unquantified: keep verbatim, never silently dropped.
                unmatched.append(
                    GroceryLine(
                        canonical_item_id=ing.canonical_item_id,
                        display_name=ing.raw,
                        qty=ing.qty * scale if ing.qty is not None else None,
                        unit=ing.unit,
                        section="other",
                        origin="recipe",
                        source_recipe_ids=[recipe.id],
                    )
                )
                continue
            item = items.get(ing.canonical_item_id)
            unit = normalize_unit(ing.unit)
            qty = ing.qty * scale
            existing = lines.get(ing.canonical_item_id)
            if existing is not None and existing.qty is not None and existing.unit is not None:
                converted = convert(qty, unit, existing.unit)
                if converted is not None:
                    existing.qty += converted
                    existing.source_recipe_ids.append(recipe.id)
                    continue
            if existing is None:
                lines[ing.canonical_item_id] = GroceryLine(
                    canonical_item_id=ing.canonical_item_id,
                    display_name=item.name if item else ing.raw,
                    qty=qty,
                    unit=unit,
                    section=item.store_section if item else "other",
                    origin="recipe",
                    source_recipe_ids=[recipe.id],
                    est_price_cents=item.typical_price_cents if item else None,
                )
            else:
                # Same item, incompatible units — separate verbatim line.
                unmatched.append(
                    GroceryLine(
                        canonical_item_id=ing.canonical_item_id,
                        display_name=item.name if item else ing.raw,
                        qty=qty,
                        unit=unit,
                        section=item.store_section if item else "other",
                        origin="recipe",
                        source_recipe_ids=[recipe.id],
                    )
                )

    # 2. Subtract confirmed pantry stock.
    for pantry_item in pantry:
        if pantry_item.confidence != "confirmed":
            continue
        line = lines.get(pantry_item.canonical_item_id)
        if line is None or line.qty is None or line.unit is None:
            continue
        on_hand = convert(pantry_item.qty, pantry_item.unit, line.unit)
        if on_hand is None:
            continue
        line.qty = max(0.0, line.qty - on_hand)
        line.pantry_adjusted = True

    # 3. Standing lines.
    standing_lines: list[GroceryLine] = []
    for s in standing:
        item = items.get(s.canonical_item_id) if s.canonical_item_id else None
        standing_lines.append(
            GroceryLine(
                canonical_item_id=s.canonical_item_id,
                display_name=item.name if item else s.raw,
                qty=s.qty,
                unit=s.unit,
                section=item.store_section if item else "other",
                origin="restock" if s.reason == "restock" else "standing",
                est_price_cents=item.typical_price_cents if item else None,
            )
        )

    all_lines = [
        *(l for l in lines.values() if l.qty is None or l.qty > 0),
        *unmatched,
        *standing_lines,
    ]

    # 4. Group by section.
    sections: dict[StoreSection, list[GroceryLine]] = {}
    for line in all_lines:
        sections.setdefault(line.section, []).append(line)

    # 5. Budget. Total is None if ANY line lacks a price — a partial sum
    # presented as a total would mislead.
    priced = [l for l in all_lines if l.est_price_cents is not None]
    est_total_cents = (
        sum(l.est_price_cents or 0 for l in priced)
        if all_lines and len(priced) == len(all_lines)
        else None
    )
    under_budget_cents = (
        budget_cents - est_total_cents
        if budget_enabled and budget_cents is not None and est_total_cents is not None
        else None
    )

    return GroceryListResult(
        sections=sections,
        lines=all_lines,
        est_total_cents=est_total_cents,
        budget=BudgetStatus(
            enabled=budget_enabled,
            budget_cents=budget_cents,
            under_budget_cents=under_budget_cents,
        ),
    )
