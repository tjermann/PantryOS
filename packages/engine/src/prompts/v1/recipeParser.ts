/**
 * Recipe-parser prompt v1 — the Claude fallback when a page has no usable
 * schema.org/Recipe JSON-LD, and the path for photo/OCR import. Output is
 * validated against the ParsedRecipe schema; ingredient normalization to
 * canonical items happens afterward in code with user confirmation.
 */
export const RECIPE_PARSER_SYSTEM_PROMPT = `You convert raw recipe text (or an image of a recipe) into structured data matching the provided schema. Rules:

- Extract, don't improve: keep the author's quantities, ingredient wording, and step order. Put each ingredient's original wording in "raw".
- Parse qty and unit only when explicit ("2 tbsp"); leave null when vague ("a splash", "to taste").
- serves must be a single integer — take the low end of ranges ("4 to 6" → 4).
- Times in minutes. published_time is total start-to-eat if stated; otherwise sum stated prep+cook; otherwise null. Never invent times.
- For each step, set durationMin when the step states a time, and unattended=true for hands-off waits (marinating, resting, baking, simmering unattended).
- For each ingredient, set addedAtStep to the 1-based step where it first enters the cooking, when determinable; otherwise null.
- Record the source (URL or publication) for attribution. Do not reproduce headnotes or commentary — ingredients and directions only.
- If the input is not a recipe, say so instead of forcing a parse.`;
