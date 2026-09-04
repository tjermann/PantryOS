"""Grocery pipeline — port of packages/engine/src/grocery/pipeline.ts.

 1. Aggregate the same ingredient across recipes into one line.
 2. Subtract confirmed pantry stock.
 3. Add standing order lines (kids' meals, restocks).
 4. Group by store section.
 5. Report budget status if enabled.
"""

from __future__ import annotations

import re

from dataclasses import dataclass, field
from typing import Literal, Mapping

from ..schemas.domain import (
    CanonicalItem,
    PantryItem,
    Recipe,
    StandingOrderLine,
    StoreSection,
)
from .units import convert, dimension_of, normalize_unit

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
    # Staple items assumed on hand and therefore not purchased this week.
    assumed_on_hand: list[str] = field(default_factory=list)
    # Items the household removed during review ("we have enough").
    removed_by_household: list[str] = field(default_factory=list)


# Lines that appear among ingredients but are not things you buy: tap water, and
# the "For the sauce:" headers many sites emit as ingredient rows.
_NOT_PURCHASABLE = re.compile(
    r"^(?:\s*(?:cold|warm|hot|ice|lukewarm|filtered|boiling)?\s*water\s*)$",
    re.IGNORECASE,
)


def is_purchasable(raw: str) -> bool:
    from .parse import parse_qty_unit

    text = re.sub(r"\([^)]*\)", " ", raw or "").strip()
    if not text or text.endswith(":"):
        return False  # section header, e.g. "To garnish:"
    _, _, name = parse_qty_unit(text)
    name = (name or text).strip(" .,:;")
    if not name or not any(ch.isalpha() for ch in name):
        return False
    return not _NOT_PURCHASABLE.match(name)


def _is_staple(name: str, staples: list[str]) -> bool:
    import re

    lowered = name.lower()
    return any(re.search(rf"\b{re.escape(s)}\b", lowered) for s in staples)


