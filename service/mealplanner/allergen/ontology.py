"""Allergen ontology — port of packages/engine/src/allergen/ontology.ts.

Membership is decided ONLY by an item's explicit allergen list. There is
deliberately no name/substring matching anywhere in this module: "coconut
milk" must not match dairy, "cream of tartar" must not match dairy, "water
chestnut" must not match tree_nut, "buckwheat" must not match gluten.

An item unknown to the ontology returns "unknown", which callers must treat
as blocking for allergy-severity restrictions (fail closed, not open).
"""

from __future__ import annotations

from functools import lru_cache
from importlib import resources
from typing import Literal, Mapping

import yaml

from ..schemas.domain import CanonicalItem

ALLERGEN_CLASSES = (
    "dairy",
    "gluten",
    "peanut",
    "tree_nut",
    "shellfish",
    "fish",
    "egg",
    "soy",
    "sesame",
)

MembershipResult = Literal["member", "non_member", "unknown"]


def item_in_allergen_class(
    item: CanonicalItem | None, allergen_class: str
) -> MembershipResult:
    if item is None:
        return "unknown"
    if allergen_class in item.allergens:
        return "member"
    return "non_member"


def lookup_item(
    items: Mapping[str, CanonicalItem], item_id: str | None
) -> CanonicalItem | None:
    return items.get(item_id) if item_id else None


@lru_cache(maxsize=1)
def load_ontology() -> dict[str, CanonicalItem]:
    """Load the packaged canonical-items dataset."""
    data = yaml.safe_load(
        resources.files("mealplanner.allergen").joinpath("ontology_data.yaml").read_text()
    )
    items = {row["id"]: CanonicalItem.model_validate(row) for row in data["items"]}
    return items


@lru_cache(maxsize=1)
def alias_index() -> dict[str, str]:
    """Lowercased name/alias -> item id, for deterministic ingredient matching."""
    index: dict[str, str] = {}
    for item in load_ontology().values():
        index[item.name.lower()] = item.id
        for alias in item.aliases:
            index[alias.lower()] = item.id
    return index


def match_ingredient_text(text: str) -> str | None:
    """Deterministic alias match for a raw ingredient string.

    Exact full-phrase match against names/aliases after light normalization —
    intentionally conservative. No substring matching against allergen names;
    a miss returns None and the backstop fails closed for allergies.
    """
    cleaned = text.lower().strip().rstrip(".,;")
    index = alias_index()
    if cleaned in index:
        return index[cleaned]
    # Try progressively stripping leading qty/unit tokens ("2 cups basmati rice").
    tokens = cleaned.split()
    for start in range(1, min(len(tokens), 4)):
        candidate = " ".join(tokens[start:])
        if candidate in index:
            return index[candidate]
    # Try dropping trailing prep notes after a comma ("cilantro, chopped").
    head = cleaned.split(",")[0].strip()
    if head != cleaned and head in index:
        return index[head]
    return None
