"""`mealplanner doctor` — checks the whole setup and says what to do next.

Written for someone who has never used a terminal: every failure names the
exact command or click that fixes it.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .config import list_users, load_user_config, user_dir
from .credentials import SERVICE_ROOT, anthropic_key, smtp_credentials

OK, WARN, BAD = "✓", "!", "✗"


def _line(status: str, label: str, detail: str = "") -> str:
    return f"  {status}  {label}" + (f"\n       {detail}" if detail else "")


def run_doctor(check_email: bool = False) -> int:
    print("\nPantryOS checkup\n" + "=" * 40)
    problems = 0

    # --- credentials ---------------------------------------------------
    print("\nCredentials")
    address, password, _ = smtp_credentials()
    if address and password:
        print(_line(OK, f"Email account: {address}"))
        if check_email:
            import smtplib

            from .emailer.sender import smtp_settings

            try:
                s = smtp_settings()
                with smtplib.SMTP_SSL(s.host, s.port, timeout=20) as server:
                    server.login(s.user, s.password)
                print(_line(OK, "Gmail accepted the app password"))
            except Exception as exc:
                problems += 1
                print(_line(BAD, "Gmail rejected the login", str(exc)[:90]))
    else:
        problems += 1
        print(_line(BAD, "No email credentials",
                    "Copy sample_user_info.json to user_info.json and fill in the "
                    '"email" section (see GETTING-STARTED.md, step 3).'))

    users = list_users()
    backends = {u: load_user_config(u).llm_backend for u in users} if users else {}
    if "api" in backends.values() or not users:
        if anthropic_key():
            print(_line(OK, "Anthropic API key found"))
        elif "api" in backends.values():
            problems += 1
            print(_line(BAD, "No Anthropic API key",
                        'Add "anthropic_api_key" to user_info.json, or switch to the '
                        "claude-cli backend (see GETTING-STARTED.md, step 3)."))

    # --- households ----------------------------------------------------
    print("\nHouseholds")
    if not users:
        problems += 1
        print(_line(BAD, "No household set up yet",
                    "Run:  mealplanner setup"))
    for u in users:
        config = load_user_config(u)
        print(_line(OK, f"{u} — {len(config.household.people)} people, "
                        f"{config.household.dinners_per_week} dinners"
                        + (f" + {config.household.lunches_per_week} lunch"
                           if config.household.lunches_per_week else "")))
        if config.llm_backend == "local":
            try:
                import urllib.request

                urllib.request.urlopen(config.local_base_url.rstrip("/") + "/models",
                                       timeout=5)
                print(_line(OK, f"  Local model endpoint reachable "
                                f"({config.local_model})"))
            except Exception:
                problems += 1
                print(_line(BAD, "  Local model endpoint not reachable",
                            f"Nothing answering at {config.local_base_url}. Start it "
                            "(Ollama: `ollama serve`) or fix local_base_url."))
        if config.llm_backend == "claude-cli":
            if shutil.which(config.claude_cli_path):
                print(_line(OK, "  Claude Code found (planning uses your subscription)"))
            else:
                problems += 1
                print(_line(BAD, "  Claude Code not found",
                            f"'{config.claude_cli_path}' isn't installed or isn't on PATH. "
                            "Install from claude.com/claude-code, or set claude_cli_path "
                            "in the config to its full path."))
        # recipes
        parsed = list((user_dir(u) / "parsed").glob("*.json"))
        if parsed:
            print(_line(OK, f"  {len(parsed)} recipes ready to plan"))
        else:
            problems += 1
            print(_line(BAD, "  No recipes imported yet",
                        f"Run:  mealplanner import-recipes --user {u}"))
        # stores
        for store in config.stores:
            profile = user_dir(u) / "browser" / store.id
            if profile.exists():
                print(_line(OK, f"  Signed in to {store.id}"))
            else:
                print(_line(WARN, f"  Not signed in to {store.id} — lists still email, "
                                  "carts won't load",
                            f"Run:  mealplanner login --user {u} --store {store.id}"))
        if not config.stores:
            print(_line(WARN, "  No stores configured — you'll get emailed lists only"))

    # --- automation ----------------------------------------------------
    print("\nAutomation")
    try:
        crontab = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        installed = crontab.stdout.count("pantryos-")
    except Exception:
        installed = 0
    if installed >= 6:
        print(_line(OK, f"Scheduled ({installed} jobs) — runs itself weekly"))
    else:
        problems += 1
        print(_line(BAD, "Not scheduled yet", "Run:  mealplanner install-cron"))

    web_up = False
    try:
        import urllib.request

        for u in users:
            base = (load_user_config(u).web_base_url or "").rstrip("/")
            if base:
                urllib.request.urlopen(base + "/", timeout=5)
                web_up = True
                break
    except Exception:
        web_up = False
    if not users or not any((load_user_config(u).web_base_url or "") for u in users):
        print(_line(WARN, "Family web page not configured (optional)",
                    "Add web_base_url to the config to enable star ratings and the "
                    "grocery review page."))
    elif web_up:
        print(_line(OK, "Family web page is up"))
    else:
        problems += 1
        print(_line(BAD, "Family web page isn't responding",
                    "Run:  mealplanner restart-serve"))

    print("\n" + "=" * 40)
    if problems == 0:
        print("Everything looks good. Your next email arrives on schedule.\n")
    else:
        print(f"{problems} thing(s) need attention — see the lines marked ✗ above.\n")
    return 0 if problems == 0 else 1
