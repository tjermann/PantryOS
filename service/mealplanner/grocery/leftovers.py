"""Leftovers: what earlier orders left on hand, so it isn't bought twice.

A recipe needs a tablespoon of sriracha and the store sells a bottle; it needs
half an onion and the store sells onions. The rest stays in the kitchen, and the
next recipe that calls for it should use that instead of adding another bottle.

The ledger is deliberately conservative. Every item has a shelf life, after
which its leftover is forgotten; units that can't be compared are never guessed
across; and anything the household says has run out is removed at once.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Mapping

from ..schemas.domain import CanonicalItem
from .units import convert, normalize_unit

EPSILON = 1e-6


@dataclass(frozen=True)
class Keeps:
    """How an item is sold and how long an opened one lasts."""

    unit: str          # unit the leftover is tracked in
    package: float     # how much of `unit` one purchase holds
    shelf_days: int


_SPICE = Keeps("tsp", 24, 365)
_SPICE_IDS = {
    "garlic-powder", "onion-powder", "turmeric", "cayenne", "ginger-ground",
    "garam-masala", "italian-seasoning", "taco-seasoning", "nutmeg",
    "cream-of-tartar", "baking-powder", "baking-soda", "vanilla-extract",
}
_PER_ITEM: dict[str, Keeps] = {
    # bought whole
    "yellow-onion": Keeps("each", 1, 30), "red-onion": Keeps("each", 1, 30),
    "shallot": Keeps("each", 1, 30), "garlic": Keeps("head", 1, 21),
    "ginger": Keeps("piece", 1, 21), "lemon": Keeps("each", 1, 21),
    "lime": Keeps("each", 1, 21),
    # bottles and jars
    "sriracha": Keeps("tbsp", 34, 180), "soy-sauce": Keeps("tbsp", 30, 365),
    "tamari": Keeps("tbsp", 20, 365), "fish-sauce": Keeps("tbsp", 13, 365),
    "ketchup": Keeps("tbsp", 64, 180), "bbq-sauce": Keeps("tbsp", 36, 180),
    "worcestershire": Keeps("tbsp", 20, 365), "yellow-mustard": Keeps("tbsp", 16, 180),
    "dijon": Keeps("tbsp", 16, 180), "mayonnaise": Keeps("tbsp", 30, 60),
    "rice-vinegar": Keeps("tbsp", 24, 365), "red-wine-vinegar": Keeps("tbsp", 32, 365),
    "balsamic-vinegar": Keeps("tbsp", 16, 365), "apple-cider-vinegar": Keeps("tbsp", 32, 365),
    "white-vinegar": Keeps("tbsp", 32, 365), "avocado-oil": Keeps("tbsp", 34, 180),
    "coconut-oil": Keeps("tbsp", 28, 365), "sesame-oil": Keeps("tbsp", 10, 180),
    "honey": Keeps("tbsp", 16, 365), "maple-syrup": Keeps("tbsp", 24, 365),
    "peanut-butter": Keeps("tbsp", 28, 90), "tahini": Keeps("tbsp", 28, 90),
    "miso": Keeps("tbsp", 20, 90), "gochujang": Keeps("tbsp", 16, 90),
    "chipotles-adobo": Keeps("tbsp", 10, 14), "tomato-paste": Keeps("tbsp", 10, 7),
    # dry goods
    "almond": Keeps("cup", 1.5, 90), "cashew": Keeps("cup", 1.5, 90),
    "peanut": Keeps("cup", 1.5, 90), "pecans": Keeps("cup", 1.5, 90),
    "walnuts": Keeps("cup", 1.5, 90), "pine-nuts": Keeps("cup", 0.5, 60),
    "pumpkin-seeds": Keeps("cup", 1.5, 90), "chia-seeds": Keeps("tbsp", 24, 365),
    "sesame-seeds": Keeps("tbsp", 16, 365), "dried-cranberries": Keeps("cup", 1.25, 180),
    "rice": Keeps("cup", 5, 365), "wild-rice": Keeps("cup", 2.5, 365),
    "quinoa": Keeps("cup", 2.5, 365), "farro": Keeps("cup", 2.5, 365),
    "couscous": Keeps("cup", 2.5, 365), "pasta": Keeps("oz", 16, 365),
    "spaghetti": Keeps("oz", 16, 365), "orecchiette": Keeps("oz", 16, 365),
    "lasagna-noodles": Keeps("oz", 16, 365), "rice-noodles": Keeps("oz", 14, 365),
    "panko": Keeps("cup", 2, 180), "breadcrumbs": Keeps("cup", 2, 180),
    "cornstarch": Keeps("tbsp", 40, 365),
    # hard cheese
    "parmesan": Keeps("cup", 1.25, 30), "pecorino": Keeps("cup", 1.25, 30),
}


def keeps_for(item: CanonicalItem | None) -> Keeps | None:
    """None for anything not worth tracking (fresh meat, most dairy, bread)."""
    if item is None:
        return None
    if item.id in _PER_ITEM:
        return _PER_ITEM[item.id]
    if item.id in _SPICE_IDS or item.id.startswith("dried-"):
        return _SPICE
    if item.perishability == "tender_herb":
        return Keeps("bunch", 1, 7)
    if item.perishability == "hardy_herb":
        return Keeps("bunch", 1, 14)
    return None


def amountless_need(keeps: Keeps) -> float:
    """'Cilantro, to garnish' uses some: a quarter of a bunch or onion, or a
    tablespoon/teaspoon of something sold by the bottle or jar."""
    return 0.25 if keeps.package <= 4 else 1.0


@dataclass
class Batch:
    item_id: str
    name: str
    qty: float
    unit: str
    expires: str  # ISO date
    week: str = ""

    def fresh(self, as_of: date) -> bool:
        return date.fromisoformat(self.expires) >= as_of


@dataclass(frozen=True)
class UsedLeftover:
    item_id: str
    name: str
    qty: float
    unit: str


def need_in_keeps_units(need: float | None, unit: str | None, keeps: Keeps) -> float | None:
    if need is None:
        return amountless_need(keeps)
    if normalize_unit(unit) == normalize_unit(keeps.unit):
        return need
    return convert(need, unit or "each", keeps.unit)  # None: never guess across


def _available(stock: list[Batch], item_id: str) -> float:
    return sum(b.qty for b in stock if b.item_id == item_id)


def _take(stock: list[Batch], item_id: str, amount: float) -> float:
    """Use the soonest-to-expire first. Mutates `stock`; returns what was taken."""
    taken = 0.0
    for batch in sorted((b for b in stock if b.item_id == item_id), key=lambda b: b.expires):
        if taken >= amount - EPSILON:
            break
        grab = min(batch.qty, amount - taken)
        batch.qty -= grab
        taken += grab
    stock[:] = [b for b in stock if b.qty > EPSILON]
    return taken


def from_before(ledger: list[Batch], iso_week: str) -> list[Batch]:
    """Leftovers left by orders before `iso_week`. A week's own purchases can't
    be leftovers for that same week — otherwise the list, viewed after its order
    was placed, shrinks by what that order left over."""
    return [b for b in ledger if b.week < iso_week]


def apply_leftovers(lines: dict[str, Any], ledger: list[Batch],
                    items: Mapping[str, CanonicalItem], as_of: date) -> list[UsedLeftover]:
    """Cover grocery lines from leftovers. Removes lines that are fully covered,
    shrinks ones that are partly covered, and reports what was drawn on. The
    ledger passed in is not modified."""
    stock = [Batch(**asdict(b)) for b in ledger if b.fresh(as_of)]
    used: list[UsedLeftover] = []
    for key, line in list(lines.items()):
        item = items.get(line.canonical_item_id or "")
        keeps = keeps_for(item)
        if keeps is None:
            continue
        need = need_in_keeps_units(line.need, line.unit, keeps)
        if need is None or need <= EPSILON:
            continue
        have = _available(stock, item.id)
        if have <= EPSILON:
            continue
        same_unit = normalize_unit(line.unit) == normalize_unit(keeps.unit)
        if have + EPSILON < need and not same_unit:
            continue  # partial cover in a unit we can't convert back: buy as listed
        taken = _take(stock, item.id, need)
        used.append(UsedLeftover(item.id, item.name, round(taken, 3), keeps.unit))
        remaining = need - taken
        if remaining <= EPSILON:
            lines.pop(key)
            continue
        line.pantry_adjusted = True
        line.need = remaining
        line.qty = (float(max(1, math.ceil(remaining - 0.01)))
                    if keeps.package <= 1 else remaining)
    return used


def settle(ledger: list[Batch], used: list[UsedLeftover], bought_lines: list[Any],
           items: Mapping[str, CanonicalItem], as_of: date, week: str) -> list[Batch]:
    """The ledger after an order: expired batches dropped, leftovers the list
    drew on used up, and whatever this order leaves over added."""
    stock = [Batch(**asdict(b)) for b in ledger if b.fresh(as_of)]
    for u in used:
        _take(stock, u.item_id, u.qty)
    for line in bought_lines:
        item = items.get(line.canonical_item_id or "")
        keeps = keeps_for(item)
        if keeps is None:
            continue
        need = need_in_keeps_units(line.need, line.unit, keeps)
        if need is None:
            continue
        if keeps.package <= 1 and line.qty is not None:
            bought = need_in_keeps_units(line.qty, line.unit, keeps) or 0.0  # 2 onions
        else:
            bought = max(1, math.ceil(need / keeps.package - 1e-9)) * keeps.package
        left = bought - need
        if left > (0.2 if keeps.package <= 4 else 1.0):
            stock.append(Batch(
                item_id=item.id, name=item.name, qty=round(left, 3), unit=keeps.unit,
                expires=(as_of + timedelta(days=keeps.shelf_days)).isoformat(), week=week,
            ))
    return stock


def on_hand(ledger: list[Batch], as_of: date) -> list[dict[str, Any]]:
    """One row per item still good on `as_of`, for people to read."""
    rows: dict[str, dict[str, Any]] = {}
    for b in ledger:
        if not b.fresh(as_of):
            continue
        row = rows.setdefault(b.item_id, {"item_id": b.item_id, "name": b.name,
                                          "qty": 0.0, "unit": b.unit, "expires": b.expires})
        row["qty"] += b.qty
        row["expires"] = max(row["expires"], b.expires)
    return sorted(rows.values(), key=lambda r: r["name"].lower())


def describe(qty: float, unit: str) -> str:
    if qty < 1 and normalize_unit(unit) in ("each", "head", "bunch"):
        return "part of one"
    label = f"{round(qty, 1):g}"
    return label if normalize_unit(unit) == "each" else f"{label} {unit}"


def rebuild_from_history(user: str, base: Path | None = None, weeks: int = 10) -> list[Batch]:
    """Estimate the ledger from past orders, for a household that ordered before
    leftovers were tracked. Each week is rebuilt with today's rules, but only
    purchases the real order actually contained are counted — so the estimate
    can come out low, never invent a jar that was never bought."""
    from datetime import datetime

    import yaml

    from ..allergen.ontology import load_ontology
    from ..config import load_user_config, user_dir
    from ..planning.selection import needs_shopping
    from ..recipes.merged import load_full_library
    from ..state.store import StateStore
    from .pipeline import build_grocery_list

    config = load_user_config(user, base)
    store = StateStore(user_dir(user, base))
    items = load_ontology()
    by_id = {e.recipe.id: e.recipe for e in load_full_library(user, config.recipe_library, base)}
    ledger: list[Batch] = []
    orders_dir = store.root / "orders"
    if not orders_dir.exists():
        return ledger
    for path in sorted(orders_dir.glob("*.yaml"))[-weeks:]:
        week = path.stem
        plan = store.load_plan(week)
        if not plan or plan.get("status") != "final":
            continue
        order = yaml.safe_load(path.read_text()) or {}
        ordered = {str(l.get("name", "")).lower() for l in order.get("grocery_lines", [])}
        as_of = datetime.fromtimestamp(path.stat().st_mtime).date()
        recipes = [
            (by_id[e["recipe_id"]], e.get("servings", 4))
            for e in needs_shopping(plan.get("entries", [])) if e.get("recipe_id") in by_id
        ]
        result = build_grocery_list(
            recipes=recipes, pantry=store.load_pantry(), standing=[], items=items,
            budget_enabled=False, budget_cents=None,
            substitutions=config.household.item_substitutions,
            staples=store.load_staples(), excluded=store.load_exclusions(week),
            leftovers=ledger, as_of=as_of,
        )
        bought = [l for l in result.lines if l.display_name.lower() in ordered]
        ledger = settle(ledger, result.leftovers_used, bought, items, as_of, week)
    return ledger
