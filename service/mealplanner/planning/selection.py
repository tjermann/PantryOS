"""Which of the proposed meals are actually happening this week.

The Friday proposal can be a shortlist — say 7 dinners and 2 lunches — that the
household picks 4 and 1 from. Everything downstream (the grocery list on the
review page, the cart, Saturday's email) has to agree on exactly that subset, so
it is resolved in one place.

Nobody picking is a normal Saturday, not an error: the planner ordered the
shortlist best-first, so an unanswered week falls back to the top options and
the household still eats.
"""

from __future__ import annotations

from typing import Any

from ..schemas.domain import Household


def _meal(entry: dict[str, Any]) -> str:
    return entry.get("meal_type") or "dinner"


def resolve_selection(plan: dict[str, Any], household: Household) -> list[dict[str, Any]]:
    """The week's real menu: the household's picks, topped up from the shortlist
    if they picked short, re-dated onto the actual nights."""
    entries = list(plan.get("entries", []))
    dinners = [e for e in entries if _meal(e) == "dinner"]
    lunches = [e for e in entries if _meal(e) == "lunch"]
    picked = set(plan.get("selected") or [])

    def choose(pool: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
        chosen = [e for e in pool if e.get("recipe_id") in picked]
        # Top up in the planner's own order so a partial or absent pick still
        # fills the week.
        rest = [e for e in pool if e.get("recipe_id") not in picked]
        return (chosen + rest)[:count]

    return _redate(
        choose(dinners, household.dinners_per_week),
        choose(lunches, household.lunches_per_week),
        plan.get("week_dates") or [],
    )


def _redate(
    dinners: list[dict[str, Any]], lunches: list[dict[str, Any]], dates: list[str]
) -> list[dict[str, Any]]:
    """Shortlist entries carry placeholder dates; the chosen ones get the real
    nights, in the order they were proposed."""
    out: list[dict[str, Any]] = []
    for i, entry in enumerate(dinners):
        entry = dict(entry)
        if i < len(dates):
            entry["date"] = dates[i]
        out.append(entry)
    for entry in lunches:
        entry = dict(entry)
        if dates:
            entry["date"] = dates[0]  # batch-cooked at the start of the week
        entry["meal_type"] = "lunch"
        out.append(entry)
    return out


def selection_counts(plan: dict[str, Any], household: Household) -> tuple[int, int]:
    """(dinner options, lunch options) actually present on this proposal."""
    entries = plan.get("entries", [])
    return (
        sum(1 for e in entries if _meal(e) == "dinner"),
        sum(1 for e in entries if _meal(e) == "lunch"),
    )