def build_grocery_list(
    recipes: list[tuple[Recipe, int]],
    pantry: list[PantryItem],
    standing: list[StandingOrderLine],
    items: Mapping[str, CanonicalItem],
    budget_enabled: bool,
    budget_cents: int | None,
    substitutions: Mapping[str, str] | None = None,
    staples: list[str] | None = None,
    excluded: list[str] | None = None,
) -> GroceryListResult:
    lines: dict[str, GroceryLine] = {}
    unmatched: list[GroceryLine] = []
    substitutions = substitutions or {}
    staples = staples or []
    excluded_set = {e.strip().lower() for e in (excluded or [])}

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
            if not is_purchasable(ing.raw):
                continue
            # A known item with no stated amount ("cilantro, for garnish") is
            # still that item: it belongs in its own aisle and merges with the
            # other mentions, rather than becoming a second raw row.
            if ing.canonical_item_id is None:
                # Unmatched to the ontology: still aggregate by normalized name
                # so '2 lemons' and '1 lemon' become one line of 3.
                from .parse import aggregation_key, compatible_units, parse_qty_unit

                qty, unit, name = (ing.qty, ing.unit, ing.raw)
                if qty is None:
                    qty, unit, name = parse_qty_unit(ing.raw)
                key = f"~{aggregation_key(name)}"
                existing = lines.get(key)
                scaled = qty * scale if qty is not None else None
                if existing is not None:
                    if (existing.qty is not None and scaled is not None
                            and compatible_units(existing.unit, unit)):
                        converted = convert(scaled, unit or "each", existing.unit or "each")
                        if converted is not None:
                            existing.qty += converted
                            existing.source_recipe_ids.append(recipe.id)
                            continue
                    # Same item, incompatible units — keep the second verbatim.
                    unmatched.append(
                        GroceryLine(
                            canonical_item_id=None, display_name=ing.raw,
                            qty=scaled, unit=unit, section="other",
                            origin="recipe", source_recipe_ids=[recipe.id],
                        )
                    )
                    continue
                lines[key] = GroceryLine(
                    canonical_item_id=None,
                    display_name=name if qty is not None else ing.raw,
                    qty=scaled, unit=unit, section="other",
                    origin="recipe", source_recipe_ids=[recipe.id],
                )
                continue
            item = items.get(ing.canonical_item_id)
            unit = normalize_unit(ing.unit)
            qty = ing.qty * scale if ing.qty is not None else None
            # Key by (item, dimension) so '2 tbsp dill' and '1 tbsp dill' merge
            # instead of the second spilling into a duplicate row.
            key = f"{ing.canonical_item_id}|{dimension_of(unit)}"
            existing = lines.get(key)
            if (existing is not None and existing.qty is not None
                    and existing.unit is not None and qty is not None):
                converted = convert(qty, unit, existing.unit)
                if converted is not None:
                    existing.qty += converted
                    existing.source_recipe_ids.append(recipe.id)
                    continue
            if existing is None:
                lines[key] = GroceryLine(
                    canonical_item_id=ing.canonical_item_id,
                    display_name=item.name if item else ing.raw,
                    qty=qty,
                    unit=unit,
                    section=item.store_section if item else "other",
                    origin="recipe",
                    source_recipe_ids=[recipe.id],
                    est_price_cents=item.typical_price_cents if item else None,
                )
            elif qty is None:
                existing.source_recipe_ids.append(recipe.id)  # nothing to add
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

    # 1b. Herbs are bought by the bunch, however recipes measure them: collapse
    # every measure of one herb into a single shopping line.
    # Explicit bunch counts are respected ('1 bunch' + '1 bunch' = 2); loose
    # measures (sprigs, tbsp, cups) fold into the bunches you're already buying,
    # with a floor of one.
    import math

    herb_lines: dict[str, GroceryLine] = {}
    herb_bunches: dict[str, float] = {}
    for key in list(lines):
        line = lines[key]
        item = items.get(line.canonical_item_id or "")
        if item is None or item.perishability not in ("tender_herb", "hardy_herb"):
            continue
        bunches = line.qty or 0.0 if normalize_unit(line.unit) == "bunch" else 0.0
        herb_bunches[item.id] = herb_bunches.get(item.id, 0.0) + bunches
        primary = herb_lines.get(item.id)
        if primary is None:
            herb_lines[item.id] = line
        else:
            primary.source_recipe_ids.extend(line.source_recipe_ids)
            lines.pop(key)
    for item_id, line in herb_lines.items():
        line.unit = "bunch"
        line.qty = float(max(1, math.ceil(herb_bunches.get(item_id, 0.0) - 0.01)))

    # 2. Subtract confirmed pantry stock.
    for pantry_item in pantry:
        if pantry_item.confidence != "confirmed":
            continue
        # Lines are keyed by (item, dimension), so match on the item id itself.
        for line in lines.values():
            if line.canonical_item_id != pantry_item.canonical_item_id:
                continue
            if line.qty is None or line.unit is None:
                continue
            on_hand = convert(pantry_item.qty, pantry_item.unit, line.unit)
            if on_hand is None:
                continue
            line.qty = max(0.0, line.qty - on_hand)
            line.pantry_adjusted = True
            break

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

    candidate_lines = [
        *(l for l in lines.values() if l.qty is None or l.qty > 0),
        *unmatched,
        *standing_lines,
    ]
    # Staples are assumed on hand: dropped from every purchase EXCEPT explicit
    # restock lines ("we ran out"), which always buy.
    assumed: list[str] = []
    removed: list[str] = []
    all_lines = []
    for line in candidate_lines:
        if line.display_name.strip().lower() in excluded_set:
            if line.display_name not in removed:
                removed.append(line.display_name)
        elif line.origin != "restock" and _is_staple(line.display_name, staples):
            if line.display_name not in assumed:
                assumed.append(line.display_name)
        else:
            all_lines.append(line)

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
        assumed_on_hand=assumed,
        removed_by_household=removed,
    )
