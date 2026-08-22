"""Reading a reply to the proposal email as a decision about the week.

Katy writes "just the bolognese and the kale salad, plus the two we didn't get
to last week — three dinners total", and that has to become the same thing the
family page's checkboxes produce. The model's only job is matching words to
dishes that already exist; every id it returns is checked against the real menu
before anything is saved, and counts are clamped to what the household can eat.
An unmatched phrase is reported, never guessed at.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from ..schemas.domain import StrictModel

MAX_MENU = 40


class ReplyPicks(StrictModel):
    """What a reply asked for, in the model's words."""

    is_about_picking: bool
    dinner_ids: list[str] = []
    lunch_ids: list[str] = []
    # Dishes from an earlier week the household wants now and already shopped for.
    carry_over_ids: list[str] = []
    dinner_count: int | None = None
    lunch_count: int | None = None
    unmatched: list[str] = []
    other_notes: str | None = None


@dataclass
class AppliedPicks:
    dinners: list[str] = field(default_factory=list)
    lunches: list[str] = field(default_factory=list)
    carried: list[str] = field(default_factory=list)
    dinner_count: int = 0
    lunch_count: int = 0
    unmatched: list[str] = field(default_factory=list)
    # The lasting-preference part of the reply, if any ("less spicy"). Choices
    # about one week are not preferences and must not become them.
    notes: str | None = None

    @property
    def changed(self) -> bool:
        return bool(self.dinners or self.lunches or self.carried)


SYSTEM = """You turn a household's reply to their meal-plan email into a selection.

You are given this week's menu options and a list of dishes from recent weeks.
Match what the reply asks for to those dishes. Rules:

- Only ever return ids that appear in the lists you were given. Never invent one.
- dinner_ids / lunch_ids: options from THIS WEEK's menu they want to eat.
- carry_over_ids: dishes from a RECENT WEEK they want this week — typically
  phrased as not having got round to cooking them. Only use this list for
  dishes that are not among this week's options.
- dinner_count / lunch_count: set only if they say how many meals they want
  this week ("three dinners total"). Otherwise leave null.
- unmatched: any dish they clearly asked for that you could not match to an id.
- other_notes: anything that is a general preference rather than a choice about
  this week ("less spicy", "loved Tuesday"). Null if there is none.
- is_about_picking: false when the reply makes no choice about this week at all.

If the reply is ambiguous, prefer leaving a field empty over guessing."""


def interpret_reply(
    client: Any,
    *,
    model: str,
    reply: str,
    menu: list[dict[str, str]],
    recent: list[dict[str, str]],
) -> ReplyPicks:
    import json

    context = {
        "this_weeks_options": menu[:MAX_MENU],
        "dishes_from_recent_weeks": recent[:MAX_MENU],
        "reply": reply,
    }
    response = client.messages.parse(
        model=model,
        max_tokens=2000,
        system=[{"type": "text", "text": SYSTEM}],
        messages=[{"role": "user", "content": json.dumps(context, sort_keys=True)}],
        output_format=ReplyPicks,
    )
    parsed = getattr(response, "parsed_output", None)
    return parsed if parsed is not None else ReplyPicks(is_about_picking=False)


def apply_picks(
    picks: ReplyPicks,
    plan: dict[str, Any],
    household,
    recent_ids: Mapping[str, str],
) -> AppliedPicks:
    """Fold an interpreted reply into a proposal. Deterministic and defensive:
    the model's ids are filtered against what genuinely exists."""
    entries = plan.get("entries", [])
    menu_dinners = {e["recipe_id"] for e in entries
                    if (e.get("meal_type") or "dinner") == "dinner"}
    menu_lunches = {e["recipe_id"] for e in entries if e.get("meal_type") == "lunch"}

    dinners = [i for i in dict.fromkeys(picks.dinner_ids) if i in menu_dinners]
    lunches = [i for i in dict.fromkeys(picks.lunch_ids) if i in menu_lunches]
    # A carry-over must come from a real earlier plan and not already be on the menu.
    carried = [
        i for i in dict.fromkeys(picks.carry_over_ids)
        if i in recent_ids and i not in menu_dinners and i not in menu_lunches
    ]

    applied = AppliedPicks(
        dinners=dinners, lunches=lunches, carried=carried,
        unmatched=list(picks.unmatched), notes=picks.other_notes,
    )
    if not applied.changed:
        return applied

    # How many meals this week: what they asked for, bounded by what there is.
    wanted_d = picks.dinner_count or (len(dinners) + len(carried))
    wanted_l = picks.lunch_count or len(lunches) or household.lunches_per_week
    applied.dinner_count = max(1, min(wanted_d, len(menu_dinners) + len(carried)))
    applied.lunch_count = max(0, min(wanted_l, len(menu_lunches)))
    return applied
