"""'How was last week?' — a Friday companion to the proposal email.

Lists the meals actually cooked in the last executed week with one-tap star
links, keeper/never-again links, and an invitation to just reply. Ratings
feed the lifecycle (two 4+ makes a keeper, two lows retire it) and every
reply lands in planning context for the next round.
"""

from __future__ import annotations

from datetime import date
from importlib import resources
from pathlib import Path
from typing import Any

from jinja2 import Environment, FunctionLoader

from ..config import load_user_config, user_dir
from ..emailer.sender import send_email
from ..emailer.weekly import _source_label
from ..recipes.merged import load_full_library
from ..state.store import StateStore


def _load_template(name: str) -> str | None:
    try:
        return (
            resources.files("mealplanner.emailer").joinpath(f"templates/{name}").read_text()
        )
    except FileNotFoundError:
        return None


_env = Environment(loader=FunctionLoader(_load_template), autoescape=False)


def build_review_context(
    user: str, base: Path | None = None, today: date | None = None
) -> dict[str, Any] | None:
    today = today or date.today()
    config = load_user_config(user, base)
    store = StateStore(user_dir(user, base))
    last = store.last_executed_plan()
    if last is None:
        return None
    week, plan = last

    library = {e.recipe.id: e for e in load_full_library(user, config.recipe_library, base)}
    states = store.load_recipe_states()
    base_url = (config.web_base_url or "").rstrip("/")
    meals = []
    for entry in plan.get("entries", []):
        # Only ask about meals whose day has actually passed.
        try:
            when = date.fromisoformat(entry.get("date", ""))
        except ValueError:
            continue
        if when >= today:
            continue
        lib_entry = library.get(entry.get("recipe_id"))
        if lib_entry is None:
            continue
        recipe = lib_entry.recipe
        state = states.get(recipe.id)
        rated = bool(state and state.ratings)
        stars, keep_url, cut_url, recipe_link = [], None, None, None
        if base_url:
            from ..web.app import rating_url, recipe_url
            from ..web.app import _serializer

            s = _serializer(user, base)
            stars = [(n, rating_url(user, base_url, recipe.id, n, base)) for n in range(1, 6)]
            keep_url = f"{base_url}/mark/{user}?t={s.dumps({'u': user, 'm': recipe.id, 'lc': 'keeper'})}"
            cut_url = f"{base_url}/mark/{user}?t={s.dumps({'u': user, 'm': recipe.id, 'lc': 'cut'})}"
            recipe_link = recipe_url(user, base_url, recipe.id, base)
        meals.append({
            "day": when.strftime("%A"),
            "meal_type": entry.get("meal_type", "dinner"),
            "title": recipe.title,
            "url": recipe_link,
            "source": lib_entry.source,
            "source_label": _source_label(lib_entry.source),
            "stars": stars,
            "keep_url": keep_url,
            "cut_url": cut_url,
            "rated": rated,
            "current": (
                f"{sum(state.ratings) / len(state.ratings):.1f}★" if rated else None
            ),
            "lifecycle": state.lifecycle if state else "to_try",
        })
    if not meals:
        return None
    return {
        "week_label": week,
        "meals": meals,
        "feedback_url": (
            __import__("mealplanner.web.app", fromlist=["feedback_url"]).feedback_url(
                user, base_url, base
            ) if base_url else None
        ),
    }


def run_review(user: str, *, base: Path | None = None, dry_run: bool = False,
               today: date | None = None) -> int:
    config = load_user_config(user, base)
    context = build_review_context(user, base, today)
    if context is None:
        print(f"[{user}] no completed week to review yet")
        return 0
    text = _env.get_template("review.txt.j2").render(**context)
    html = _env.get_template("review.html.j2").render(**context)
    if dry_run:
        print(text)
        return 0
    send_email(
        to=config.email.to, cc=config.email.cc,
        subject="How was last week? (tap a star, or just reply)",
        text=text, html=html,
    )
    print(f"[{user}] review email sent ({len(context['meals'])} meals)")
    return 0
