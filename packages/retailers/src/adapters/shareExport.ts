import type { GroceryLine, StoreSection } from "@meal-planner/engine";
import type { HandoffResult, RetailerAdapter } from "../adapter.js";

const SECTION_ORDER: StoreSection[] = [
  "produce",
  "meat_seafood",
  "dairy",
  "bakery",
  "frozen",
  "pantry",
  "other",
];

const SECTION_LABELS: Record<StoreSection, string> = {
  produce: "Produce",
  meat_seafood: "Meat & Seafood",
  dairy: "Dairy",
  bakery: "Bakery",
  frozen: "Frozen",
  pantry: "Pantry",
  other: "Other",
};

function formatQty(qty: number | null, unit: string | null): string {
  if (qty === null) return "";
  const rounded = Number.isInteger(qty) ? qty.toString() : qty.toFixed(2).replace(/\.?0+$/, "");
  const u = unit && unit !== "each" ? ` ${unit}` : "";
  return ` — ${rounded}${u}`;
}

/**
 * The universal fallback: a section-grouped checklist any app accepts via the
 * share sheet (notes, messages, Walmart/Target/Amazon search-by-hand).
 */
export function formatShareList(lines: GroceryLine[]): string {
  const bySection = new Map<StoreSection, GroceryLine[]>();
  for (const line of lines) {
    const list = bySection.get(line.section) ?? [];
    list.push(line);
    bySection.set(line.section, list);
  }
  const blocks: string[] = [];
  for (const section of SECTION_ORDER) {
    const sectionLines = bySection.get(section);
    if (!sectionLines?.length) continue;
    blocks.push(
      `${SECTION_LABELS[section]}\n` +
        sectionLines
          .map((l) => `☐ ${l.displayName}${formatQty(l.qty, l.unit)}`)
          .join("\n"),
    );
  }
  return blocks.join("\n\n");
}

export const shareExportAdapter: RetailerAdapter = {
  id: "share-export",
  displayName: "Share list (any store)",
  capability: "export-only",
  isAvailable: () => Promise.resolve(true),
  buildHandoff(lines): Promise<HandoffResult> {
    // The app hands formatShareList(lines) to the native share sheet.
    return Promise.resolve({ url: null, cartAdded: false, unmatched: [] });
  },
};
