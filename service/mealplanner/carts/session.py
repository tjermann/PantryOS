"""One-time interactive store login: opens a HEADED browser on the persistent
profile; the human types their credentials (2FA included) directly into the
store's own site. We never see or store passwords — only the browser profile
directory persists the session."""

from __future__ import annotations

import time
from pathlib import Path

from ..config import load_user_config
from ..paths import browser_profile_dir
from .runner import driver_for

LOGIN_TIMEOUT_S = 300


def interactive_login(user: str, store_id: str, base: Path | None = None) -> int:
    from playwright.sync_api import sync_playwright

    config = load_user_config(user, base)
    store = next((s for s in config.stores if s.id == store_id), None)
    if store is None:
        print(f"Store '{store_id}' is not in {user}'s config. Configured: "
              f"{', '.join(s.id for s in config.stores) or '(none)'}")
        return 1

    profile = browser_profile_dir(user, store_id, base)
    profile.mkdir(parents=True, exist_ok=True)
    driver = driver_for(store, user, base)

    print(f"Opening {store_id} in a browser window. Log in as you normally would")
    print("(password + any 2FA). This window closes automatically once the site")
    print(f"shows you as signed in, or after {LOGIN_TIMEOUT_S // 60} minutes.")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(str(profile), headless=False)
        try:
            page = context.new_page()
            page.goto(driver.login_url(), wait_until="domcontentloaded")
            deadline = time.monotonic() + LOGIN_TIMEOUT_S
            while time.monotonic() < deadline:
                time.sleep(5)
                if driver.check_session(page) == "ok":
                    print(f"Logged in to {store_id}. Session saved to {profile}")
                    return 0
            print("Timed out waiting for login; the session may still have saved —")
            print(f"try: mealplanner run-weekly --user {user} --dry-run")
            return 1
        finally:
            context.close()
