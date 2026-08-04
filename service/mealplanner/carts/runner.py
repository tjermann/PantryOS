"""Cart orchestration: persistent browser contexts per user+store, one store
at a time, hard stop at the cart page. The weekly email always sends whether
or not carts load — cart failures degrade to list-only."""

from __future__ import annotations

from pathlib import Path

from ..config import StoreConfig, UserConfig, user_dir
from ..grocery.pipeline import GroceryLine
from ..paths import browser_profile_dir
from .base import CartReport
from .selector_driver import SelectorDriver, load_selector_pack

MAX_CONSECUTIVE_FAILURES = 3


def driver_for(store: StoreConfig, user: str, base: Path | None = None) -> SelectorDriver:
    pack_name = "amazon_fresh" if store.adapter == "amazon_fresh" else store.id
    overrides = user_dir(user, base) / "selectors"
    return SelectorDriver(store.id, load_selector_pack(pack_name, overrides))


def store_lines(store: StoreConfig, lines: list[GroceryLine]) -> list[GroceryLine]:
    """Optional section routing: only this store's sections, else everything."""
    if not store.sections:
        return lines
    wanted = set(store.sections)
    return [l for l in lines if l.section in wanted]


def load_cart_for_store(
    user: str,
    store: StoreConfig,
    lines: list[GroceryLine],
    base: Path | None = None,
) -> CartReport:
    from playwright.sync_api import sync_playwright

    profile = browser_profile_dir(user, store.id, base)
    if not profile.exists():
        return CartReport(
            store_id=store.id,
            session="expired",
            error=f"no saved login — run: mealplanner login --user {user} --store {store.id}",
        )

    report = CartReport(store_id=store.id, session="unknown")
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(str(profile), headless=True)
        try:
            page = context.new_page()
            page.set_default_timeout(10000)  # bound worst-case per action
            driver = driver_for(store, user, base)
            report.session = driver.check_session(page)
            if report.session == "expired":
                report.error = (
                    f"session expired — run: mealplanner login --user {user} --store {store.id}"
                )
                return report
            hard_failures = 0
            for line in store_lines(store, lines):
                try:
                    result = driver.search_and_add(page, line)
                except Exception as exc:  # keep going; a broken selector ≠ a broken run
                    from .base import LineResult

                    result = LineResult(line.display_name, "not_found", note=str(exc)[:120])
                report.results.append(result)
                # Only site-broken signals (search box gone, zero results, page
                # errors) count toward the abort — ordinary match misses are
                # normal and just land on the add-by-hand list.
                site_broken = result.status == "not_found" and (
                    result.note is None
                    or "search box" in (result.note or "")
                    or "no results" in (result.note or "")
                )
                hard_failures = hard_failures + 1 if site_broken else 0
                if hard_failures >= MAX_CONSECUTIVE_FAILURES:
                    report.error = "stopped after repeated failures (site change? run login again)"
                    break
            report.cart_url = driver.cart_url()
        finally:
            context.close()
    return report


def load_all_carts(
    user: str,
    config: UserConfig,
    lines: list[GroceryLine],
    base: Path | None = None,
    dry_run: bool = False,
) -> list[dict]:
    """Returns template-ready cart dicts for the weekly email."""
    carts: list[dict] = []
    for store in config.stores:
        if not store.enabled:
            continue
        if dry_run:
            carts.append(
                {
                    "store": store.id,
                    "summary": f"dry run — would load {len(store_lines(store, lines))} items",
                    "url": None,
                    "not_found": [],
                    "action_needed": None,
                }
            )
            continue
        report = load_cart_for_store(user, store, lines, base)
        carts.append(
            {
                "store": store.id,
                "summary": report.summary(),
                "url": report.cart_url if report.session == "ok" else None,
                "not_found": report.not_found,
                "action_needed": report.error,
            }
        )
    return carts
