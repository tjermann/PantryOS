"""Path helpers for per-user data."""

from __future__ import annotations

from pathlib import Path

from .config import user_dir


def parsed_cache_dir(user: str, base: Path | None = None) -> Path:
    """Structured-recipe cache built by `import-recipes`."""
    return user_dir(user, base) / "parsed"


def browser_profile_dir(user: str, store_id: str, base: Path | None = None) -> Path:
    """Playwright persistent-context directory for one user+store."""
    return user_dir(user, base) / "browser" / store_id
