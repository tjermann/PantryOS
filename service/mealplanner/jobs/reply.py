"""Apply an email reply to the open proposal, and tell the household what stuck.

A reply that chooses meals should do exactly what the family page's checkboxes
do. Anything it could not act on is said out loud in the confirmation, so a
request never disappears into a log file.
"""

from __future__ import annotations

from pathlib import Path

from ..config import UserConfig, user_dir
from ..planning.reply_picks import AppliedPicks, apply_picks, interpret_reply
from ..state.store import StateStore

CARRY_RATIONALE = (
    "Carried over from an earlier week — never got cooked, ingredients already bought."
)


def _menu(plan: dict, titles: dict[str, str]) -> list[dict[str, str]]:
    return [
        {"id": e["recipe_id"],
         "title": titles.get(e["recipe_id"], e["recipe_id"]),
         "meal": e.get("meal_type") or "dinner"}
        for e in plan.get("entries", [])
    ]


def _recent(store: StateStore, titles: dict[str, str], skip: str) -> dict[str, str]:
    """Dishes from the last few weeks, for 'the one we didn't get to' requests."""
    out: dict[str, str] = {}
    plans_dir = store.root / "plans"
    if not plans_dir.exists():
        return out
    import yaml

    for path in sorted(plans_dir.glob("*.yaml"), reverse=True)[:3]:
        if path.stem == skip:
            continue
        data = yaml.safe_load(path.read_text()) or {}
        for entry in data.get("entries", []):
            slug = entry.get("recipe_id")
            if slug and slug not in out:
                out[slug] = titles.get(slug, slug)
    return out


def apply_reply(
    user: str, config: UserConfig, reply: str, base: Path | None = None,
) -> AppliedPicks | None:
    """Returns what was applied, or None if the reply wasn't about this week."""
    store = StateStore(user_dir(user, base))
    latest = store.latest_plan()
    if latest is None or latest[1].get("status") != "proposed":
        return None  # nothing open to change
    iso_week, plan = latest

    from ..recipes.merged import load_full_library

    titles = {
        e.recipe.id: e.recipe.title
        for e in load_full_library(user, config.recipe_library, base)
    }
    recent = _recent(store, titles, skip=iso_week)

    from ..llm.client import client_for_user

    picks = interpret_reply(
        client_for_user(config), model=config.model, reply=reply,
        menu=_menu(plan, titles),
        recent=[{"id": k, "title": v} for k, v in recent.items()],
    )
    if not picks.is_about_picking:
        return None

    applied = apply_picks(picks, plan, config.household, recent)
    if not applied.changed:
        return applied  # asked for something, nothing matched — caller reports it

    known = {e["recipe_id"] for e in plan["entries"]}
    for slug in applied.carried:
        if slug not in known:
            plan["entries"].append({
                "recipe_id": slug, "date": plan["week_dates"][0],
                "meal_type": "dinner", "servings": 4,
                "rationale": CARRY_RATIONALE, "person_handling": [],
                "ingredients_on_hand": True,
            })
    plan["selected"] = [*applied.dinners, *applied.carried, *applied.lunches]
    plan["select_dinners"] = applied.dinner_count
    plan["select_lunches"] = applied.lunch_count
    # The week is settled now: don't let the iterate job re-plan over it.
    plan["fingerprint"] = store.feedback_fingerprint()
    store.save_plan(iso_week, plan)
    return applied


def confirm_email(user: str, config: UserConfig, applied: AppliedPicks,
                  base: Path | None = None) -> None:
    """Say what was understood — a silent change to dinner is worse than none."""
    from ..emailer.sender import send_email
    from ..planning.selection import needs_shopping, resolve_selection
    from ..recipes.merged import load_full_library

    store = StateStore(user_dir(user, base))
    iso_week, plan = store.latest_plan()
    titles = {
        e.recipe.id: e.recipe.title
        for e in load_full_library(user, config.recipe_library, base)
    }
    menu = resolve_selection(plan, config.household)
    shopping = {e["recipe_id"] for e in needs_shopping(menu)}

    lines = ["Got it — here's the week as it now stands:", ""]
    for entry in menu:
        slug = entry["recipe_id"]
        tag = "" if slug in shopping else "   (already shopped for)"
        lines.append(f"  {entry['date']}  {entry['meal_type']:6s}  "
                     f"{titles.get(slug, slug)}{tag}")
    if applied.unmatched:
        lines += ["", "I couldn't match these, so nothing was changed for them:"]
        lines += [f"  - {u}" for u in applied.unmatched]
    shop_day = config.planning_day.capitalize()
    lines += [
        "",
        f"The grocery list covers only the meals still to be shopped for. "
        f"Change anything until {shop_day} morning on the family page:",
    ]
    if config.web_base_url:
        from ..web.app import feedback_url

        lines.append(f"  {feedback_url(user, config.web_base_url.rstrip('/'), base)}")
    text = "\n".join(lines)
    send_email(to=config.email.to, cc=config.email.cc,
               subject=f"Your picks are in — {iso_week}", text=text, html=None)


def settle_fingerprint(user: str, base: Path | None = None) -> None:
    """Mark the open plan as current, so the iterate job sees no outstanding
    feedback and leaves the household's choices alone."""
    store = StateStore(user_dir(user, base))
    latest = store.latest_plan()
    if latest is None or latest[1].get("status") != "proposed":
        return
    iso_week, plan = latest
    store.save_plan(iso_week, {**plan, "fingerprint": store.feedback_fingerprint()})
