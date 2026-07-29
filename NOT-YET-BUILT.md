# Not yet built

Scope ledger, in the spirit of the source system's "Do not assume these exist" section.
Move items out when they land; do not silently assume them.

## Python service (`service/` — the current product)

Requires a human / live credentials:
- [ ] Live smoke test: `import-recipes` + `run-weekly --dry-run` against a real API key
- [ ] Real store login + cart run (validates the amazon_fresh selector pack against today's site)
- [ ] Gmail app password created; `send-test-email` verified
- [ ] Cron entries installed; `mealplanner serve` running for the web UI

Code not yet written:
- [ ] Pantry management surface (state file exists; no CLI/web editing yet — inventory is still manual YAML)
- [ ] LLM-assisted selector self-healing when all fallbacks miss (report degrades gracefully today)
- [ ] Claude cook-mode notes in the tonight email (deterministic steps only today)
- [ ] Ontology expansion beyond the ~85-item starter set (unknown ingredients fail closed for allergy households)
- [ ] Per-store organic-preference handling at add-to-cart time
- [ ] Windows support (flock in cli.py is POSIX-only)

## Shelved mobile app (TS monorepo)
The Expo/Supabase plan is on ice; `packages/engine` is kept as the reference
implementation for the deterministic core. See git history for its roadmap.
