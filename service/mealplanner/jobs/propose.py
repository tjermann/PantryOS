"""The approval flow: propose on proposal day, iterate on feedback, and let
run_weekly execute the approved plan the next morning.

  Friday 6:15  run-propose  -> 'Proposed dinners' email (no cart, nothing bought)
  Friday 9-18  run-iterate  -> new feedback? revise + email updated proposal
  Saturday     run-weekly   -> executes the latest proposal: list, cart, final email
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from ..config import load_user_config, user_dir
from ..emailer.sender import send_email
from ..emailer.weekly import build_weekly_email_context, render_weekly_email
from ..state.store import StateStore
from .common import WEEKDAYS, generate_plan, iso_week_of, next_week_dates, plan_payload


def _proposal_email(user, config, store, result, recipes_by_id, week_dates, base,
                    iteration: int, dry_run: bool) -> None:
    from ..allergen.ontology import load_ontology
    from ..grocery.pipeline import build_grocery_list

    # Show the would-be grocery list so budget/scale feedback can happen early.
    recipes = [
        (recipes_by_id[e.recipe_id], e.servings)
        for e in result.proposal.entries if e.recipe_id in recipes_by_id
    ]
    grocery = build_grocery_list(
        recipes=recipes, pantry=store.load_pantry(),
        standing=[*config.standing_orders, *store.load_restock()],
        items=load_ontology(),
        budget_enabled=config.household.budget_enabled,
        budget_cents=config.household.budget_cents_weekly,
        substitutions=config.household.item_substitutions,
        staples=store.load_staples(),
    )
    feedback_url = None
    recipe_links: dict[str, str] = {}
    rating_links: dict[str, list] = {}
    if config.web_base_url:
        from ..web.app import feedback_url as signed_feedback_url
        from ..web.app import rating_url, recipe_url

        base_url = config.web_base_url.rstrip("/")
        feedback_url = signed_feedback_url(user, base_url, base)
        recipe_links = {e.recipe_id: recipe_url(user, base_url, e.recipe_id, base)
                        for e in result.proposal.entries}
        rating_links = {
            e.recipe_id: [(n, rating_url(user, base_url, e.recipe_id, n, base))
                          for n in range(1, 6)]
            for e in result.proposal.entries
        }
    version = f" (v{iteration})" if iteration > 1 else ""
    context = build_weekly_email_context(
        plan=result, grocery=grocery, recipes=recipes_by_id,
        items=load_ontology(), household=config.household,
        week_start=week_dates[0], carts=[],
        feedback_url=feedback_url, recipe_links=recipe_links,
        rating_links=rating_links,
        proposal_note=(
            f"PROPOSAL{version} — nothing has been ordered. Reply to this email, tap a "
            f"star, or use the family page with any changes today; an updated proposal "
            f"follows. The final plan and cart run tomorrow morning."
        ),
    )
    text, html = render_weekly_email(context)
    if dry_run:
        print(text)
        return
    send_email(
        to=config.email.to, cc=config.email.cc,
        subject=f"Proposed dinners{version} — speak now, cart loads tomorrow",
        text=text, html=html,
    )


def run_propose(user: str, *, base: Path | None = None, dry_run: bool = False,
                force: bool = False, today: date | None = None) -> int:
    today = today or date.today()
    config = load_user_config(user, base)
    if config.proposal_day is None:
        return 0
    if not force and WEEKDAYS[today.weekday()] != config.proposal_day:
        print(f"[{user}] not proposal day ({config.proposal_day}); skipping")
        return 0
    store = StateStore(user_dir(user, base))
    week_dates = next_week_dates(today, config.household.dinners_per_week)
    result, recipes_by_id = generate_plan(user, config, store, week_dates, base)
    iso_week = iso_week_of(week_dates[0])
    if not dry_run:
        store.save_plan(iso_week, plan_payload(
            result, iso_week, status="proposed", iteration=1,
            fingerprint=store.feedback_fingerprint(),
            week_dates=[d.isoformat() for d in week_dates],
        ))
    _proposal_email(user, config, store, result, recipes_by_id, week_dates, base, 1, dry_run)
    print(f"[{user}] proposal sent ({iso_week})")
    return 0


def run_iterate(user: str, *, base: Path | None = None, dry_run: bool = False,
                today: date | None = None) -> int:
    today = today or date.today()
    config = load_user_config(user, base)
    if config.proposal_day is None or WEEKDAYS[today.weekday()] != config.proposal_day:
        return 0
    store = StateStore(user_dir(user, base))
    latest = store.latest_plan()
    if latest is None:
        return 0
    iso_week, plan = latest
    if plan.get("status") != "proposed":
        return 0
    current = store.feedback_fingerprint()
    if current == plan.get("fingerprint"):
        print(f"[{user}] no new feedback; proposal stands")
        return 0

    iteration = int(plan.get("iteration", 1)) + 1
    print(f"[{user}] new feedback — revising proposal (v{iteration})")
    week_dates = [date.fromisoformat(d) for d in plan.get("week_dates", [])] or \
        next_week_dates(today, config.household.dinners_per_week)
    previous = json.dumps(plan.get("entries", []))
    result, recipes_by_id = generate_plan(
        user, config, store, week_dates, base, revision_context=previous
    )
    if not dry_run:
        store.save_plan(iso_week, plan_payload(
            result, iso_week, status="proposed", iteration=iteration,
            fingerprint=store.feedback_fingerprint(),
            week_dates=[d.isoformat() for d in week_dates],
        ))
    _proposal_email(user, config, store, result, recipes_by_id, week_dates, base,
                    iteration, dry_run)
    print(f"[{user}] revised proposal v{iteration} sent ({iso_week})")
    return 0
