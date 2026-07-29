import type { CanonicalItem } from "../schemas/domain.js";

export const ALLERGEN_CLASSES = [
  "dairy",
  "gluten",
  "peanut",
  "tree_nut",
  "shellfish",
  "fish",
  "egg",
  "soy",
  "sesame",
] as const;
export type AllergenClass = (typeof ALLERGEN_CLASSES)[number];

/**
 * Membership is decided ONLY by the item's explicit allergen list.
 * There is deliberately no name/substring matching anywhere in this module:
 * "coconut milk" must not match dairy, "cream of tartar" must not match dairy,
 * "water chestnut" must not match tree_nut, "buckwheat" must not match gluten.
 *
 * An item unknown to the ontology returns "unknown", which callers must treat
 * as blocking for allergy-severity restrictions (fail closed, not open).
 */
export type MembershipResult = "member" | "non_member" | "unknown";

export function itemInAllergenClass(
  item: CanonicalItem | undefined,
  allergenClass: string,
): MembershipResult {
  if (!item) return "unknown";
  if (item.allergens.includes(allergenClass)) return "member";
  // Negative assertions exist for documentation/regression purposes; absence
  // from `allergens` is already a non-membership decision for known items.
  return "non_member";
}

export function lookupItem(
  items: ReadonlyMap<string, CanonicalItem>,
  id: string | null,
): CanonicalItem | undefined {
  return id ? items.get(id) : undefined;
}
