# Meal Planner — AI-assisted family meal planning & grocery ordering

Cross-platform app (Expo/React Native + TypeScript, Supabase backend) generalizing a
prompt-driven family meal-planning system. Users bring their own Anthropic API key for
AI planning; the app is fully functional without one (manual mode).

## Layout

- `apps/mobile` — Expo app (expo-router). Screens only; domain logic lives in packages.
- `packages/engine` — **pure TypeScript, zero React Native imports.** Deterministic core:
  allergen backstop, candidate filtering, variety scoring, grocery pipeline, validators,
  versioned prompts (`src/prompts/v1/`), zod schemas. Must run in plain Node.
- `packages/retailers` — `RetailerAdapter` interface + per-retailer adapters
  (share-export, instacart, kroger, walmart). Checkout always happens in the retailer's app.
- `packages/db` — Supabase generated types + sync protocol types.
- `packages/ui` — shared components.
- `supabase/` — SQL migrations (schema + RLS), Edge Functions, seed data.
- `content/` — seed-recipe authoring pipeline. **Licensing rule: no scraped content, ever.**

## Hard rules

1. **Allergen logic is code-only, never LLM.** Every Claude-proposed plan passes through
   `packages/engine/src/allergen/backstop.ts` before display/save. Allergy severity = hard
   fail. Matching is via the item→allergen ontology (with negative assertions like
   coconut milk ≠ dairy) — never substring matching.
2. **User's Anthropic API key**: device secure storage only (expo-secure-store). Never
   synced, never logged, never sent to our backend. Retailer passwords: never collected.
3. **`published_time` and `real_time` are never merged.** real_time comes from cook-session
   timestamps only.
4. Dietary restrictions are **per person**, with handling Clear / Substitute / Split / Skip.
5. Prompts are versioned files in git; saved plans record `prompt_version` + `model`.

## Commands

- `pnpm install` at root (pnpm workspaces + turbo)
- `pnpm test` — vitest across packages (engine tests are the contract; no live API in CI)
- `pnpm typecheck`
- Engine only: `pnpm --filter @meal-planner/engine test`

## Source material

The original prompt-based system lives at `../Claude-Meals/` (read-only reference).
Its `1-engine/SYSTEM.md` is the source of prompt v1; its 98-recipe library is the import
parser's golden corpus — that content is paywalled ATK/NYT and must never ship in-app.
