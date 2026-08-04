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

_UNIT_WORDS = (
    r"cups?|tbsp|tablespoons?|tsp|teaspoons?|lbs?|pounds?|oz|ounces?|grams?|kg|"
    r"cloves?|bunch(?:es)?|cans?|packages?|pk|pieces?|inch(?:es)?|slices?|sprigs?|heads?"
)
# Lines that aren't purchasable products at all.
_UNBUYABLE = re.compile(r"reserved|pasta water|tap water|to taste", re.IGNORECASE)


def clean_query(display_name: str) -> str:
    """Reduce a recipe-phrased line to a searchable product name:
    '1 1/2 lb extra-large shrimp (21-25), peeled and deveined' -> shrimp core."""
    q = re.sub(r"\(.*?\)", " ", display_name)
    q = q.split(",")[0]  # trailing prep clauses: ', chopped', ', skin-on'
    q = re.sub(r"[½⅓¼⅔¾⅛⅜⅝⅞]", " ", q)
    q = re.sub(r"\b\d+(?:[\s/.\-]\d+)*\b", " ", q)  # 4, 1/2, 12-14, 1.5
    q = re.sub(rf"\b(?:{_UNIT_WORDS})\b", " ", q, flags=re.IGNORECASE)
    q = re.sub(r"\s+", " ", q).strip(" -–")
    return q or display_name.strip()


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


def _singular(token: str) -> str:
    """Crude plural folding so 'bananas' matches 'Banana' and 'thighs' 'Thigh'."""
    if len(token) > 3 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 4 and token.endswith("oes"):
        return token[:-2]  # tomatoes -> tomato, potatoes -> potato
    if len(token) > 3 and token.endswith("es") and token[-3] in "hsxz":
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _tokens(text: str) -> set[str]:
    return {
        _singular(t)
        for t in re.findall(r"[a-z]+", text.lower())
        if len(t) > 2 and t not in _STOPWORDS
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
        if _UNBUYABLE.search(line.display_name):
            return LineResult(line.display_name, "skipped", note="not a purchasable item")
        query = clean_query(line.display_name)
        search_url = self.pack.get("search_url")
        if search_url:
            # Direct search URL (e.g. Amazon's i=wholefoods index): keeps the
            # store context and sidesteps overlay/search-box issues entirely.
            from urllib.parse import quote_plus

            try:
                page.goto(search_url.format(query=quote_plus(query)),
                          wait_until="domcontentloaded", timeout=20000)
            except Exception as exc:
                return LineResult(line.display_name, "not_found",
                                  note=f"search box not found ({str(exc)[:60]})")
        else:
            # Fresh page per item: add-to-cart overlays from the previous item
            # otherwise cover the search box and block every later click.
            try:
                page.goto(self.home_url(), wait_until="domcontentloaded", timeout=20000)
            except Exception:
                pass  # search box check below is the real gate
            search = self._first_visible(page, "search_input")
            if search is None:
                return LineResult(line.display_name, "not_found", note="search box not found")
            try:
                search.click(timeout=8000)
                search.fill(query)
                search.press("Enter")
            except Exception as exc:
                return LineResult(line.display_name, "not_found",
                                  note=f"search box not found (blocked: {str(exc)[:60]})")
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

        scored = []
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
            if title:
                scored.append((score_match(query, title), title, card))
        scored.sort(key=lambda x: x[0], reverse=True)
        eligible = [s for s in scored if s[0] >= self.MATCH_THRESHOLD]
        if not eligible:
            best = scored[0][1] if scored else None
            return LineResult(line.display_name, "not_found",
                              note=f"best match too weak ({best!r})" if best else "no titles")

        # Try candidates best-first: variant-style listings ("See options")
        # carry no add button, so fall through to the next-best match.
        for score, title, card in eligible:
            for bsel in self.pack.get("add_button", []):
                try:
                    button = card.locator(bsel).first
                    button.scroll_into_view_if_needed(timeout=2000)
                    button.click(timeout=4000)
                    human_pause()
                    return LineResult(
                        line.display_name,
                        "added" if score >= 0.75 else "substituted",
                        product_title=title,
                    )
                except Exception:
                    continue
        return LineResult(line.display_name, "not_found", note="no addable card",
                          product_title=eligible[0][1])
