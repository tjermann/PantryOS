"""Recipe importer — builds the structured parsed cache from markdown files.

For each recipe markdown, one Claude call (recipe-parser prompt v1) extracts
structured ingredients/steps; canonical-item matching then happens
DETERMINISTICALLY in code via the ontology alias index — the LLM never picks
ontology ids. Cache entries carry a sha256 of the source markdown so only
changed files re-parse. Costs pennies per recipe; run via
`mealplanner import-recipes`.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

import anthropic
from pydantic import BaseModel, ConfigDict, Field

from ..allergen.ontology import match_ingredient_text
from ..prompts.v1.recipe_parser import RECIPE_PARSER_SYSTEM_PROMPT
from ..recipes.library import LibraryEntry


class ParsedIngredient(BaseModel):
    model_config = ConfigDict(extra="forbid")
    raw: str
    qty: float | None = None
    unit: str | None = None
    prep_note: str | None = None
    is_optional: bool = False
    group: str | None = None  # "Sauce", "Marinade", … when the source groups them
    added_at_step: int | None = None


class ParsedStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order: int
    text: str
    duration_min: int | None = None
    unattended: bool = False


class ParsedRecipe(BaseModel):
    model_config = ConfigDict(extra="forbid")
    serves: int | None = None
    cuisine: str | None = None
    effort: Literal["easy", "moderate", "involved"] = "moderate"
    ingredients: list[ParsedIngredient] = Field(default_factory=list)
    steps: list[ParsedStep] = Field(default_factory=list)
    is_recipe: bool = True


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def parse_recipe_markdown(
    client: anthropic.Anthropic, markdown: str, model: str = "claude-opus-5"
) -> ParsedRecipe:
    """One structured-output Claude call. Import parsing is mechanical
    extraction, so low effort keeps it fast and cheap."""
    response = client.messages.parse(
        model=model,
        max_tokens=8000,
        system=RECIPE_PARSER_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": markdown}],
        output_format=ParsedRecipe,
        output_config={"effort": "low"},
    )
    parsed = response.parsed_output
    if parsed is None:
        raise RuntimeError("Recipe parse returned no structured output")
    return parsed


def enrich_with_ontology(parsed: ParsedRecipe) -> list[dict]:
    """Deterministic canonical-item matching on the raw ingredient strings."""
    out = []
    for ing in parsed.ingredients:
        out.append(
            {
                "canonical_item_id": match_ingredient_text(ing.raw),
                "raw": ing.raw,
                "qty": ing.qty,
                "unit": ing.unit,
                "prep_note": ing.prep_note,
                "is_optional": ing.is_optional,
                "group": ing.group,
                "added_at_step": ing.added_at_step,
            }
        )
    return out


class GeneratedSteps(BaseModel):
    model_config = ConfigDict(extra="forbid")
    steps: list[ParsedStep] = Field(default_factory=list)


DIRECTIONS_PROMPT = """You write clear home-cook directions for a recipe when the
original directions are unavailable. You are given the recipe title and its exact
ingredient list. Write concise numbered steps a competent home cook can follow:
sensible order, standard technique for this well-known dish, temperatures and
doneness cues, duration_min on steps with meaningful time, unattended=true for
hands-off waits (marinating, chilling, simmering, roasting). Use ONLY the listed
ingredients. 6-12 steps."""


def generate_directions(
    client: anthropic.Anthropic,
    entry: LibraryEntry,
    parsed_dir: Path,
    model: str = "claude-opus-5",
) -> bool:
    """Fill in AI-written steps for a cached recipe that has none. Returns True
    if directions were written."""
    cache_file = parsed_dir / f"{entry.recipe.id}.json"
    if not cache_file.exists():
        return False
    data = json.loads(cache_file.read_text())
    if data.get("steps"):
        return False
    ingredients = "\n".join(f"- {i['raw']}" for i in data.get("ingredients", []))
    response = client.messages.parse(
        model=model,
        max_tokens=8000,
        system=DIRECTIONS_PROMPT,
        messages=[{
            "role": "user",
            "content": f"Recipe: {entry.recipe.title}\nServes: {entry.recipe.serves}\n"
                       f"Ingredients:\n{ingredients}",
        }],
        output_format=GeneratedSteps,
        output_config={"effort": "low"},
    )
    generated = response.parsed_output
    if generated is None or not generated.steps:
        return False
    data["steps"] = [s.model_dump() for s in generated.steps]
    data["directions_ai_generated"] = True
    cache_file.write_text(json.dumps(data, indent=2))
    return True


def import_entry(
    client: anthropic.Anthropic,
    entry: LibraryEntry,
    parsed_dir: Path,
    model: str = "claude-opus-5",
    force: bool = False,
) -> Literal["parsed", "cached", "no_markdown", "not_a_recipe"]:
    if not entry.markdown_path.exists():
        return "no_markdown"
    markdown = entry.markdown_path.read_text(encoding="utf-8")
    digest = _sha256(markdown)
    cache_file = parsed_dir / f"{entry.recipe.id}.json"

    if not force and cache_file.exists():
        cached = json.loads(cache_file.read_text())
        if cached.get("source_sha256") == digest:
            return "cached"

    parsed = parse_recipe_markdown(client, markdown, model=model)
    if not parsed.is_recipe:
        return "not_a_recipe"

    parsed_dir.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(
        json.dumps(
            {
                "source_sha256": digest,
                "serves": parsed.serves,
                "cuisine": parsed.cuisine,
                "effort": parsed.effort,
                "ingredients": enrich_with_ontology(parsed),
                "steps": [s.model_dump() for s in parsed.steps],
            },
            indent=2,
        )
    )
    return "parsed"
