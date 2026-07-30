# PantryOS 🍳

**Self-hosted, AI-powered meal planning for your household.** Claude plans your
week of dinners around each person's dietary needs, the season, your budget, and
what wastes least; PantryOS builds the grocery list, pre-loads your store carts,
and emails everyone — you just review the cart and hit "place order."

Born from a real family's hand-rolled meal-planning system, generalized so
anyone can clone this repo, plug in their own credentials, and run it on a
spare machine with cron.

## What it does

Every week, per household:

1. **Plans dinners with Claude** (your own Anthropic API key) — seasonality,
   protein/cuisine variety, effort spread across the week, and clustering of
   perishable herbs so nothing gets composted. Every AI-proposed plan is
   re-verified by **deterministic allergen code** before it reaches anyone:
   restrictions are tracked *per person* (allergy / intolerance / preference),
   and the validator knows coconut milk isn't dairy. Unverifiable ingredients
   fail closed.
2. **Builds the grocery list** — quantities aggregated across recipes, pantry
   stock subtracted, standing items (kid staples, restocks) added, grouped by
   store section, checked against your budget.
3. **Loads your carts** with a headless browser on your own logged-in store
   sessions. **It never checks out** — the email links you straight to the
   cart to review substitutions and submit.
4. **Emails the household**: the menu (with per-person handling like "pull
   Sam's portion before the cream goes in"), prep-ahead flags ("start the
   brine by 2pm"), the list, and cart status per store.

Plus a mid-week restock reminder, a nightly "Tonight: …" email with a
computed start-by time, and a **household web page** where non-technical
family members rate dinners one-click, leave notes, mark "never again," and
tweak budget/preferences — no terminal required.

Feedback loops all the way down: ratings drive a keeper/probation/cut
lifecycle, real cook times get recorded next to (never over) published times,
order history and "that substitution worked" notes feed future planning.

## Repo layout

| Path | What it is |
|---|---|
| `service/` | **The product** — the Python package (`mealplanner`), CLI, tests. Start here. |
| `packages/engine/` | TypeScript reference implementation of the deterministic core (allergen backstop, variety rules, grocery pipeline). The Python core is a 1:1 port; the two test suites are the contract. |
| `apps/mobile/`, `supabase/`, `packages/*` | A shelved mobile-app iteration kept for reference. |

## Setup

Requirements: Python 3.11+, a Linux/macOS box that stays on (a Raspberry Pi
works), a Gmail account with an
[app password](https://myaccount.google.com/apppasswords), and Claude access —
either an [Anthropic API key](https://console.anthropic.com/) (metered; ~cents
per week) **or** a Claude subscription with
[Claude Code](https://claude.com/claude-code) signed in on the box (the
`claude-cli` backend plans through your plan's allowance, no per-token cost).

```bash
git clone https://github.com/tjermann/PantryOS.git
cd PantryOS/service
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/playwright install chromium

# 1. Credentials — one gitignored file:
cp sample_user_info.json user_info.json
$EDITOR user_info.json          # API key + Gmail address/app password
chmod 600 user_info.json

# 2. Your household — interactive questionnaire (people, allergies, stores,
#    budget, planning day, standing items, email recipients):
.venv/bin/python -m mealplanner setup

# 3. Recipes — point at a library (index.csv + markdown files; a one-time
#    Claude parse structures them, cached until a file changes):
.venv/bin/python -m mealplanner import-recipes --user <you>

# 4. Store login — a real browser window opens; you log in (2FA and all).
#    PantryOS never sees or stores your store password:
.venv/bin/python -m mealplanner login --user <you> --store <store-id>

# 5. Trial run:
.venv/bin/python -m mealplanner send-test-email --user <you>
.venv/bin/python -m mealplanner run-weekly --user <you> --dry-run
.venv/bin/python -m mealplanner run-weekly --user <you> --force
```

Then put it on cron and start the family web page — see
[`service/README.md`](service/README.md) for the cron lines, the web UI
(`mealplanner serve`), multi-household setup, and every CLI command
(`rate`, `mark`, `review-orders`, …).

## Principles

- **Human always submits the order.** Substitutions need human judgment; the
  review step is a feature, not a limitation.
- **Allergen safety is code, never AI.** Claude proposes; a deterministic
  ontology-backed validator has the last word.
- **Secrets stay home.** `user_info.json` and everything under
  `service/users/` (configs, state, browser sessions) are gitignored. Store
  passwords are never collected at all.
- **The second cook beats the first.** Everything you rate, note, and adjust
  feeds the next week's plan.

## Development

```bash
cd service && .venv/bin/python -m pytest    # 60+ tests, no network needed
```

Built with [Claude Code](https://claude.com/claude-code).
