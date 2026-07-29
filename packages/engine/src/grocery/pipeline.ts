import type {
  CanonicalItem,
  PantryItem,
  Recipe,
  StandingOrderLine,
  StoreSection,
} from "../schemas/domain.js";
import { convert, normalizeUnit } from "./units.js";

/**
 * The grocery pipeline, ported from the source system:
 *  1. Aggregate the same ingredient across recipes into one line.
 *  2. Subtract confirmed pantry stock.
 *  3. Add standing order lines (kids' meals, restocks).
 *  4. Group by store section.
 *  5. Report budget status if enabled.
 */
export interface GroceryLine {
  canonicalItemId: string | null;
  displayName: string;
  qty: number | null;
  unit: string | null;
  section: StoreSection;
  origin: "recipe" | "standing" | "restock";
  sourceRecipeIds: string[];
  estPriceCents: number | null;
  /** True when we subtracted pantry stock from this line. */
  pantryAdjusted: boolean;
}

export interface GroceryListResult {
  sections: Partial<Record<StoreSection, GroceryLine[]>>;
  lines: GroceryLine[];
  estTotalCents: number | null;
  budget: {
    enabled: boolean;
    budgetCents: number | null;
    underBudgetCents: number | null;
  };
}

export interface BuildListInput {
  recipes: { recipe: Recipe; servings: number }[];
  pantry: PantryItem[];
  standing: StandingOrderLine[];
  items: ReadonlyMap<string, CanonicalItem>;
  budgetEnabled: boolean;
  budgetCents: number | null;
}

export function buildGroceryList(input: BuildListInput): GroceryListResult {
  const lines = new Map<string, GroceryLine>();
  const unmatched: GroceryLine[] = [];

  // 1. Aggregate matched ingredients by (item, dimension-compatible unit).
  for (const { recipe, servings } of input.recipes) {
    const scale = servings / recipe.serves;
    for (const ing of recipe.ingredients) {
      if (ing.isOptional) continue;
      if (!ing.canonicalItemId || ing.qty === null) {
        // Unmatched or unquantified: keep verbatim, never silently dropped.
        unmatched.push({
          canonicalItemId: ing.canonicalItemId,
          displayName: ing.raw,
          qty: ing.qty !== null ? ing.qty * scale : null,
          unit: ing.unit,
          section: "other",
          origin: "recipe",
          sourceRecipeIds: [recipe.id],
          estPriceCents: null,
          pantryAdjusted: false,
        });
        continue;
      }
      const item = input.items.get(ing.canonicalItemId);
      const unit = normalizeUnit(ing.unit);
      const qty = ing.qty * scale;
      const existing = lines.get(ing.canonicalItemId);
      if (existing && existing.qty !== null && existing.unit !== null) {
        const converted = convert(qty, unit, existing.unit);
        if (converted !== null) {
          existing.qty += converted;
          existing.sourceRecipeIds.push(recipe.id);
          continue;
        }
      }
      if (!existing) {
        lines.set(ing.canonicalItemId, {
          canonicalItemId: ing.canonicalItemId,
          displayName: item?.name ?? ing.raw,
          qty,
          unit,
          section: item?.storeSection ?? "other",
          origin: "recipe",
          sourceRecipeIds: [recipe.id],
          estPriceCents: item?.typicalPriceCents ?? null,
          pantryAdjusted: false,
        });
      } else {
        // Same item, incompatible units — separate verbatim line.
        unmatched.push({
          canonicalItemId: ing.canonicalItemId,
          displayName: item?.name ?? ing.raw,
          qty,
          unit,
          section: item?.storeSection ?? "other",
          origin: "recipe",
          sourceRecipeIds: [recipe.id],
          estPriceCents: null,
          pantryAdjusted: false,
        });
      }
    }
  }

  // 2. Subtract confirmed pantry stock.
  for (const pantryItem of input.pantry) {
    if (pantryItem.confidence !== "confirmed") continue;
    const line = lines.get(pantryItem.canonicalItemId);
    if (!line || line.qty === null || line.unit === null) continue;
    const onHand = convert(pantryItem.qty, pantryItem.unit, line.unit);
    if (onHand === null) continue;
    line.qty = Math.max(0, line.qty - onHand);
    line.pantryAdjusted = true;
  }

  // 3. Standing lines.
  const standingLines: GroceryLine[] = input.standing.map((s) => {
    const item = s.canonicalItemId ? input.items.get(s.canonicalItemId) : undefined;
    return {
      canonicalItemId: s.canonicalItemId,
      displayName: item?.name ?? s.raw,
      qty: s.qty,
      unit: s.unit,
      section: item?.storeSection ?? "other",
      origin: (s.reason === "restock" ? "restock" : "standing") as GroceryLine["origin"],
      sourceRecipeIds: [],
      estPriceCents: item?.typicalPriceCents ?? null,
      pantryAdjusted: false,
    };
  });

  const all = [
    ...[...lines.values()].filter((l) => l.qty === null || l.qty > 0),
    ...unmatched,
    ...standingLines,
  ];

  // 4. Group by section.
  const sections: Partial<Record<StoreSection, GroceryLine[]>> = {};
  for (const line of all) {
    (sections[line.section] ??= []).push(line);
  }

  // 5. Budget. Total is null if ANY line lacks a price — a partial sum
  // presented as a total would mislead.
  const priced = all.filter((l) => l.estPriceCents !== null);
  const estTotalCents =
    priced.length === all.length && all.length > 0
      ? priced.reduce((sum, l) => sum + (l.estPriceCents ?? 0), 0)
      : null;
  const underBudgetCents =
    input.budgetEnabled && input.budgetCents !== null && estTotalCents !== null
      ? input.budgetCents - estTotalCents
      : null;

  return {
    sections,
    lines: all,
    estTotalCents,
    budget: {
      enabled: input.budgetEnabled,
      budgetCents: input.budgetCents,
      underBudgetCents,
    },
  };
}
