"""Unit normalization + conversion — port of packages/engine/src/grocery/units.ts.

Volume↔mass conversions require an item-specific density and are only
attempted when one is known — otherwise quantities stay in their original
unit and are listed as separate lines.
"""

from __future__ import annotations

from typing import Literal

_UNIT_ALIASES: dict[str, str] = {
    "tablespoon": "tbsp", "tablespoons": "tbsp", "tbs": "tbsp", "tbsp": "tbsp",
    "teaspoon": "tsp", "teaspoons": "tsp", "tsp": "tsp",
    "cup": "cup", "cups": "cup",
    "ounce": "oz", "ounces": "oz", "oz": "oz",
    "pound": "lb", "pounds": "lb", "lbs": "lb", "lb": "lb",
    "gram": "g", "grams": "g", "g": "g",
    "kilogram": "kg", "kilograms": "kg", "kg": "kg",
    "milliliter": "ml", "milliliters": "ml", "ml": "ml",
    "liter": "l", "liters": "l", "l": "l",
    "pint": "pint", "pints": "pint",
    "quart": "quart", "quarts": "quart",
    "clove": "clove", "cloves": "clove",
    "bunch": "bunch", "bunches": "bunch",
    "can": "can", "cans": "can",
    "each": "each", "count": "each", "piece": "each", "pieces": "each",
}

_VOLUME_TO_ML: dict[str, float] = {
    "tsp": 4.929, "tbsp": 14.787, "cup": 236.588,
    "pint": 473.176, "quart": 946.353, "ml": 1.0, "l": 1000.0,
}
_MASS_TO_G: dict[str, float] = {"oz": 28.3495, "lb": 453.592, "g": 1.0, "kg": 1000.0}

Dimension = Literal["volume", "mass", "count"]


def normalize_unit(unit: str | None) -> str:
    if not unit:
        return "each"
    stripped = unit.strip().lower()
    return _UNIT_ALIASES.get(stripped, stripped)


def dimension_of(unit: str) -> Dimension:
    u = normalize_unit(unit)
    if u in _VOLUME_TO_ML:
        return "volume"
    if u in _MASS_TO_G:
        return "mass"
    return "count"


def convert(qty: float, from_unit: str, to_unit: str) -> float | None:
    """Convert qty between units of the same dimension; None when impossible."""
    f = normalize_unit(from_unit)
    t = normalize_unit(to_unit)
    if f == t:
        return qty
    if f in _VOLUME_TO_ML and t in _VOLUME_TO_ML:
        return qty * _VOLUME_TO_ML[f] / _VOLUME_TO_ML[t]
    if f in _MASS_TO_G and t in _MASS_TO_G:
        return qty * _MASS_TO_G[f] / _MASS_TO_G[t]
    return None
