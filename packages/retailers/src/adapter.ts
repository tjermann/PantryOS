import type { GroceryLine } from "@meal-planner/engine";

/**
 * Every retailer integration implements this interface. Hard rules:
 *  - Retailer passwords are NEVER collected or stored, anywhere.
 *  - Checkout ALWAYS happens in the retailer's own app/site — the human
 *    reviews substitutions and pays there. That review step is a feature.
 *  - Capabilities can be degraded remotely (config flag) without an app
 *    release, e.g. when a deep-link format breaks.
 */
export type Capability = "api-cart" | "deep-link" | "export-only";

export interface MatchResult {
  line: GroceryLine;
  /** Retailer product id, when the adapter can search products. */
  productId: string | null;
  productName: string | null;
  priceCents: number | null;
  confidence: "high" | "medium" | "low" | "unmatched";
}

export interface HandoffResult {
  /** Deep link the app opens (Instacart list, Walmart cart, retailer app). */
  url: string | null;
  /** True when items were pushed into the user's real cart (Kroger only). */
  cartAdded: boolean;
  /** Lines the adapter could not carry over — must be shown to the user. */
  unmatched: GroceryLine[];
}

export interface RetailerAdapter {
  id: string;
  displayName: string;
  capability: Capability;
  /** Honest availability for the user's region/store; export-only never fails. */
  isAvailable(region: string | null): Promise<boolean>;
  /** Optional product matching with prices (api-capable retailers). */
  matchItems?(lines: GroceryLine[]): Promise<MatchResult[]>;
  buildHandoff(lines: GroceryLine[]): Promise<HandoffResult>;
}
