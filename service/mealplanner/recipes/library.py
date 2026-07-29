"""Recipe library reader — consumes the reference workspace format in place:
an `index.csv` (recipe,season,protein,dairy_work,published_time,real_time,
serves,instant_pot,source,file) plus markdown files in `library/`.

The CSV's free-text fields are normalized here (serves "4 to 6" → 4, times
"1 hr 30 min" → 90). Structured ingredients/steps come from the parsed cache
built by the importer — without a cache entry a recipe still loads, but with
empty ingredients, which the allergen backstop treats as unverifiable and the
planner excludes for allergy households (fail closed).
"""

from __future__ import annotations

import csv
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from ..schemas.domain import Recipe, Season

_SEASON_MAP: dict[str, Season] = {
    "spring": "spring",
    "summer": "summer",
    "fall": "fall",
    "autumn": "fall",
    "winter": "winter",
    "year-round": "year_round",
    "year round": "year_round",
    "yearround": "year_round",
}


def slugify(title: str) -> str:
    norm = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", norm.lower()).strip("-")


def parse_serves(text: str | None) -> int:
    """Free text → single integer, taking the low end of ranges. Default 4."""
    if not text:
        return 4
    match = re.search(r"\d+", text)
    return int(match.group()) if match else 4


def parse_time_min(text: str | None) -> int | None:
    """'50 minutes' → 50, '1 hr 30 min' → 90, '3 hr 30 min' → 210."""
    if not text or not text.strip():
        return None
    t = text.lower()
    hours = re.search(r"(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|hr\b|h\b)", t)
    mins = re.search(r"(\d+)\s*(?:minutes?|mins?|min\b|m\b)", t)
    total = 0.0
    if hours:
        total += float(hours.group(1)) * 60
    if mins:
        total += int(mins.group(1))
    if not hours and not mins:
        bare = re.search(r"\d+", t)
        if bare:
            total = int(bare.group())
    return int(total) if total > 0 else None


def parse_seasons(text: str | None) -> list[Season]:
    if not text:
        return ["year_round"]
    seasons: list[Season] = []
    for part in re.split(r"[/,]", text):
        season = _SEASON_MAP.get(part.strip().lower())
        if season and season not in seasons:
            seasons.append(season)
    return seasons or ["year_round"]


@dataclass(frozen=True)
class LibraryEntry:
    recipe: Recipe
    source: str | None
    markdown_path: Path
    real_time_min: int | None  # measured column from the index; state-level data


def _cuisine_guess(title: str, protein: str) -> str:
    """The reference index has no cuisine column; default to 'unspecified'.

    The parsed cache (importer) may refine this; planning treats 'unspecified'
    as never triggering back-to-back-cuisine warnings against itself.
    """
    return "unspecified"


def load_library(library_root: Path, parsed_dir: Path | None = None) -> list[LibraryEntry]:
    """Read index.csv + markdown library; merge structured data from the parsed
    cache when present."""
    index_path = library_root / "index.csv"
    lib_dir = library_root / "library"
    entries: list[LibraryEntry] = []

    with index_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            title = (row.get("recipe") or "").strip()
            if not title:
                continue
            slug = slugify(title)
            md_path = lib_dir / (row.get("file") or "").strip()

            parsed: dict = {}
            if parsed_dir is not None:
                cache_file = parsed_dir / f"{slug}.json"
                if cache_file.exists():
                    parsed = json.loads(cache_file.read_text())

            equipment = ["instant_pot"] if (row.get("instant_pot") or "").strip().lower() == "yes" else []
            recipe = Recipe(
                id=slug,
                title=title,
                serves=parsed.get("serves") or parse_serves(row.get("serves")),
                published_time_min=parse_time_min(row.get("published_time")),
                protein=(row.get("protein") or "unknown").strip().lower(),
                cuisine=parsed.get("cuisine") or _cuisine_guess(title, row.get("protein") or ""),
                seasons=parse_seasons(row.get("season")),
                equipment=equipment,
                effort=parsed.get("effort", "moderate"),
                ingredients=parsed.get("ingredients", []),
                steps=parsed.get("steps", []),
            )
            entries.append(
                LibraryEntry(
                    recipe=recipe,
                    source=(row.get("source") or "").strip() or None,
                    markdown_path=md_path,
                    real_time_min=parse_time_min(row.get("real_time")),
                )
            )
    return entries
