"""Shared plumbing for the weekly/proposal jobs."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from ..allergen.ontology import load_ontology
from ..config import UserConfig, user_dir
from ..llm.client import client_for_user
from ..llm.planner import PlanRunResult, propose_plan
from ..planning.candidates import filter_candidates
from ..planning.variety import VarietyRules
from ..recipes.merged import load_full_library
from ..schemas.domain import Recipe
from ..state.store import StateStore

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def next_week_dates(today: date, dinners: int) -> list[date]:
    """Plan starting tomorrow, one dinner per day."""
    start = today + timedelta(days=1)
    return [start + timedelta(days=i) for i in range(dinners)]


def iso_week_of(day: date) -> str:
    cal = day.isocalendar()
    return f"{cal.year}-W{cal.week:02d}"


def generate_plan(
    user: str,
    config: UserConfig,
    store: StateStore,
    week_dates: list[date],
    base: Path | None = None,
    revision_context: str | None = None,
) -> tuple[PlanRunResult, dict[str, Recipe]]:
    items = load_ontology()
    library = load_full_library(user, config.recipe_library, base)
    recipes_by_id = {e.recipe.id: e.recipe for e in library}
    states = store.load_recipe_states()
    candidates, rejected = filter_candidates(
        [e.recipe for e in library], states, config.household, week_dates[0].month
    )
    if not candidates:
        raise RuntimeError("no candidate recipes (library empty or all filtered)")
    print(f"[{user}] {len(candidates)} candidates ({len(rejected)} filtered out)")
    client = client_for_user(config)
    result = propose_plan(
        client,
        model=config.model,
        candidates=candidates,
        states=states,
        items=items,
        household=config.household,
        week_dates=week_dates,
        learnings=store.load_learnings(),
        variety_rules=VarietyRules(
            max_same_protein_per_week=config.variety.max_same_protein_per_week,
            repeat_window_days=config.variety.repeat_window_days,
        ),
        revision_context=revision_context,
    )
    if result.dropped_recipe_ids:
        print(f"[{user}] dropped unrepairable entries: {result.dropped_recipe_ids}")
    return result, recipes_by_id


def plan_payload(result: PlanRunResult, iso_week: str, **extra) -> dict:
    return {
        "week": iso_week,
        "prompt_version": result.prompt_version,
        "model": result.model,
        "usage": result.usage.__dict__,
        "entries": [e.model_dump() for e in result.proposal.entries],
        "warnings": [v.model_dump() for v in result.validation.warnings],
        "dropped": result.dropped_recipe_ids,
        **extra,
    }
