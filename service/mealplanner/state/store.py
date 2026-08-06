"""Per-user state persistence — human-readable YAML, atomic writes.

Layout under users/<name>/state/:
  recipes.yaml   lifecycle / ratings / last_made / real_time per recipe slug
  pantry.yaml    PantryItem list
  restock.yaml   StandingOrderLine list (things that ran out mid-week)
  learnings.md   free text, injected verbatim into planning context
  plans/<iso-week>.yaml
  orders/<iso-week>.yaml
"""

from __future__ import annotations

import os
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from ..schemas.domain import HouseholdRecipeState, PantryItem, StandingOrderLine


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


class StateStore:
    def __init__(self, user_directory: Path):
        self.root = user_directory / "state"

    # -- recipes ------------------------------------------------------------
    def load_recipe_states(self) -> dict[str, HouseholdRecipeState]:
        path = self.root / "recipes.yaml"
        if not path.exists():
            return {}
        data = yaml.safe_load(path.read_text()) or {}
        return {
            slug: HouseholdRecipeState.model_validate({"recipe_id": slug, **fields})
            for slug, fields in data.items()
        }

    def save_recipe_states(self, states: dict[str, HouseholdRecipeState]) -> None:
        data = {
            slug: {
                k: v
                for k, v in s.model_dump(exclude={"recipe_id"}, exclude_none=True).items()
                if v not in ([], 0) or k == "times_made"
            }
            for slug, s in sorted(states.items())
        }
        _atomic_write(self.root / "recipes.yaml", yaml.safe_dump(data, sort_keys=False))

    def record_rating(
        self,
        slug: str,
        score: int | None = None,
        real_time_min: int | None = None,
        note: str | None = None,
        made_on: date | None = None,
    ) -> HouseholdRecipeState:
        states = self.load_recipe_states()
        state = states.get(slug) or HouseholdRecipeState(recipe_id=slug)
        if score is not None:
            state.ratings.append(score)
            # Lifecycle heuristic: two ratings >=4 → keeper; any <=2 → probation.
            if score <= 2:
                state.lifecycle = "probation"
            elif len([r for r in state.ratings if r >= 4]) >= 2:
                state.lifecycle = "keeper"
        if made_on is not None:
            state.last_made_at = made_on.isoformat()
            state.times_made += 1
        if real_time_min is not None:
            state.real_time_min = real_time_min  # measured; never touches published time
        if note:
            state.notes = f"{state.notes}\n{note}".strip() if state.notes else note
        states[slug] = state
        self.save_recipe_states(states)
        return state

    def set_lifecycle(self, slug: str, lifecycle: str) -> HouseholdRecipeState:
        states = self.load_recipe_states()
        state = states.get(slug) or HouseholdRecipeState(recipe_id=slug)
        state.lifecycle = lifecycle  # type: ignore[assignment]
        states[slug] = state
        self.save_recipe_states(states)
        return state

    # -- pantry / restock ---------------------------------------------------
    def load_pantry(self) -> list[PantryItem]:
        path = self.root / "pantry.yaml"
        if not path.exists():
            return []
        return [PantryItem.model_validate(r) for r in (yaml.safe_load(path.read_text()) or [])]

    def load_restock(self) -> list[StandingOrderLine]:
        path = self.root / "restock.yaml"
        if not path.exists():
            return []
        rows = yaml.safe_load(path.read_text()) or []
        return [
            StandingOrderLine.model_validate({**r, "reason": r.get("reason", "restock")})
            for r in rows
        ]

    def save_restock(self, lines: list[StandingOrderLine]) -> None:
        _atomic_write(
            self.root / "restock.yaml",
            yaml.safe_dump([l.model_dump(exclude_none=True) for l in lines], sort_keys=False),
        )

    def add_restock(self, raw: str, reason: str = "restock") -> None:
        lines = self.load_restock()
        lines.append(StandingOrderLine(raw=raw, reason=reason))
        self.save_restock(lines)

    def feedback_fingerprint(self) -> str:
        """Hash of everything household feedback can touch — compared against a
        proposal's stored fingerprint to detect 'new feedback arrived'."""
        import hashlib

        digest = hashlib.sha256()
        for name in ("learnings.md", "recipes.yaml", "restock.yaml", "staples.yaml"):
            path = self.root / name
            digest.update(name.encode())
            if path.exists():
                digest.update(path.read_bytes())
        config_path = self.root.parent / "config.yaml"
        if config_path.exists():
            digest.update(config_path.read_bytes())
        return digest.hexdigest()

    # -- pantry staples -----------------------------------------------------
    def load_staples(self) -> list[str]:
        """Things assumed on hand (salt, olive oil, spices…): matching grocery
        lines are dropped from purchases until explicitly restocked."""
        path = self.root / "staples.yaml"
        if not path.exists():
            return []
        return list(yaml.safe_load(path.read_text()) or [])

    def save_staples(self, staples: list[str]) -> None:
        cleaned = sorted({s.strip().lower() for s in staples if s.strip()})
        _atomic_write(self.root / "staples.yaml", yaml.safe_dump(cleaned))

    # -- learnings ----------------------------------------------------------
    def load_learnings(self) -> str:
        path = self.root / "learnings.md"
        return path.read_text() if path.exists() else ""

    def append_learning(self, text: str) -> None:
        current = self.load_learnings()
        _atomic_write(self.root / "learnings.md", f"{current.rstrip()}\n- {text}\n".lstrip())

    # -- plans / orders -----------------------------------------------------
    def save_plan(self, iso_week: str, payload: dict[str, Any]) -> Path:
        path = self.root / "plans" / f"{iso_week}.yaml"
        _atomic_write(path, yaml.safe_dump(payload, sort_keys=False, allow_unicode=True))
        return path

    def load_plan(self, iso_week: str) -> dict[str, Any] | None:
        path = self.root / "plans" / f"{iso_week}.yaml"
        return yaml.safe_load(path.read_text()) if path.exists() else None

    def latest_plan(self) -> tuple[str, dict[str, Any]] | None:
        plans_dir = self.root / "plans"
        if not plans_dir.exists():
            return None
        files = sorted(plans_dir.glob("*.yaml"))
        if not files:
            return None
        latest = files[-1]
        return latest.stem, yaml.safe_load(latest.read_text())

    def save_order(self, iso_week: str, payload: dict[str, Any]) -> Path:
        path = self.root / "orders" / f"{iso_week}.yaml"
        _atomic_write(path, yaml.safe_dump(payload, sort_keys=False, allow_unicode=True))
        return path

    def load_orders(self, limit: int = 8) -> list[tuple[str, dict[str, Any]]]:
        orders_dir = self.root / "orders"
        if not orders_dir.exists():
            return []
        files = sorted(orders_dir.glob("*.yaml"))[-limit:]
        return [(f.stem, yaml.safe_load(f.read_text())) for f in files]
