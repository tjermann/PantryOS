"""Tonight's-dinner email: the dish, a start-by time from long-lead flags,
split-point reminders, and condensed deterministic cook notes."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

from ..allergen.ontology import load_ontology
from ..config import load_user_config, user_dir
from ..emailer.sender import send_email
from ..paths import parsed_cache_dir
from ..planning.long_lead import total_lead_min
from ..recipes.merged import load_full_library
from ..state.store import StateStore


def run_tonight(user: str, *, base: Path | None = None, dry_run: bool = False,
                today: date | None = None) -> int:
    today = today or date.today()
    config = load_user_config(user, base)
    if not config.emails_enabled.tonight:
        return 0
    store = StateStore(user_dir(user, base))
    latest = store.latest_plan()
    if latest is None:
        return 0
    _, plan = latest
    entry = next((e for e in plan.get("entries", []) if e.get("date") == today.isoformat()), None)
    if entry is None:
        return 0

    library = load_full_library(user, config.recipe_library, base)
    match = next((e for e in library if e.recipe.id == entry["recipe_id"]), None)
    if match is None:
        return 0
    recipe = match.recipe

    dinner = datetime.combine(today, datetime.min.time()) + timedelta(hours=config.dinner_hour)
    lead = total_lead_min(recipe)
    cook = recipe.published_time_min or 45
    start_by = dinner - timedelta(minutes=lead + cook)

    people = {p.id: p.name for p in config.household.people}
    lines = [f"Tonight: {recipe.title}"]
    lines.append(f"Aim to start by {start_by.strftime('%-I:%M %p')} for dinner at "
                 f"{dinner.strftime('%-I:%M %p')}"
                 + (f" (includes {lead} min unattended lead time)" if lead else ""))
    for h in entry.get("person_handling", []):
        name = people.get(h.get("person_id"), h.get("person_id"))
        if h.get("handling") == "split":
            step_hint = ""
            restricted = [i for i in recipe.ingredients if i.added_at_step and i.added_at_step > 1]
            if restricted:
                first = min(i.added_at_step for i in restricted)
                step_hint = f" (before step {first})"
            lines.append(f"Split: pull {name}'s portion before the restricted ingredient{step_hint}")
        elif h.get("handling") == "substitute":
            lines.append(f"Substitute for {name}: {h.get('substitute_note') or h.get('substitute_item_id')}")
    if recipe.steps:
        lines.append("")
        lines.append("Steps:")
        for s in recipe.steps:
            marker = " (hands-off)" if s.unattended else ""
            timing = f" ~{s.duration_min} min" if s.duration_min else ""
            lines.append(f"  {s.order}. {s.text}{timing}{marker}")
    state = store.load_recipe_states().get(recipe.id)
    if state and state.notes:
        lines.append("")
        lines.append(f"Your notes from last time: {state.notes}")

    body = "\n".join(lines)
    html = "<pre style='font-family: Georgia, serif;'>" + body + "</pre>"
    if dry_run:
        print(body)
        return 0
    send_email(to=config.email.to, cc=config.email.cc,
               subject=f"Tonight: {recipe.title}", text=body, html=html)
    print(f"[{user}] tonight email sent")
    return 0
