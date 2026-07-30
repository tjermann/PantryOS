"""Operator credentials — user_info.json.

PantryOS reads secrets from `user_info.json` in the service directory (copy
`sample_user_info.json` to get started). The file is gitignored; keep it
chmod 600. Environment variables (ANTHROPIC_API_KEY, MEALPLANNER_SMTP_USER/
PASS) still work as a fallback for people who prefer them.

Store passwords deliberately do NOT belong here: store logins happen once in
a visible browser (`mealplanner login`) and persist as a browser profile.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOCATIONS = (
    SERVICE_ROOT / "user_info.json",
    Path.cwd() / "user_info.json",
)


@lru_cache(maxsize=1)
def load_user_info() -> dict:
    override = os.environ.get("PANTRYOS_USER_INFO")
    candidates = (Path(override),) if override else DEFAULT_LOCATIONS
    for path in candidates:
        if path.exists():
            try:
                return json.loads(path.read_text())
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"{path} is not valid JSON: {exc}") from exc
    return {}


def anthropic_key() -> str | None:
    info = load_user_info()
    return info.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY")


def smtp_credentials() -> tuple[str | None, str | None, str]:
    """Returns (user, password, from_name)."""
    email = load_user_info().get("email") or {}
    user = email.get("address") or os.environ.get("MEALPLANNER_SMTP_USER")
    password = email.get("app_password") or os.environ.get("MEALPLANNER_SMTP_PASS")
    from_name = email.get("from_name") or "PantryOS"
    return user, password, from_name
