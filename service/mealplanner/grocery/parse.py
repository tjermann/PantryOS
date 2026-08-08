"""Parse quantities out of recipe-phrased ingredient lines.

'2 lemons, juiced' -> (2, 'each', 'lemons'); '1 1/2 lb shrimp' -> (1.5, 'lb',
'shrimp'). Without this, imported ingredients carry no quantity and can't be
aggregated — you end up with '2 lemons' and '1 lemon' as separate rows.
"""

from __future__ import annotations

import re

from .units import dimension_of, normalize_unit

_VULGAR = {
    "½": 0.5, "⅓": 1 / 3, "⅔": 2 / 3, "¼": 0.25, "¾": 0.75,
    "⅛": 0.125, "⅜": 0.375, "⅝": 0.625, "⅞": 0.875,
}
_UNIT_WORD = re.compile(
    r"^(cups?|tbsps?|tablespoons?|tsps?|teaspoons?|lbs?|pounds?|ozs?|ounces?|grams?|g|"
    r"kgs?|kilograms?|ml|milliliters?|liters?|l|pints?|quarts?|cloves?|bunch(?:es)?|"
    r"cans?|jars?|packages?|pkgs?|sprigs?|heads?|stalks?|slices?|sticks?)\b",
    re.IGNORECASE,
)
_PREP_TAIL = re.compile(r",.*$")
_PARENS = re.compile(r"\(.*?\)")


def _leading_qty(text: str) -> tuple[float | None, str]:
    """Pull a leading quantity ('1 1/2', '2-3', '½', '1.5') off the string."""
    s = text.strip()
    total = 0.0
    found = False
    while s:
        m = re.match(r"^(\d+)\s*/\s*(\d+)", s)  # 1/2
        if m:
            total += int(m.group(1)) / int(m.group(2))
            s, found = s[m.end():].lstrip(), True
            continue
        m = re.match(r"^(\d+(?:\.\d+)?)\s*(?:to|-|–)\s*\d+(?:\.\d+)?", s)  # 2-3 -> 2
        if m:
            total += float(m.group(1))
            s, found = s[m.end():].lstrip(), True
            break
        m = re.match(r"^(\d+(?:\.\d+)?)", s)  # whole or decimal
        if m:
            total += float(m.group(1))
            s, found = s[m.end():].lstrip(), True
            continue
        if s[0] in _VULGAR:
            total += _VULGAR[s[0]]
            s, found = s[1:].lstrip(), True
            continue
        break
    return (total if found else None), s


def parse_qty_unit(raw: str) -> tuple[float | None, str | None, str]:
    """Returns (qty, normalized_unit, item_name_without_qty/unit)."""
    text = _PARENS.sub(" ", raw).strip()
    # 'juice of 1 lemon' / 'zest and juice of 2 limes' — the count follows the
    # usage phrase; treat the fruit as the item and the count as the quantity.
    m = re.match(r"^(?:[\w\s]*?\b(?:juice|zest)\b[\w\s]*?)\bof\s+(.*)$", text, re.I)
    if m:
        text = m.group(1)
    qty, rest = _leading_qty(text)
    unit = None
    m = _UNIT_WORD.match(rest)
    if m:
        unit = normalize_unit(m.group(1))
        rest = rest[m.end():].lstrip(" .")
        rest = re.sub(r"^of\s+", "", rest)  # 'cup of olive oil' — prefix, not chars
    elif qty is not None:
        unit = "each"
    name = _PREP_TAIL.sub("", rest).strip(" -–,.")
    return qty, unit, (name or raw.strip())


def singularize(word: str) -> str:
    if len(word) > 4 and word.endswith("oes"):
        return word[:-2]
    if len(word) > 3 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("es") and word[-3] in "hsxz":
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


# Words that describe how an ingredient is used, not what to buy — dropping
# them lets 'juice of 1 lemon' and '2 lemons' land on the same shopping line.
_NOISE = {
    "juice", "juiced", "zest", "zested", "zesting", "of", "the", "fresh",
    "freshly", "squeezed", "grated", "chopped", "minced", "sliced", "diced",
    "plus", "more", "for", "serving", "garnish", "to", "taste", "optional",
    "divided", "and", "or", "large", "small", "medium", "about",
}


def aggregation_key(name: str) -> str:
    """Normalized key so 'Lemons', '1 lemon', and 'juice of 1 lemon' group."""
    words = [singularize(w) for w in re.findall(r"[a-z]+", name.lower())]
    meaningful = [w for w in words if w not in _NOISE]
    return " ".join(meaningful or words) or name.lower().strip()


def format_qty(qty: float | None, unit: str | None) -> str:
    """Shopping-friendly quantity: you buy 4 onions, not 3.667."""
    if qty is None:
        return ""
    import math

    if unit in (None, "each", "clove", "bunch", "can", "jar", "package", "head"):
        rounded = max(1, math.ceil(qty - 0.01))
        label = f"{rounded}"
    elif qty < 1:
        label = f"{round(qty, 2):g}"
    else:
        label = f"{round(qty * 4) / 4:g}"  # nearest quarter for measures
    suffix = f" {unit}" if unit and unit != "each" else ""
    return f"{label}{suffix}"


def compatible_units(a: str | None, b: str | None) -> bool:
    if a == b:
        return True
    if a is None or b is None:
        return False
    return dimension_of(a) == dimension_of(b) and dimension_of(a) != "count"
