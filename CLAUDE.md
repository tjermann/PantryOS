# PantryOS — self-hosted family meal planning

A cron-driven Python service (`service/`): it plans a week of dinners with an AI,
emails the household a proposal, folds in their feedback, builds the grocery list,
fills the store cart for a human to submit, and learns from ratings and replies.

**If the person asks you to set PantryOS up for them, follow the runbook below.**
Everything else in this file is context for working on the code.

---

## Setup runbook (for a fresh clone)

Work through these in order. Ask for one thing at a time, keep explanations short,
and check your work with `doctor` at the end. **Never invent credentials or guess at
household details — ask.**

1. **Install.** `cd service && python3 -m venv .venv && .venv/bin/pip install -e .`
   then `.venv/bin/playwright install chromium`. (Python 3.11+ required. If `venv`
   fails on Debian/Ubuntu, tell them to run `sudo apt install python3-venv` — do not
   run sudo yourself.)

2. **Credentials → `service/user_info.json`** (gitignored; `chmod 600`). Copy
   `sample_user_info.json` and fill in:
   - `email.address` / `email.app_password` — a **Gmail app password**, not their
     normal password. Walk them through it: 2-Step Verification on, then
     myaccount.google.com/apppasswords → name it PantryOS → 16-letter code. You
     cannot create this for them; ask them to paste it.
   - `anthropic_api_key` — only needed for the `api` backend (see step 4).

3. **Household config.** Either run `.venv/bin/python -m mealplanner setup`
   (interactive questionnaire — they answer, not you), **or** interview them
   conversationally and write `service/users/<name>/config.yaml` yourself. The
   second is usually nicer. Ask about: who eats (and whether kids eat the planned
   dinners), per-person allergies with severity, dinners and make-ahead lunches per
   week, planning day, kitchen equipment they actually own, budget, stores, staples
   they always have, recipient emails. If they'd rather choose from a menu than be
   handed a fixed week, set `dinner_options` / `lunch_options` above
   `dinners_per_week` / `lunches_per_week` — Friday then proposes a shortlist and
   the family page grows a picker. Validate with
   `.venv/bin/python -m mealplanner validate-config --user <name>`.

4. **AI backend** — ask which they want:
   - `claude-cli` — free with a Claude subscription; needs Claude Code installed and
     signed in. Set `claude_cli_path` to the absolute path (`which claude`) so cron
     can find it.
   - `api` — Anthropic API key, a few cents a week.
   - `local` — their own Ollama/LM Studio endpoint; set `local_base_url`/`local_model`.

5. **Recipes.** Add their favorite recipe sites to `recipe_sources` in the config,
   then `.venv/bin/python -m mealplanner discover-recipes --user <name> --total 40`.
   Set `source_policy: exclusive` if they only want those sites. This takes a while —
   run it in the background and keep going.

6. **Store login.** `.venv/bin/python -m mealplanner login --user <name> --store <id>`
   opens a real browser; **they** type the password and 2FA. You never handle store
   credentials. Skippable — without it they get emailed lists instead of filled carts.

7. **Go live.** `install-cron` (or `docker compose up -d`), then
   `restart-serve` for the family web page. Set `web_base_url` in the config to
   `http://<lan-ip>:8321` so email links work.

8. **Verify.** `.venv/bin/python -m mealplanner doctor` — fix anything marked ✗, then
   show them a preview: `run-weekly --user <name> --dry-run --force`.

Ongoing requests you'll get: "add this recipe site", "we don't eat X", "make the
meals quicker". Preferences that are *judgment* go in `users/<name>/state/learnings.md`
(free text, read by the planner every week); preferences that are *rules* go in
`config.yaml` (`avoid_proteins`, `item_substitutions`, equipment, budget).

---

## Hard rules

1. **Allergen logic is code, never the model.** Every proposed plan passes through
   `service/mealplanner/allergen/backstop.py` before anyone sees it. Allergy severity
   is a hard fail; unknown ingredients fail closed. Matching uses the item→allergen
   ontology with negative assertions (coconut milk ≠ dairy) — never substring matching.
2. **Secrets never enter git.** `user_info.json` and `service/users/**` are gitignored
   and stay that way. Store passwords are never collected at all — sign-in happens in
   the user's own browser.
3. **The human submits the order.** Cart automation stops at the cart page, always.
4. **Dietary restrictions are per person**, with handling Clear / Substitute / Split / Skip.
5. **`published_time` and `real_time` never merge.** real_time comes only from measured
   cook sessions.
6. **Recipes are for the household that imported them** — no redistribution, and no
   scraped content ships in the repo. `starter-recipes/` is original content only.

## Commands

Run from `service/` (or prefix with `service/.venv/bin/`):

```
python -m pytest                       # 100+ tests, no network needed
python -m mealplanner doctor           # health check with fixes
python -m mealplanner run-propose --user X --dry-run --force   # preview a proposal
python -m mealplanner run-weekly  --user X --dry-run --force   # preview the full run
python -m mealplanner --help           # everything else
```

Tests are the contract for the deterministic core (allergens, variety, grocery
pipeline). No live API calls in tests — LLM backends are faked.

## Layout

- `service/mealplanner/` — the product.
  - `allergen/`, `planning/`, `grocery/` — deterministic core; no LLM involvement
  - `llm/` — three interchangeable backends (`api`, `claude-cli`, `local`), all
    duck-typed to `messages.parse()`; validation + repair loop makes weak models safe
  - `jobs/` — propose / iterate / weekly / review / restock / tonight
  - `carts/` — Playwright store drivers, YAML selector packs with fallback chains
  - `web/` — the family feedback page (escape all user content: `esc()`/`q()`)
  - `recipes/` — library reader, URL import, site discovery
- `service/users/<name>/` — private per-household data (gitignored)
- `packages/`, `apps/`, `supabase/` — **archived** TypeScript/mobile iteration.
  `packages/engine` is the reference implementation the Python core was ported from.
