"""Import a recipe from a URL into the user's personal library.

Most recipe blogs (including Begin With Balance, Cookie and Kate, Half Baked
Harvest) embed schema.org/Recipe JSON-LD; we extract deterministically, then
one small Claude call classifies protein/cuisine/seasons/effort, assigns
ingredient groups, and marks unattended steps. The result lands in
users/<user>/recipes/ (index.csv + library/ + parsed cache entry), which is
merged with the configured library at planning time.

Recipes are stored for the household's own use only — never redistributed.
"""

from __future__ import annotations

import csv
import json
import re
import urllib.request
from pathlib import Path
from typing import Literal

import anthropic
from pydantic import BaseModel, ConfigDict, Field

from ..allergen.ontology import match_ingredient_text
from ..config import user_dir
from .library import slugify

USER_AGENT = "Mozilla/5.0 (PantryOS home meal planner; personal use)"


def personal_library_dir(user: str, base: Path | None = None) -> Path:
    return user_dir(user, base) / "recipes"


def fetch_html(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _iso_duration_min(value: str | None) -> int | None:
    if not value:
        return None
    m = re.match(r"^PT(?:(\d+)H)?(?:(\d+)M)?", str(value))
    if not m or (m.group(1) is None and m.group(2) is None):
        return None
    return int(m.group(1) or 0) * 60 + int(m.group(2) or 0)


def _first_recipe_node(data) -> dict | None:
    """Find the @type=Recipe node in a JSON-LD document (handles @graph/lists)."""
    stack = [data]
    while stack:
        node = stack.pop()
        if isinstance(node, list):
            stack.extend(node)
        elif isinstance(node, dict):
            node_type = node.get("@type", "")
            types = node_type if isinstance(node_type, list) else [node_type]
            if any(t == "Recipe" for t in types):
                return node
            stack.extend(node.get("@graph", []))
    return None


def extract_jsonld_recipe(html: str) -> dict | None:
    """Returns {title, serves, total_min, ingredients: [str], steps: [str]} or None."""
    for match in re.finditer(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.DOTALL | re.IGNORECASE,
    ):
        try:
            data = json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            continue
        node = _first_recipe_node(data)
        if node is None:
            continue
        ingredients = [str(i).strip() for i in node.get("recipeIngredient", []) if str(i).strip()]
        steps: list[str] = []
        def _collect(instr):
            for item in instr if isinstance(instr, list) else [instr]:
                if isinstance(item, dict):
                    if item.get("@type") == "HowToSection":
                        _collect(item.get("itemListElement", []))
                    else:
                        text = item.get("text") or item.get("name") or ""
                        if text.strip():
                            steps.append(re.sub(r"\s+", " ", text).strip())
                elif isinstance(item, str) and item.strip():
                    steps.append(item.strip())
        _collect(node.get("recipeInstructions", []))
        if not ingredients:
            continue
        serves = None
        yield_val = node.get("recipeYield")
        if yield_val:
            first = yield_val[0] if isinstance(yield_val, list) else yield_val
            m = re.search(r"\d+", str(first))
            serves = int(m.group()) if m else None
        return {
            "title": re.sub(r"\s+", " ", str(node.get("name", "Imported recipe"))).strip(),
            "serves": serves,
            "total_min": _iso_duration_min(node.get("totalTime"))
                         or _iso_duration_min(node.get("cookTime")),
            "ingredients": ingredients,
            "steps": steps,
        }
    return None


class _Classification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    protein: str
    cuisine: str
    seasons: list[Literal["spring", "summer", "fall", "winter", "year_round"]]
    effort: Literal["easy", "moderate", "involved"]
    # Parallel to the ingredient list: component group per ingredient (null when ungrouped).
    ingredient_groups: list[str | None] = Field(default_factory=list)
    # 1-based indices of steps that are hands-off waits, with their minutes.
    unattended_steps: list[dict] = Field(default_factory=list)


CLASSIFY_PROMPT = """You annotate a structured recipe. Given its title, ingredients
(numbered), and steps (numbered), return: the main protein (one lowercase word, or
'veg'), cuisine (lowercase), applicable seasons (['year_round'] when unclear),
effort (easy/moderate/involved by hands-on work), ingredient_groups (one entry PER
ingredient, in order: the component it belongs to like 'Sauce'/'Marinade' when the
recipe has components, else null), and unattended_steps (objects {"step": n,
"minutes": m} for hands-off waits like marinating/baking/simmering)."""


def import_from_url(
    client: anthropic.Anthropic,
    user: str,
    url: str,
    model: str = "claude-opus-5",
    base: Path | None = None,
) -> str:
    """Import one recipe; returns its slug. Raises on unparseable pages."""
    html = fetch_html(url)
    data = extract_jsonld_recipe(html)
    if data is None:
        raise ValueError(
            f"No structured recipe found at {url} — the page may not be a recipe, "
            f"or the site doesn't publish recipe data."
        )
    if not data["steps"]:
        raise ValueError(f"Recipe at {url} has no instructions in its structured data.")

    numbered_ings = "\n".join(f"{i+1}. {s}" for i, s in enumerate(data["ingredients"]))
    numbered_steps = "\n".join(f"{i+1}. {s}" for i, s in enumerate(data["steps"]))
    response = client.messages.parse(
        model=model,
        max_tokens=4000,
        system=CLASSIFY_PROMPT,
        messages=[{
            "role": "user",
            "content": f"Title: {data['title']}\nIngredients:\n{numbered_ings}\n\nSteps:\n{numbered_steps}",
        }],
        output_format=_Classification,
        output_config={"effort": "low"},
    )
    cls = response.parsed_output or _Classification(
        protein="veg", cuisine="unspecified", seasons=["year_round"], effort="moderate"
    )
    groups = list(cls.ingredient_groups) + [None] * len(data["ingredients"])
    unattended = {
        int(u.get("step", 0)): int(u.get("minutes", 0) or 0)
        for u in cls.unattended_steps if u.get("step")
    }

    slug = slugify(data["title"])
    lib = personal_library_dir(user, base)
    (lib / "library").mkdir(parents=True, exist_ok=True)

    # Markdown (display + provenance)
    md_name = f"{data['title'].replace('/', '-')}.md"
    md_lines = [f"# {data['title']}", "", f"**Source:** {url}",
                f"**Servings:** {data['serves'] or 4}"]
    if data["total_min"]:
        md_lines.append(f"**Published time:** {data['total_min']} minutes")
    md_lines += ["", "## Ingredients", ""]
    last_group = None
    for ing_text, group in zip(data["ingredients"], groups):
        if group and group != last_group:
            md_lines.append(f"- **{group}:**")
        last_group = group or last_group
        md_lines.append(f"- {ing_text}")
    md_lines += ["", "## Directions", ""]
    md_lines += [f"{i+1}. {s}" for i, s in enumerate(data["steps"])]
    (lib / "library" / md_name).write_text("\n".join(md_lines) + "\n")

    # Index row
    index = lib / "index.csv"
    header = "recipe,season,protein,dairy_work,published_time,real_time,serves,instant_pot,source,file\n"
    if not index.exists():
        index.write_text(header)
    season_label = "Year-round" if "year_round" in cls.seasons else "/".join(
        s.title() for s in cls.seasons
    )
    with index.open("a", newline="") as f:
        csv.writer(f).writerow([
            data["title"], season_label, cls.protein.title(), "",
            f"{data['total_min']} minutes" if data["total_min"] else "",
            "", str(data["serves"] or 4), "", url, md_name,
        ])

    # Parsed cache entry (structured, ready to plan/cook)
    from ..paths import parsed_cache_dir

    parsed = {
        "source_sha256": "webimport",
        "serves": data["serves"] or 4,
        "cuisine": cls.cuisine,
        "effort": cls.effort,
        "ingredients": [
            {
                "canonical_item_id": match_ingredient_text(text),
                "raw": text, "qty": None, "unit": None, "prep_note": None,
                "is_optional": False, "group": group, "added_at_step": None,
            }
            for text, group in zip(data["ingredients"], groups)
        ],
        "steps": [
            {
                "order": i + 1, "text": s,
                "duration_min": unattended.get(i + 1) or None,
                "unattended": (i + 1) in unattended,
            }
            for i, s in enumerate(data["steps"])
        ],
    }
    cache_dir = parsed_cache_dir(user, base)
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"{slug}.json").write_text(json.dumps(parsed, indent=2))
    return slug
