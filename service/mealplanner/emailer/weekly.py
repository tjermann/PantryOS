"""Weekly email builder — renders the menu + grocery + carts email from the
planning run outputs."""

from __future__ import annotations

from datetime import date
from importlib import resources
from typing import Any, Mapping

from jinja2 import Environment, FunctionLoader

from ..grocery.pipeline import GroceryListResult
from ..llm.planner import PlanRunResult
from ..planning.long_lead import detect_long_lead
from ..schemas.domain import CanonicalItem, Household, Recipe

SECTION_LABELS = {
    "produce": "Produce",
    "meat_seafood": "Meat & Seafood",
    "dairy": "Dairy",
    "bakery": "Bakery",
    "frozen": "Frozen",
    "pantry": "Pantry",
    "other": "Other",
}
SECTION_ORDER = ["produce", "meat_seafood", "dairy", "bakery", "frozen", "pantry", "other"]


def _load_template(name: str) -> str | None:
    try:
        return (
            resources.files("mealplanner.emailer").joinpath(f"templates/{name}").read_text()
        )
    except FileNotFoundError:
        return None


_env = Environment(loader=FunctionLoader(_load_template), autoescape=False)


def _fmt_qty(qty: float | None, unit: str | None) -> str:
    if qty is None:
        return ""
    rounded = f"{qty:g}"
    u = f" {unit}" if unit and unit != "each" else ""
    return f" — {rounded}{u}"


def build_weekly_email_context(
    *,
    plan: PlanRunResult,
    grocery: GroceryListResult,
    recipes: Mapping[str, Recipe],
    items: Mapping[str, CanonicalItem],
    household: Household,
    week_start: date,
    carts: list[dict[str, Any]] | None = None,
    feedback_url: str | None = None,
    recipe_links: Mapping[str, str] | None = None,
    rating_links: Mapping[str, list[tuple[int, str]]] | None = None,
) -> dict[str, Any]:
    recipe_links = recipe_links or {}
    rating_links = rating_links or {}
    people = {p.id: p.name for p in household.people}

    entries = []
    long_lead_notes = []
    for e in sorted(plan.proposal.entries, key=lambda x: x.date):
        recipe = recipes.get(e.recipe_id)
        if recipe is None:
            continue
        day = date.fromisoformat(e.date).strftime("%A")
        flags = detect_long_lead(recipe)
        if flags:
            total = sum(f.lead_min for f in flags)
            lead = f"{total / 60:g} hr" if total >= 60 else f"{total} min"
            steps = "" if len(flags) == 1 else f" across {len(flags)} steps"
            long_lead_notes.append(
                f"{day}: {recipe.title} needs {lead} of unattended lead time{steps} — start early"
            )
        time_label = None
        if recipe.published_time_min:
            time_label = f"~{recipe.published_time_min} min listed"
        handling = []
        for h in e.person_handling:
            name = people.get(h.person_id, h.person_id)
            if h.handling == "substitute":
                sub = items.get(h.substitute_item_id) if h.substitute_item_id else None
                detail = f" ({h.substitute_note})" if h.substitute_note else ""
                handling.append(f"{name}: swap in {sub.name if sub else 'substitute'}{detail}")
            elif h.handling == "split":
                handling.append(f"{name}: pull their portion before the restricted ingredient goes in")
            elif h.handling == "skip":
                handling.append(f"{name}: eats separately tonight")
        entries.append(
            {
                "day": day,
                "title": recipe.title,
                "rationale": e.rationale,
                "time_label": time_label,
                "handling": handling,
                "url": recipe_links.get(recipe.id),
                "stars": rating_links.get(recipe.id, []),
            }
        )

    perishable_notes = None
    if plan.proposal.perishable_pairings:
        parts = []
        for pairing in plan.proposal.perishable_pairings:
            item = items.get(pairing.canonical_item_id)
            titles = [recipes[r].title for r in pairing.recipe_ids if r in recipes]
            if item and len(titles) >= 2:
                parts.append(f"{item.name} across {' + '.join(titles)}")
        perishable_notes = "; ".join(parts) or None

    grocery_sections = []
    for key in SECTION_ORDER:
        lines = grocery.sections.get(key)  # type: ignore[arg-type]
        if not lines:
            continue
        grocery_sections.append(
            {
                "label": SECTION_LABELS[key],
                "lines": [
                    {
                        "text": f"{l.display_name}{_fmt_qty(l.qty, l.unit)}",
                        "tag": (
                            "restock" if l.origin == "restock"
                            else "standing" if l.origin == "standing"
                            else "pantry-adjusted" if l.pantry_adjusted
                            else None
                        ),
                    }
                    for l in lines
                ],
            }
        )

    budget_line = None
    if grocery.budget.enabled and grocery.budget.budget_cents:
        if grocery.est_total_cents is not None:
            total = grocery.est_total_cents / 100
            budget = grocery.budget.budget_cents / 100
            headroom = (grocery.budget.under_budget_cents or 0) / 100
            state = f"${headroom:.2f} under" if headroom >= 0 else f"${-headroom:.2f} over"
            budget_line = f"Estimated total ${total:.2f} of ${budget:.2f} budget ({state})."
        else:
            budget_line = "Budget check: some items have no price estimate yet, so no total is shown."

    return {
        "week_label": week_start.strftime("week of %B %-d"),
        "assumed_on_hand": ", ".join(grocery.assumed_on_hand) or None,
        "entries": entries,
        "long_lead_notes": long_lead_notes,
        "perishable_notes": perishable_notes,
        "grocery_sections": grocery_sections,
        "budget_line": budget_line,
        "carts": carts or [],
        "feedback_url": feedback_url,
    }


def render_weekly_email(context: dict[str, Any]) -> tuple[str, str]:
    """Returns (text, html)."""
    text = _env.get_template("weekly.txt.j2").render(**context)
    html = _env.get_template("weekly.html.j2").render(**context)
    return text, html
