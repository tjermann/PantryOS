"""Long-lead detection — port of packages/engine/src/planning/longLead.ts.

Long-lead steps (marinades, brines, thaws, slow cooking) must surface at PLAN
time, not be discovered at 6pm. Source rule: any step with more than 30
minutes of unattended lead time gets an explicit prep-ahead flag.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..schemas.domain import Recipe

LONG_LEAD_THRESHOLD_MIN = 30


@dataclass(frozen=True)
class LongLeadFlag:
    recipe_id: str
    step_order: int
    step_text: str
    lead_min: int


def detect_long_lead(recipe: Recipe) -> list[LongLeadFlag]:
    return [
        LongLeadFlag(recipe.id, s.order, s.text, s.duration_min)
        for s in recipe.steps
        if s.unattended
        and s.duration_min is not None
        and s.duration_min > LONG_LEAD_THRESHOLD_MIN
    ]


def total_lead_min(recipe: Recipe) -> int:
    """Total unattended lead minutes — used for 'start by' notification times."""
    return sum(f.lead_min for f in detect_long_lead(recipe))
