"""Per-user configuration — users/<name>/config.yaml, validated on every load."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from .schemas.domain import Household, StandingOrderLine

Weekday = Literal[
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"
]

EQUIPMENT_CHOICES = [
    "instant_pot", "rice_cooker", "air_fryer", "stand_mixer", "grill",
    "sheet_pan", "dutch_oven", "food_processor", "wok", "slow_cooker",
]


class EmailConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to: list[str] = Field(min_length=1)
    cc: list[str] = Field(default_factory=list)


class StoreConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    adapter: str  # driver name in mealplanner.carts
    enabled: bool = True
    # Optional routing: only these grocery sections go to this store.
    sections: list[str] | None = None


class VarietyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_same_protein_per_week: int = 2
    repeat_window_days: int = 21


class EmailsEnabled(BaseModel):
    model_config = ConfigDict(extra="forbid")
    weekly: bool = True
    restock: bool = True
    tonight: bool = True


class UserConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    timezone: str = "America/New_York"
    email: EmailConfig
    # "api" = Anthropic API key (user_info.json / env). "claude-cli" = headless
    # Claude Code on the operator's Claude subscription — no per-token billing.
    llm_backend: Literal["api", "claude-cli"] = "api"
    claude_cli_path: str = "claude"
    # Optional; falls back to user_info.json, then the ANTHROPIC_API_KEY env var.
    anthropic_api_key: str | None = None
    model: str = "claude-opus-5"
    recipe_library: str
    planning_day: Weekday = "saturday"
    dinner_hour: int = Field(default=18, ge=0, le=23)
    household: Household
    variety: VarietyConfig = Field(default_factory=VarietyConfig)
    stores: list[StoreConfig] = Field(default_factory=list)
    standing_orders: list[StandingOrderLine] = Field(default_factory=list)
    emails_enabled: EmailsEnabled = Field(default_factory=EmailsEnabled)
    organic_preference: Literal["none", "produce_only", "everything"] = "none"
    # Base URL of the feedback web UI, used for signed links in emails.
    web_base_url: str | None = None


def users_root(base: Path | None = None) -> Path:
    if base is not None:
        return base
    env = os.environ.get("MEALPLANNER_USERS_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / "users"


def user_dir(user: str, base: Path | None = None) -> Path:
    return users_root(base) / user


def load_user_config(user: str, base: Path | None = None) -> UserConfig:
    path = user_dir(user, base) / "config.yaml"
    data = yaml.safe_load(path.read_text())
    return UserConfig.model_validate(data)


def save_user_config(user: str, config: UserConfig, base: Path | None = None) -> Path:
    directory = user_dir(user, base)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "config.yaml"
    path.write_text(yaml.safe_dump(config.model_dump(exclude_none=True), sort_keys=False))
    os.chmod(path, 0o600)  # may hold an API key
    return path


def list_users(base: Path | None = None) -> list[str]:
    root = users_root(base)
    if not root.exists():
        return []
    return sorted(
        p.parent.name for p in root.glob("*/config.yaml")
    )


def resolve_api_key(config: UserConfig) -> str:
    from .credentials import anthropic_key

    key = config.anthropic_api_key or anthropic_key()
    if not key:
        raise RuntimeError(
            f"No Anthropic API key for user {config.name}: set anthropic_api_key in "
            f"user_info.json (copy sample_user_info.json), or per-user in config.yaml."
        )
    return key
