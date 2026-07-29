"""Selector-pack-driven store driver: search each grocery line, score results
by token overlap, add the best plausible match. All selectors come from YAML
packs with ordered fallback chains, so selector rot is a data edit."""

from __future__ import annotations

import random
import re
import time
from importlib import resources
from pathlib import Path

import yaml

from ..grocery.pipeline import GroceryLine
from .base import LineResult, SessionStatus, StoreDriver

_STOPWORDS = {"fresh", "organic", "large", "small", "whole", "the", "a", "of", "and"}


def load_selector_pack(name: str, user_override_dir: Path | None = None) -> dict:
    """User-local pack (users/<u>/selectors/<name>.yaml) wins over the packaged one."""
    if user_override_dir is not None:
        override = user_override_dir / f"{name}.yaml"
        if override.exists():
            return yaml.safe_load(override.read_text())
    packed = resources.files("mealplanner.carts").joinpath(f"selectors/{name}.yaml")
    try:
        return yaml.safe_load(packed.read_text())
    except FileNotFoundError:
        return yaml.safe_load(
            resources.files("mealplanner.carts").joinpath("selectors/generic.yaml").read_text()
        )


def _tokens(text: str) -> set[str]:
    return {
        t for t in re.findall(r"[a-z]+", text.lower()) if len(t) > 2 and t not in _STOPWORDS
    }


def score_match(query: str, product_title: str) -> float:
    """Token-overlap score in [0, 1]: how much of the query the product covers."""
    q = _tokens(query)
    if not q:
        return 0.0
    return len(q & _tokens(product_title)) / len(q)


def human_pause() -> None:
    time.sleep(random.uniform(0.8, 2.0))


class SelectorDriver(StoreDriver):
    MATCH_THRESHOLD = 0.5
    RESULTS_TO_CONSIDER = 4

    def __init__(self, store_id: str, pack: dict):
        self.id = store_id
        self.pack = pack

    def home_url(self) -> str:
        return self.pack["home_url"]

    def login_url(self) -> str:
        return self.pack["login_url"] or self.pack["home_url"]

    def cart_url(self) -> str:
        return self.pack["cart_url"]

    def _first_visible(self, page, slot: str, timeout_ms: int = 4000):
        for selector in self.pack.get(slot, []):
            try:
                locator = page.locator(selector).first
                locator.wait_for(state="visible", timeout=timeout_ms)
                return locator
            except Exception:
                continue
        return None

    def check_session(self, page) -> SessionStatus:
        try:
            page.goto(self.home_url(), wait_until="domcontentloaded", timeout=30000)
        except Exception:
            return "unknown"
        if self._first_visible(page, "signin_marker", timeout_ms=2500) is not None:
            return "expired"
        if self._first_visible(page, "account_marker", timeout_ms=2500) is not None:
            return "ok"
        return "unknown"

    def search_and_add(self, page, line: GroceryLine) -> LineResult:
        query = re.sub(r"\(.*?\)", "", line.display_name).strip()
        search = self._first_visible(page, "search_input")
        if search is None:
            return LineResult(line.display_name, "not_found", note="search box not found")
        search.click()
        search.fill(query)
        search.press("Enter")
        human_pause()

        cards = None
        for selector in self.pack.get("result_card", []):
            locator = page.locator(selector)
            try:
                locator.first.wait_for(state="visible", timeout=6000)
                cards = locator
                break
            except Exception:
                continue
        if cards is None:
            return LineResult(line.display_name, "not_found", note="no results")

        best_title, best_score, best_card = None, 0.0, None
        for i in range(min(self.RESULTS_TO_CONSIDER, cards.count())):
            card = cards.nth(i)
            title = None
            for tsel in self.pack.get("result_title", []):
                try:
                    title = card.locator(tsel).first.inner_text(timeout=1500).strip()
                    if title:
                        break
                except Exception:
                    continue
            if not title:
                continue
            s = score_match(query, title)
            if s > best_score:
                best_title, best_score, best_card = title, s, card
        if best_card is None or best_score < self.MATCH_THRESHOLD:
            return LineResult(line.display_name, "not_found",
                              note=f"best match too weak ({best_title!r})" if best_title else None)

        added = False
        for bsel in self.pack.get("add_button", []):
            try:
                best_card.locator(bsel).first.click(timeout=3000)
                added = True
                break
            except Exception:
                continue
        if not added:
            return LineResult(line.display_name, "not_found", note="add button not found",
                              product_title=best_title)
        human_pause()
        exact = score_match(best_title or "", query) >= 0.99 and best_score >= 0.99
        return LineResult(
            line.display_name,
            "added" if best_score >= 0.75 or exact else "substituted",
            product_title=best_title,
        )
