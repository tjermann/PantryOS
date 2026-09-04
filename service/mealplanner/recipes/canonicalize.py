"""Match already-parsed ingredient lines to canonical items.

Imports leave `canonical_item_id` null whenever the parser wasn't confident, and
a null means the raw recipe line goes on the shopping list verbatim. That is
ugly, but the real cost is duplication: one recipe's "chicken breasts" becomes a
tidy item while another's "1 1/2 lbs chicken breasts (about 2-3 large)" stays a
separate line, and the household buys chicken twice.

Matching here is deliberately conservative — a whole-phrase hit on a canonical
name or alias, longest first, never a fuzzy guess. Nulls are only ever filled,
never overwritten.
"""

from __future__ import annotations

import re
from typing import Iterable, Mapping

from ..schemas.domain import CanonicalItem

# Words that describe handling rather than the thing being bought.
_NOISE = re.compile(
    r"\b(chopped|diced|minced|sliced|shredded|crumbled|grated|melted|softened|"
    r"drained|rinsed|cooked|uncooked|raw|fresh|frozen|canned|optional|large|"
    r"small|medium|thinly|roughly|coarsely|finely|packed|divided|to taste|"
    r"about|approximately|plus more|for garnish|for serving)\b",
    re.IGNORECASE,
)


def clean_line(raw: str) -> str:
    """Strip quantities, parentheticals and prep words down to the noun."""
    text = re.sub(r"\([^)]*\)", " ", raw)          # (about 2-3 large breasts)
    text = re.sub(r"[\d/¼½¾⅓⅔⅛.,-]+", " ", text)   # quantities and fractions
    text = _NOISE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def _phrases(items: Mapping[str, CanonicalItem]) -> list[tuple[str, str]]:
    """(phrase, item_id) longest-first, so 'chicken breast' beats 'chicken'."""
    out: list[tuple[str, str]] = []
    for item in items.values():
        for phrase in [item.name, *item.aliases]:
            cleaned = phrase.strip().lower()
            if cleaned:
                out.append((cleaned, item.id))
    return sorted(out, key=lambda p: -len(p[0]))


# A word right after the match that makes it a different product: avocado oil
# is not an avocado, garlic powder is not garlic. Usage words like "juice" are
# fine — juice of a lime still means buying limes.
_TURNS_INTO_ANOTHER_PRODUCT = {
    "oil", "sauce", "powder", "paste", "extract", "vinegar", "seasoning",
    "milk", "butter", "broth", "stock", "flour", "sugar", "salt", "flakes",
}


def match_line(raw: str, items: Mapping[str, CanonicalItem],
               phrases: list[tuple[str, str]] | None = None) -> str | None:
    text = clean_line(raw)
    if not text:
        return None
    for phrase, item_id in (phrases if phrases is not None else _phrases(items)):
        singular = phrase[:-1] if phrase.endswith("s") else phrase
        found = re.search(rf"\b{re.escape(singular)}e?s?\b", text)
        if not found:
            continue
        after = text[found.end():].strip().split(" ")[:1]
        if after and after[0] in _TURNS_INTO_ANOTHER_PRODUCT:
            item_name = items[item_id].name.lower()
            if after[0] not in item_name:
                continue  # e.g. matched "avocado" inside "avocado oil"
        return item_id
    return None


def backfill(recipes: Iterable[dict], items: Mapping[str, CanonicalItem]) -> int:
    """Fill null canonical ids in place. Returns how many were filled."""
    phrases = _phrases(items)
    filled = 0
    for recipe in recipes:
        for ingredient in recipe.get("ingredients", []):
            if ingredient.get("canonical_item_id"):
                continue
            match = match_line(ingredient.get("raw", ""), items, phrases)
            if match:
                ingredient["canonical_item_id"] = match
                filled += 1
    return filled
