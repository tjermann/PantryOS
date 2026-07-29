"""The weekly run: plan → grocery list → carts → email → persist state."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

from ..config import UserConfig, load_user_config, user_dir
from ..grocery.pipeline import build_grocery_list
from ..llm.client import client_for_user
from ..llm.planner import propose_plan
from ..allergen.ontology import load_ontology
from ..emailer.sender import send_email
from ..emailer.weekly import build_weekly_email_context, render_weekly_email
from ..paths import parsed_cache_dir
from ..planning.candidates import filter_candidates
from ..planning.variety import VarietyRules
from ..recipes.library import load_library
from ..state.store import StateStore

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def next_week_dates(today: date, dinners: int) -> list[date]:
    """Plan starting tomorrow, one dinner per day."""
    start = today + timedelta(days=1)
    return [start + timedelta(days=i) for i in range(dinners)]


def is_planning_day(config: UserConfig, today: date) -> bool:
    return WEEKDAYS[today.weekday()] == config.planning_day


def run_weekly(
    user: str,
    *,
    base: Path | None = None,
    dry_run: bool = False,
    skip_carts: bool = False,
    force: bool = False,
    today: date | None = None,
) -> int:
    today = today or date.today()
    config = load_user_config(user, base)
    if not force and not is_planning_day(config, today):
        print(f"[{user}] not planning day ({config.planning_day}); skipping")
        return 0

    store = StateStore(user_dir(user, base))
    items = load_ontology()
    library = load_library(Path(config.recipe_library), parsed_cache_dir(user, base))
    recipes_by_id = {e.recipe.id: e.recipe for e in library}
    states = store.load_recipe_states()

    week_dates = next_week_dates(today, config.household.dinners_per_week)
    candidates, rejected = filter_candidates(
        [e.recipe for e in library], states, config.household, week_dates[0].month
    )
    if not candidates:
        print(f"[{user}] no candidate recipes (library empty or all filtered)", file=sys.stderr)
        return 1
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
    )
    if result.dropped_recipe_ids:
        print(f"[{user}] dropped unrepairable entries: {result.dropped_recipe_ids}")

    plan_recipes = [
        (recipes_by_id[e.recipe_id], e.servings)
        for e in result.proposal.entries
        if e.recipe_id in recipes_by_id
    ]
    grocery = build_grocery_list(
        recipes=plan_recipes,
        pantry=store.load_pantry(),
        standing=[*config.standing_orders, *store.load_restock()],
        items=items,
        budget_enabled=config.household.budget_enabled,
        budget_cents=config.household.budget_cents_weekly,
    )

    carts: list[dict] = []
    if not skip_carts and config.stores:
        from ..carts.runner import load_all_carts  # deferred: playwright import

        carts = load_all_carts(user, config, grocery.lines, base=base, dry_run=dry_run)

    feedback_url = None
    if config.web_base_url:
        from ..web.app import feedback_url as signed_feedback_url

        feedback_url = signed_feedback_url(user, config.web_base_url.rstrip("/"), base)
    context = build_weekly_email_context(
        plan=result,
        grocery=grocery,
        recipes=recipes_by_id,
        items=items,
        household=config.household,
        week_start=week_dates[0],
        carts=carts,
        feedback_url=feedback_url,
    )
    text, html = render_weekly_email(context)

    iso_week = f"{week_dates[0].isocalendar().year}-W{week_dates[0].isocalendar().week:02d}"
    if dry_run:
        print(text)
        print(f"[{user}] dry run — no email sent, no state written")
        return 0

    send_email(
        to=config.email.to,
        cc=config.email.cc,
        subject=f"Dinners for the {context['week_label']}",
        text=text,
        html=html,
    )
    store.save_plan(
        iso_week,
        {
            "week": iso_week,
            "prompt_version": result.prompt_version,
            "model": result.model,
            "usage": result.usage.__dict__,
            "entries": [e.model_dump() for e in result.proposal.entries],
            "warnings": [v.model_dump() for v in result.validation.warnings],
            "dropped": result.dropped_recipe_ids,
        },
    )
    store.save_order(
        iso_week,
        {
            "week": iso_week,
            "grocery_lines": [
                {
                    "name": l.display_name,
                    "qty": l.qty,
                    "unit": l.unit,
                    "section": l.section,
                    "origin": l.origin,
                }
                for l in grocery.lines
            ],
            "carts": carts,
            "review": None,  # filled in by `mealplanner review-orders`
        },
    )
    print(f"[{user}] weekly email sent to {', '.join(config.email.to)} ({iso_week})")
    return 0
