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

## Setup — three steps, no coding

You need: a Linux or macOS computer that stays on (an old laptop or Raspberry
Pi is perfect), a Gmail account, and Claude access — either a
[Claude subscription](https://claude.com/claude-code) already signed in on the
machine (no per-token cost) or an
[Anthropic API key](https://console.anthropic.com/) (~cents per week).

**1. Install** — open a terminal and paste:

```bash
git clone https://github.com/tjermann/PantryOS.git && cd PantryOS && ./install.sh
```

The installer sets everything up in its own private environment (it never
touches your system's Python) and flows straight into…

**2. Answer the questionnaire.** It asks for everything in plain language:
your Gmail app password ([create one here](https://myaccount.google.com/apppasswords)
— the wizard walks you through it), who eats at your house, any allergies
(tracked per person), your stores, budget, planning day, and the staples you
buy every week. PantryOS ships with a starter recipe library, so there's
nothing else to prepare — you can point it at your own recipe folder later.

**3. Finish the one-time steps** the wizard prints at the end:

```bash
service/.venv/bin/mealplanner import-recipes --user <you>   # structure the recipes (one time)
service/.venv/bin/mealplanner login --user <you> --store <store>  # sign in to your store in a real browser window
service/.venv/bin/mealplanner run-weekly --user <you> --dry-run   # preview your first week
service/.venv/bin/mealplanner install-cron                  # make it automatic, forever
```

From then on it runs itself: the weekly plan lands in your inbox on your
planning day with the cart already loaded, and your family rates dinners from
links in the email. See [`service/README.md`](service/README.md) for
multi-household setup, the web page, and every command.

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
