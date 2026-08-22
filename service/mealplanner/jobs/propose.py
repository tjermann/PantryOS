"""The approval flow: propose on proposal day, iterate while the proposal is
open, and let run_weekly execute it on planning day.

  proposal_day 6:15   run-propose  -> proposal email (no cart, nothing bought)
  until planning day  run-iterate  -> new feedback? revise + email a new version
  planning_day 6:30   run-weekly   -> executes the plan: list, cart, final email

The gap between the two days is the household's review window — one day or
several, whatever their config says.
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
                    iteration: int, dry_run: bool, sources=None,
                    shortlist: dict | None = None) -> None:
    from ..allergen.ontology import load_ontology
    from ..grocery.pipeline import build_grocery_list
    from ..planning.selection import resolve_selection

    # Show the would-be grocery list so budget/scale feedback can happen early.
    # On a shortlist that means the default picks — buying for every option
    # would wildly overstate the week.
    entries = result.proposal.entries
    if shortlist:
        chosen = {
            e["recipe_id"] for e in resolve_selection(
                {"entries": [e.model_dump() for e in entries],
                 "week_dates": [d.isoformat() for d in week_dates]},
                config.household,
            )
        }
        entries = [e for e in entries if e.recipe_id in chosen]
    recipes = [
        (recipes_by_id[e.recipe_id], e.servings)
        for e in entries if e.recipe_id in recipes_by_id
    ]
    grocery = build_grocery_list(
        recipes=recipes, pantry=store.load_pantry(),
        standing=[*config.standing_orders, *store.load_restock()],
        items=load_ontology(),
        budget_enabled=config.household.budget_enabled,
        budget_cents=config.household.budget_cents_weekly,
        substitutions=config.household.item_substitutions,
        staples=store.load_staples(),
        excluded=store.load_exclusions(iso_week_of(week_dates[0])),
    )
    feedback_url = None
    recipe_links: dict[str, str] = {}
    rating_links: dict[str, list] = {}
    if config.web_base_url:
        from ..web.app import feedback_url as signed_feedback_url
        from ..web.app import rating_url, recipe_url

        base_url = config.web_base_url.rstrip("/")
        feedback_url = signed_feedback_url(user, base_url, base)
        if shortlist is not None:
            shortlist = {**shortlist, "url": feedback_url}
        recipe_links = {e.recipe_id: recipe_url(user, base_url, e.recipe_id, base)
                        for e in result.proposal.entries}
        rating_links = {
            e.recipe_id: [(n, rating_url(user, base_url, e.recipe_id, n, base))
                          for n in range(1, 6)]
            for e in result.proposal.entries
        }
    version = f" (v{iteration})" if iteration > 1 else ""
    shop_day = config.planning_day.capitalize()
    if shortlist:
        note = (
            f"PICK YOUR MEALS{version} — nothing has been ordered. Choose "
            f"{shortlist['pick_dinners']} of the {shortlist['dinner_options']} dinners "
            f"and {shortlist['pick_lunches']} of the {shortlist['lunch_options']} "
            f"lunches on the family page. You have until {shop_day} morning, when the "
            f"cart is filled from your picks — and not picking is fine: the first "
            f"{shortlist['pick_dinners']} dinners and first {shortlist['pick_lunches']} "
            f"lunch below are the default, and the grocery list shown covers exactly "
            f"those."
        )
        subject = f"Pick this week's meals{version} — cart loads {shop_day}"
    else:
        note = (
            f"PROPOSAL{version} — nothing has been ordered. Reply to this email, tap a "
            f"star, or use the family page with any changes; an updated proposal "
            f"follows. The final plan and cart run {shop_day} morning."
        )
        subject = f"Proposed dinners{version} — speak now, cart loads {shop_day}"
    context = build_weekly_email_context(
        plan=result, grocery=grocery, recipes=recipes_by_id,
        items=load_ontology(), household=config.household,
        week_start=week_dates[0], carts=[],
        feedback_url=feedback_url, recipe_links=recipe_links,
        rating_links=rating_links,
        sources=sources or {},
        proposal_note=note,
        shortlist=shortlist,
    )
    text, html = render_weekly_email(context)
    if dry_run:
        print(text)
        return
    send_email(
        to=config.email.to, cc=config.email.cc,
        subject=subject, text=text, html=html,
    )


def _shortlist_meta(household, result) -> dict:
    """What the email and page need to explain the choice — counted from what
    the planner actually returned, not what we asked for."""
    entries = result.proposal.entries
    return {
        "pick_dinners": household.dinners_per_week,
        "pick_lunches": household.lunches_per_week,
        "dinner_options": sum(1 for e in entries if e.meal_type != "lunch"),
        "lunch_options": sum(1 for e in entries if e.meal_type == "lunch"),
    }


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
    household = config.household
    # The shortlist is generated over more slots than the week has nights; the
    # real nights are stored separately and assigned once they pick.
    week_dates = next_week_dates(today, household.dinners_per_week, config.planning_day)
    option_dates = next_week_dates(today, household.shortlist_dinners, config.planning_day)
    result, recipes_by_id, sources = generate_plan(
        user, config, store, option_dates, base, shortlist=household.offers_choice
    )
    iso_week = iso_week_of(week_dates[0])
    shortlist = _shortlist_meta(household, result) if household.offers_choice else None
    if not dry_run:
        store.save_plan(iso_week, plan_payload(
            result, iso_week, status="proposed", iteration=1,
            fingerprint=store.feedback_fingerprint(),
            week_dates=[d.isoformat() for d in week_dates],
            select_dinners=household.dinners_per_week,
            select_lunches=household.lunches_per_week,
            selected=None,
        ))
    _proposal_email(user, config, store, result, recipes_by_id, week_dates, base, 1,
                    dry_run, sources, shortlist)
    print(f"[{user}] proposal sent ({iso_week})"
          + (f" — {shortlist['dinner_options']} dinner / "
             f"{shortlist['lunch_options']} lunch options to pick from"
             if shortlist else ""))

    # Same morning: ask how last week's meals actually went.
    from .review import run_review

    try:
        run_review(user, base=base, dry_run=dry_run, today=today)
    except Exception as exc:  # a review failure must never block the proposal
        print(f"[{user}] review email skipped: {exc}")
    return 0


def run_iterate(user: str, *, base: Path | None = None, dry_run: bool = False,
                today: date | None = None) -> int:
    today = today or date.today()
    config = load_user_config(user, base)
    if config.proposal_day is None:
        return 0
    store = StateStore(user_dir(user, base))
    latest = store.latest_plan()
    if latest is None:
        return 0
    iso_week, plan = latest
    # An open proposal is the signal, not the calendar: the review window can
    # span several days, and it closes the moment run_weekly marks it final.
    if plan.get("status") != "proposed":
        return 0
    current = store.feedback_fingerprint()
    if current == plan.get("fingerprint"):
        print(f"[{user}] no new feedback; proposal stands")
        return 0
    if plan.get("selected"):
        # Someone has already said what they want to eat. A machine-generated
        # revision must not overrule that: re-planning here would silently
        # replace chosen dinners, and any carried-over meal with food already
        # in the fridge would vanish with it. The feedback is saved and shapes
        # next week; this week is changed on the family page, by a person.
        print(f"[{user}] {iso_week} picks are already in — feedback recorded for "
              f"next week rather than rewriting a settled plan")
        store.save_plan(iso_week, {**plan, "fingerprint": current})
        return 0

    iteration = int(plan.get("iteration", 1)) + 1
    print(f"[{user}] new feedback — revising proposal (v{iteration})")
    household = config.household
    week_dates = [date.fromisoformat(d) for d in plan.get("week_dates", [])] or \
        next_week_dates(today, household.dinners_per_week, config.planning_day)
    option_dates = next_week_dates(today, household.shortlist_dinners, config.planning_day)
    previous = json.dumps(plan.get("entries", []))
    result, recipes_by_id, sources = generate_plan(
        user, config, store, option_dates, base, revision_context=previous,
        shortlist=household.offers_choice,
    )
    shortlist = _shortlist_meta(household, result) if household.offers_choice else None
    # Meals whose groceries are already bought survive every revision — dropping
    # one would waste food that is sitting in the fridge.
    carried = [e for e in plan.get("entries", []) if e.get("ingredients_on_hand")]
    if carried:
        print(f"[{user}] keeping {len(carried)} already-shopped-for meal(s)")
    if not dry_run:
        payload = plan_payload(
            result, iso_week, status="proposed", iteration=iteration,
            fingerprint=store.feedback_fingerprint(),
            week_dates=[d.isoformat() for d in week_dates],
            select_dinners=plan.get("select_dinners") or household.dinners_per_week,
            select_lunches=plan.get("select_lunches") or household.lunches_per_week,
            selected=None,
        )
        payload["entries"] = payload["entries"] + carried
        store.save_plan(iso_week, payload)
    _proposal_email(user, config, store, result, recipes_by_id, week_dates, base,
                    iteration, dry_run, sources, shortlist)
    print(f"[{user}] revised proposal v{iteration} sent ({iso_week})")
    return 0
