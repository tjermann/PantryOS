/**
 * Unit normalization + conversion. Volume↔mass conversions require an
 * item-specific density and are only attempted when one is known — otherwise
 * quantities stay in their original unit and are listed as separate lines.
 */
export type Unit = string;

const UNIT_ALIASES: Record<string, string> = {
  tablespoon: "tbsp", tablespoons: "tbsp", tbs: "tbsp", tbsp: "tbsp",
  teaspoon: "tsp", teaspoons: "tsp", tsp: "tsp",
  cup: "cup", cups: "cup",
  ounce: "oz", ounces: "oz", oz: "oz",
  pound: "lb", pounds: "lb", lbs: "lb", lb: "lb",
  gram: "g", grams: "g", g: "g",
  kilogram: "kg", kilograms: "kg", kg: "kg",
  milliliter: "ml", milliliters: "ml", ml: "ml",
  liter: "l", liters: "l", l: "l",
  pint: "pint", pints: "pint",
  quart: "quart", quarts: "quart",
  clove: "clove", cloves: "clove",
  bunch: "bunch", bunches: "bunch",
  can: "can", cans: "can",
  each: "each", count: "each", piece: "each", pieces: "each",
};

export function normalizeUnit(unit: string | null): string {
  if (!unit) return "each";
  return UNIT_ALIASES[unit.trim().toLowerCase()] ?? unit.trim().toLowerCase();
}

/** Conversion factors to a base unit per dimension. */
const VOLUME_TO_ML: Record<string, number> = {
  tsp: 4.929, tbsp: 14.787, cup: 236.588, pint: 473.176, quart: 946.353, ml: 1, l: 1000,
};
const MASS_TO_G: Record<string, number> = { oz: 28.3495, lb: 453.592, g: 1, kg: 1000 };

export type Dimension = "volume" | "mass" | "count";

export function dimensionOf(unit: string): Dimension {
  const u = normalizeUnit(unit);
  if (u in VOLUME_TO_ML) return "volume";
  if (u in MASS_TO_G) return "mass";
  return "count";
}

/**
 * Convert qty between units of the same dimension. Returns null when the
 * conversion is not possible (cross-dimension without density, or unknown
 * count units that don't match).
 */
export function convert(qty: number, from: string, to: string): number | null {
  const f = normalizeUnit(from);
  const t = normalizeUnit(to);
  if (f === t) return qty;
  if (f in VOLUME_TO_ML && t in VOLUME_TO_ML)
    return (qty * VOLUME_TO_ML[f]!) / VOLUME_TO_ML[t]!;
  if (f in MASS_TO_G && t in MASS_TO_G) return (qty * MASS_TO_G[f]!) / MASS_TO_G[t]!;
  return null;
}
