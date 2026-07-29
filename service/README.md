# Meal Planner (self-hosted)

A cron-driven meal-planning service you run on your own machine. Every week it:

1. **Plans dinners** with Claude (your own Anthropic API key), respecting each
   person's dietary restrictions, seasonality, variety, and your budget —
   every AI-proposed plan is re-verified by deterministic allergen code before
   anything is sent.
2. **Builds the grocery list** (aggregated across recipes, minus your pantry,
   plus standing items, grouped by store section).
3. **Loads your carts** with Playwright on your own logged-in store sessions.
   **It never checks out** — you review substitutions and submit the order.
4. **Emails your household** the menu, list, and "review & submit" links.
   Family members rate dinners and tweak preferences through one-click links
   and a small web page — no terminal needed.

Extra emails: a mid-week restock reminder and a nightly "tonight's dinner"
note with a start-by time (so a 4-hour marinade is never discovered at 6pm).

## Quickstart

```bash
git clone <this repo> && cd meal-planner/service
python3.12 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/playwright install chromium         # for cart loading

# Credentials (never stored in the repo):
export ANTHROPIC_API_KEY=sk-ant-...           # or enter per-user during setup
export MEALPLANNER_SMTP_USER=you@gmail.com    # Gmail address that sends mail
export MEALPLANNER_SMTP_PASS=xxxx-xxxx-xxxx   # a Gmail App Password

.venv/bin/python -m mealplanner setup                     # the questionnaire
.venv/bin/python -m mealplanner import-recipes --user you # one-time recipe parsing
.venv/bin/python -m mealplanner login --user you --store amazon-fresh
.venv/bin/python -m mealplanner run-weekly --user you --dry-run   # preview
.venv/bin/python -m mealplanner run-weekly --user you --force     # real run
```

Multiple households: run `setup` once per user; every command takes `--user`
or `--all-users`. Each user has their own config, API key, stores, state, and
browser sessions under `users/<name>/` (gitignored).

## Cron

```cron
# Weekly plans go out on each user's configured planning day (job exits fast otherwise)
15 6 * * *  cd /path/to/meal-planner/service && .venv/bin/python -m mealplanner run-weekly  --all-users >> var/log/weekly.log 2>&1
0 17 * * 3  cd /path/to/meal-planner/service && .venv/bin/python -m mealplanner run-restock --all-users >> var/log/restock.log 2>&1
0 15 * * *  cd /path/to/meal-planner/service && .venv/bin/python -m mealplanner run-tonight --all-users >> var/log/tonight.log 2>&1
```

For the household web page (ratings + preferences, linked from every email),
keep `mealplanner serve` running (e.g. a systemd user service) and set
`web_base_url` in the user's config to `http://<your-box>:8321`.

## Recipe library

Point `recipe_library` at a folder containing `index.csv`
(`recipe,season,protein,...,file` — see the reference format) and a `library/`
of markdown recipes. `import-recipes` parses each file once with Claude into
structured ingredients/steps (cached, re-parsed only when a file changes).
Recipes whose ingredients can't be verified against the allergen ontology are
excluded for allergy households — the system fails closed, never open.

## Safety & privacy properties

- **Allergen checks are code, not AI.** Claude proposes; a deterministic
  backstop validates every entry against an ingredient ontology (which knows
  coconut milk is not dairy). Allergy conflicts are hard failures.
- **No store passwords, ever.** `login` opens a real browser window; you type
  credentials into the store's own site. Only the browser profile persists.
- **No automatic checkout.** Carts stop at the cart page, always.
- **Keys stay local.** Your Anthropic key lives in your environment or your
  chmod-600 config; SMTP credentials live in the environment only.

## Development

```bash
.venv/bin/python -m pytest          # 60 tests, no network
.venv/bin/python -m pytest -m live  # optional: one real planning call
```

The deterministic core (`mealplanner/allergen`, `planning`, `grocery`) is a
faithful port of the TypeScript reference implementation in
`../packages/engine` — its test suite is the contract.
