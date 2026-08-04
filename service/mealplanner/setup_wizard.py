"""Interactive onboarding questionnaire — a working port of the reference
system's CONFIG-TEMPLATE.md. Runs in the terminal, writes a validated
users/<name>/config.yaml. Non-technical household members give ongoing
feedback through the web UI (`mealplanner serve`); this wizard is for whoever
deploys the service.
"""

from __future__ import annotations

from pathlib import Path

from .allergen.ontology import ALLERGEN_CLASSES
from .config import (
    EQUIPMENT_CHOICES,
    EmailConfig,
    StoreConfig,
    UserConfig,
    save_user_config,
    user_dir,
)
from .schemas.domain import (
    DietaryRestriction,
    Household,
    Person,
    StandingOrderLine,
)


def _ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    answer = input(f"{prompt}{suffix}: ").strip()
    return answer or (default or "")


def _ask_yes_no(prompt: str, default: bool = True) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    answer = input(f"{prompt} {suffix}: ").strip().lower()
    if not answer:
        return default
    return answer.startswith("y")


def _ask_int(prompt: str, default: int, lo: int, hi: int) -> int:
    while True:
        raw = _ask(prompt, str(default))
        try:
            value = int(raw)
            if lo <= value <= hi:
                return value
        except ValueError:
            pass
        print(f"  Enter a number between {lo} and {hi}.")


def _ask_choice(prompt: str, choices: list[str], default: str) -> str:
    print(f"{prompt} ({', '.join(choices)})")
    while True:
        answer = _ask("  choice", default).lower().replace(" ", "_")
        if answer in choices:
            return answer
        print(f"  Pick one of: {', '.join(choices)}")


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")


def _ensure_credentials() -> None:
    """First run on a fresh clone: collect operator credentials interactively
    and write user_info.json — no manual JSON editing."""
    import json

    from .credentials import SERVICE_ROOT, load_user_info

    if load_user_info():
        return
    print("\n--- One-time credentials (stored ONLY on this computer) ---")
    print("PantryOS emails your weekly plan from a Gmail account. It needs an")
    print("'app password' (not your normal password). To create one:")
    print("  1. Turn on 2-step verification for the Gmail account")
    print("  2. Visit https://myaccount.google.com/apppasswords")
    print("  3. Create one named 'PantryOS' and paste the 16-letter code here")
    address = _ask("Gmail address to send from")
    app_password = _ask("Gmail app password")
    print("\nFor the AI planning you can use a Claude subscription (pick the")
    print("'claude-cli' backend in a moment) or an Anthropic API key from")
    print("https://console.anthropic.com (pay-per-use, ~cents per week).")
    api_key = _ask("Anthropic API key (blank if using a Claude subscription)", "") or None

    path = SERVICE_ROOT / "user_info.json"
    path.write_text(json.dumps({
        "anthropic_api_key": api_key,
        "email": {"address": address, "app_password": app_password, "from_name": "PantryOS"},
    }, indent=2))
    path.chmod(0o600)
    load_user_info.cache_clear()
    print(f"Saved {path} (private to this machine; never uploaded anywhere).")


