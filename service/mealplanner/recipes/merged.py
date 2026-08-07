"""One call to load everything a user can cook: the configured library plus
their personal web-imported recipes (personal wins on slug collisions)."""

from __future__ import annotations

from pathlib import Path

from ..paths import parsed_cache_dir
from .library import LibraryEntry, load_library
from .webimport import personal_library_dir


def load_full_library(
    user: str, configured_library: str, base: Path | None = None
) -> list[LibraryEntry]:
    parsed = parsed_cache_dir(user, base)
    entries: list[LibraryEntry] = []
    configured = Path(configured_library)
    if (configured / "index.csv").exists():
        entries.extend(load_library(configured, parsed))
    personal = personal_library_dir(user, base)
    if (personal / "index.csv").exists():
        from dataclasses import replace

        entries.extend(
            replace(e, personal=True) for e in load_library(personal, parsed)
        )
    by_id: dict[str, LibraryEntry] = {}
    for entry in entries:
        by_id[entry.recipe.id] = entry
    return list(by_id.values())


def apply_source_policy(
    entries: list[LibraryEntry], policy: str, sources: list[str]
) -> list[LibraryEntry]:
    """'exclusive': keep only recipes from the configured source sites, plus
    the household's own hand-imported ones."""
    if policy != "exclusive" or not sources:
        return entries
    from urllib.parse import urlparse

    domains = {urlparse(s).netloc.removeprefix("www.").lower() for s in sources}
    kept = []
    for e in entries:
        source = (e.source or "").lower()
        if e.personal or any(d in source for d in domains):
            kept.append(e)
    return kept
