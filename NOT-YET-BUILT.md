# Not yet built

Scope ledger, in the spirit of the source system's "Do not assume these exist" section.
Move items out when they land; do not silently assume them.

## Requires human action (blocking later phases)
- [ ] Instacart Developer Platform application (apply ASAP — approval lead time)
- [ ] Kroger developer account + app registration (cart + products scopes)
- [ ] Walmart affiliate / Impact program application
- [ ] Apple Developer account + Google Play Console account; reserve app name
- [ ] Supabase project creation (dev + prod)

## Phase 1 remainder
- [ ] Full canonical_items dataset (~400–600 items) — schema + starter set exist
- [ ] Recipe URL import parser (JSON-LD + Claude fallback) + 98-recipe golden corpus tests
- [ ] Local SQLite schema + sync layer
- [ ] Supabase generated types in packages/db

## Phase 2+
- [ ] All mobile screens beyond placeholder tabs
- [ ] Auth + onboarding flows
- [ ] AI planning call + validate/repair loop wiring (engine pieces exist; orchestration untested against live API)
- [ ] Cook mode, ratings, pantry UI
- [ ] Instacart/Kroger/Walmart adapters (interface + share-export only today)
- [ ] Notifications, budget steering UI, learnings loop
- [ ] Seed recipe catalog (~75 recipes)
- [ ] Edge Functions (import, OAuth exchange, instacart-link, notify, delete-account)