def run_wizard(user: str | None = None, base: Path | None = None) -> Path:
    print("\n=== PantryOS setup ===")
    print("Answers land in a config file you can edit later, or re-run this")
    print("wizard any time with `mealplanner setup --user <name>`.\n")
    _ensure_credentials()

    # --- household basics ---------------------------------------------------
    name = _ask("Household name (used for the users/ folder)", user or "home")
    user_id = _slug(user or name)
    region = _ask_choice(
        "Hemisphere (drives what's in season)", ["northern", "southern"], "northern"
    )
    timezone = _ask("Timezone", "America/New_York")

    # --- people -------------------------------------------------------------
    print("\n--- Who eats? ---")
    print("List everyone. Kids on standing meals (nuggets night) can be excluded")
    print("from dinner planning and handled as standing grocery items instead.")
    people: list[Person] = []
    while True:
        person_name = _ask("Person's name (blank to finish)", "" if people else None)
        if not person_name:
            if people:
                break
            print("  At least one person is required.")
            continue
        is_child = _ask_yes_no(f"  Is {person_name} a child?", False)
        eats = True
        if is_child:
            eats = _ask_yes_no(
                f"  Does {person_name} eat the planned dinners (vs standing kid meals)?",
                False,
            )
        people.append(
            Person(id=_slug(person_name), name=person_name, is_child=is_child,
                   eats_planned_dinners=eats)
        )

    # --- dietary restrictions (per person — this is what enables Split) -----
    print("\n--- Dietary restrictions (per person, not per household) ---")
    print(f"Allergen classes: {', '.join(ALLERGEN_CLASSES)}")
    restrictions: list[DietaryRestriction] = []
    for person in people:
        while _ask_yes_no(f"Add a restriction for {person.name}?", False):
            allergen = _ask_choice(
                "  Allergen class", list(ALLERGEN_CLASSES), "dairy"
            )
            severity = _ask_choice(
                "  Severity — allergy is a hard block; intolerance gets substitutions/"
                "splits; preference is best-effort",
                ["allergy", "intolerance", "preference"],
                "intolerance",
            )
            notes = _ask("  What's still OK? (e.g. 'aged cheeses fine; coconut milk fine')", "")
            restrictions.append(
                DietaryRestriction(
                    person_id=person.id,
                    allergen_class=allergen,
                    severity=severity,  # type: ignore[arg-type]
                    notes=notes or None,
                )
            )

    # --- meal structure ------------------------------------------------------
    print("\n--- Meal structure ---")
    dinners = _ask_int("Dinners to plan per week", 5, 1, 7)
    planning_day = _ask_choice(
        "Planning day (the weekly email lands that morning)",
        ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"],
        "saturday",
    )
    dinner_hour = _ask_int("Usual dinner hour (24h, for 'start by' reminders)", 18, 0, 23)

    # --- equipment -----------------------------------------------------------
    print("\n--- Kitchen equipment (recipes needing gear you lack are skipped) ---")
    equipment = [e for e in EQUIPMENT_CHOICES if _ask_yes_no(f"  {e.replace('_', ' ').title()}?", e == "sheet_pan")]

    # --- budget --------------------------------------------------------------
    print("\n--- Budget ---")
    budget_enabled = _ask_yes_no("Enable a weekly grocery budget?", False)
    budget_cents = None
    if budget_enabled:
        dollars = _ask_int("Weekly budget in dollars", 200, 20, 2000)
        budget_cents = dollars * 100
    organic = _ask_choice(
        "Organic preference", ["none", "produce_only", "everything"], "none"
    )

    # --- stores --------------------------------------------------------------
    print("\n--- Stores ---")
    print("Adapters: amazon_fresh (Amazon Fresh / Whole Foods via amazon.com),")
    print("generic (any store site — search box + add-to-cart heuristics).")
    print("You'll log in once per store with `mealplanner login` (headed browser);")
    print("carts get loaded there, and YOU always review and submit the order.")
    stores: list[StoreConfig] = []
    while _ask_yes_no("Add a store?", not stores):
        store_id = _slug(_ask("  Store name", "amazon-fresh"))
        adapter = _ask_choice("  Adapter", ["amazon_fresh", "generic"], "amazon_fresh")
        stores.append(StoreConfig(id=store_id, adapter=adapter))

    # --- standing orders -----------------------------------------------------
    print("\n--- Standing items (every order: kids' staples, breakfast, snacks) ---")
    standing: list[StandingOrderLine] = []
    while _ask_yes_no("Add a standing item?", False):
        raw = _ask("  Item (e.g. 'chicken nuggets', 'applesauce pouches')")
        why = _ask("  Reason", "standing")
        if raw:
            standing.append(StandingOrderLine(raw=raw, reason=why))

    # --- delivery ------------------------------------------------------------
    print("\n--- Email ---")
    to = [a.strip() for a in _ask("Recipient address(es), comma-separated").split(",") if a.strip()]
    while not to:
        to = [a.strip() for a in _ask("At least one recipient address").split(",") if a.strip()]

    print("\n--- Recipe library ---")
    print("PantryOS ships with a starter library of original recipes; point this")
    print("at your own folder (index.csv + library/ of markdown files) any time.")
    from .credentials import SERVICE_ROOT

    library = _ask(
        "Path to a recipe library",
        str(SERVICE_ROOT / "starter-recipes"),
    )

    print("\n--- How should Claude be called? ---")
    print("api        — Anthropic API key (pay per token; ~cents per week)")
    print("claude-cli — headless Claude Code on this machine's Claude subscription")
    print("             (no per-token cost; requires `claude` installed & signed in)")
    llm_backend = _ask_choice("Backend", ["api", "claude-cli"], "api")

    api_key = None
    if llm_backend == "api":
        print("\n--- Anthropic API key ---")
        print("Leave blank to use the shared key from user_info.json (recommended);")
        print("or enter one here to give this household its own key (stored in this")
        print("user's config with file permissions 600).")
        api_key = _ask("API key (blank = use user_info.json)", "") or None

    web_base = _ask(
        "\nWeb feedback UI base URL (for one-click rating links in emails; blank to skip)",
        "",
    ) or None

    config = UserConfig(
        name=name,
        timezone=timezone,
        email=EmailConfig(to=to),
        llm_backend=llm_backend,  # type: ignore[arg-type]
        anthropic_api_key=api_key,
        recipe_library=library,
        planning_day=planning_day,  # type: ignore[arg-type]
        dinner_hour=dinner_hour,
        household=Household(
            id=user_id,
            name=name,
            region=region,  # type: ignore[arg-type]
            people=people,
            restrictions=restrictions,
            equipment=equipment,
            dinners_per_week=dinners,
            budget_cents_weekly=budget_cents,
            budget_enabled=budget_enabled,
        ),
        stores=stores,
        standing_orders=standing,
        organic_preference=organic,  # type: ignore[arg-type]
        web_base_url=web_base,
    )
    path = save_user_config(user_id, config, base)
    (user_dir(user_id, base) / "state").mkdir(exist_ok=True)
    print(f"\nSaved {path}")
    print(f"Next steps:")
    print(f"  1. mealplanner import-recipes --user {user_id}   (one-time recipe parsing)")
    print(f"  2. mealplanner login --user {user_id} --store <store>   (per store)")
    print(f"  3. mealplanner run-weekly --user {user_id} --dry-run")
    return path
