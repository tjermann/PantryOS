import type { Recipe } from "../schemas/domain.js";

/**
 * Long-lead steps (marinades, brines, thaws, slow cooking) must surface at
 * PLAN time, not be discovered at 6pm. Source rule: any step with more than
 * 30 minutes of unattended lead time gets an explicit prep-ahead flag.
 */
export const LONG_LEAD_THRESHOLD_MIN = 30;

export interface LongLeadFlag {
  recipeId: string;
  stepOrder: number;
  stepText: string;
  leadMin: number;
}

export function detectLongLead(recipe: Recipe): LongLeadFlag[] {
  return recipe.steps
    .filter(
      (s) =>
        s.unattended &&
        s.durationMin !== null &&
        s.durationMin > LONG_LEAD_THRESHOLD_MIN,
    )
    .map((s) => ({
      recipeId: recipe.id,
      stepOrder: s.order,
      stepText: s.text,
      leadMin: s.durationMin as number,
    }));
}

/** Total unattended lead minutes — used to compute "start by" notification times. */
export function totalLeadMin(recipe: Recipe): number {
  return detectLongLead(recipe).reduce((sum, f) => sum + f.leadMin, 0);
}
