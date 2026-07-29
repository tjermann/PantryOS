import type { RetailerAdapter } from "../adapter.js";

/**
 * Phase-3 adapters, stubbed with honest capabilities. Each throws until its
 * integration lands; the registry filters on `implemented`.
 *
 * - Instacart: Developer Platform API → shoppable-list deep link. Covers
 *   Costco, Safeway/Albertsons, Publix, Wegmans, Aldi, and Target in some
 *   regions. Requires an approved developer application (server-side key,
 *   link created in an Edge Function).
 * - Kroger: public API with OAuth; the only true add-to-cart integration and
 *   the best source of real store prices. Client secret lives server-side.
 * - Walmart: affiliate add-to-cart deep links only; no official cart API.
 *   Ships behind a beta flag, degrades to export.
 * - Amazon Fresh / Whole Foods: no reliable path — export-only, said plainly
 *   in the UI.
 */
export interface StubbedAdapter extends Omit<RetailerAdapter, "buildHandoff"> {
  implemented: false;
  plannedPhase: 3;
}

export const instacartStub: StubbedAdapter = {
  id: "instacart",
  displayName: "Instacart",
  capability: "deep-link",
  implemented: false,
  plannedPhase: 3,
  isAvailable: () => Promise.resolve(false),
};

export const krogerStub: StubbedAdapter = {
  id: "kroger",
  displayName: "Kroger (Ralphs, Fred Meyer, King Soopers…)",
  capability: "api-cart",
  implemented: false,
  plannedPhase: 3,
  isAvailable: () => Promise.resolve(false),
};

export const walmartStub: StubbedAdapter = {
  id: "walmart",
  displayName: "Walmart",
  capability: "deep-link",
  implemented: false,
  plannedPhase: 3,
  isAvailable: () => Promise.resolve(false),
};
