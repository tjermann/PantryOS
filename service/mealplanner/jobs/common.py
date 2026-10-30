"""Shared plumbing for the weekly/proposal jobs."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from ..allergen.ontology import load_ontology
from ..config import UserConfig, user_dir
from ..llm.client import client_for_user
from ..llm.planner import PlanRunResult, propose_plan
from ..planning.candidates import cap_candidates, filter_candidates
from ..planning.variety import VarietyRules
from ..recipes.merged import load_full_library
from ..schemas.domain import Recipe
from ..schemas.plan import PlanEntryProposal
from ..state.store import StateStore

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def next_weekday(today: date, name: str) -> date:
    """The next occurrence of a weekday, counting today as that day."""
    return today + timedelta(days=(WEEKDAYS.index(name) - today.weekday()) % 7)


def next_week_dates(today: date, dinners: int,
                    planning_day: str = "saturday") -> list[date]:
    """The nights this plan covers, one dinner per day.

    Cooking starts the day after the cart is loaded, so the week hangs off the
    planning day rather than off whenever we happen to be planning — that way a
    proposal written days earlier names the same nights the shopping run will.
    """
    start = next_weekday(today, planning_day) + timedelta(days=1)
    return [start + timedelta(days=i) for i in range(dinners)]


def iso_week_of(day: date) -> str:
    cal = day.isocalendar()
    return f"{cal.year}-W{cal.week:02d}"


def _scaled_protein_cap(config: UserConfig, shortlist: bool) -> int:
    """Same rule ('not three chicken dinners'), measured against however many
    dishes are on the list."""
    cap = config.variety.max_same_protein_per_week
    if not shortlist:
        return cap
    household = config.household
    ratio = household.shortlist_dinners / max(household.dinners_per_week, 1)
    return max(cap, round(cap * ratio))


def generate_plan(
    user: str,
    config: UserConfig,
    store: StateStore,
    week_dates: list[date],
    base: Path | None = None,
    revision_context: str | None = None,
    shortlist: bool = False,
    requested: list[str] | None = None,
    pick_dinners: int | None = None,
) -> tuple[PlanRunResult, dict[str, Recipe], dict[str, str]]:
    """`requested` dishes are already on the menu: they are kept out of the
    candidate pool and shown to the planner so its options complement them.
    `pick_dinners` is how many of the options the household still chooses."""
    requested = requested or []
    items = load_ontology()
    from ..recipes.merged import apply_source_policy

    library = apply_source_policy(
        load_full_library(user, config.recipe_library, base),
        config.source_policy, config.recipe_sources,
    )
    if config.source_policy == "exclusive":
        print(f"[{user}] exclusive sources: {len(library)} recipes from "
              f"{len(config.recipe_sources)} configured sites")
    recipes_by_id = {e.recipe.id: e.recipe for e in library}
    sources = {e.recipe.id: e.source for e in library if e.source}
    states = store.load_recipe_states()
    candidates, rejected = filter_candidates(
        [e.recipe for e in library if e.recipe.id not in requested], states, config.household, week_dates[0].month,
        today=week_dates[0], repeat_window_days=config.variety.repeat_window_days,
    )
    if not candidates:
        raise RuntimeError("no candidate recipes (library empty or all filtered)")
    pool = cap_candidates(candidates, states, iso_week_of(week_dates[0]))
    if len(pool) < len(candidates):
        print(f"[{user}] {len(candidates)} candidates, sending a weekly-rotating "
              f"pool of {len(pool)} to the planner ({len(rejected)} filtered out)")
    else:
        print(f"[{user}] {len(candidates)} candidates ({len(rejected)} filtered out)")
    candidates = pool
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
        lunches=(
            config.household.shortlist_lunches if shortlist
            else config.household.lunches_per_week
        ),
        variety_rules=VarietyRules(
            # A shortlist holds more dishes than the week does, so the weekly
            # protein cap has to scale with it or every menu trips the warning.
            max_same_protein_per_week=_scaled_protein_cap(config, shortlist),
            repeat_window_days=config.variety.repeat_window_days,
        ),
        revision_context=revision_context,
        shortlist=(
            (pick_dinners if pick_dinners is not None else config.household.dinners_per_week,
             config.household.lunches_per_week)
            if shortlist else None
        ),
        already_chosen=[recipes_by_id[r] for r in requested if r in recipes_by_id],
    )
    if result.dropped_recipe_ids:
        print(f"[{user}] dropped unrepairable entries: {result.dropped_recipe_ids}")
    return result, recipes_by_id, sources


def requested_entries(
    requested: list[str], recipes_by_id: dict[str, Recipe], household,
    week_dates: list[date],
) -> tuple[list[PlanEntryProposal], list[str]]:
    """Plan entries for dishes the household asked for by name. They skip the
    planner, not the allergen backstop: anything it objects to is refused."""
    from ..allergen.backstop import run_allergen_backstop

    items = load_ontology()
    entries: list[PlanEntryProposal] = []
    refused: list[str] = []
    for i, slug in enumerate(requested):
        recipe = recipes_by_id.get(slug)
        if recipe is None:
            refused.append(f"{slug}: not in the recipe library")
            continue
        entry = PlanEntryProposal(
            recipe_id=slug,
            date=week_dates[min(i, len(week_dates) - 1)].isoformat(),
            servings=recipe.serves,
            rationale=REQUESTED_RATIONALE,
        )
        errors = [
            v for v in run_allergen_backstop(
                entry=entry, entry_index=i, recipe=recipe, people=household.people,
                restrictions=household.restrictions, items=items,
            ) if v.severity == "error"
        ]
        if errors:
            refused.append(f"{recipe.title}: {errors[0].message}")
            continue
        entries.append(entry)
    return entries, refused


REQUESTED_RATIONALE = "You asked for this one — it's on the menu."


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
