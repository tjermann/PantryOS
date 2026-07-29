"""Store driver interface + cart reporting.

Hard rules, unchanged from the reference system:
 - Drivers NEVER touch checkout. They stop at the cart page; the human
   reviews substitutions and submits the order.
 - No passwords are ever collected. Login happens once in a headed browser
   (`mealplanner login`), and the session persists in a per-user+store
   Playwright profile directory.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal

from ..grocery.pipeline import GroceryLine

SessionStatus = Literal["ok", "expired", "unknown"]
LineStatus = Literal["added", "substituted", "not_found", "skipped"]


@dataclass
class LineResult:
    display_name: str
    status: LineStatus
    product_title: str | None = None
    note: str | None = None


@dataclass
class CartReport:
    store_id: str
    session: SessionStatus
    results: list[LineResult] = field(default_factory=list)
    cart_url: str | None = None
    error: str | None = None

    @property
    def added(self) -> int:
        return sum(1 for r in self.results if r.status == "added")

    @property
    def substituted(self) -> int:
        return sum(1 for r in self.results if r.status == "substituted")

    @property
    def not_found(self) -> list[str]:
        return [r.display_name for r in self.results if r.status == "not_found"]

    def summary(self) -> str:
        if self.session == "expired":
            return "store session expired"
        if self.error:
            return f"cart loading failed: {self.error}"
        parts = [f"{self.added} added"]
        if self.substituted:
            parts.append(f"{self.substituted} substituted")
        if self.not_found:
            parts.append(f"{len(self.not_found)} not found")
        return ", ".join(parts)


class StoreDriver(ABC):
    """One driver instance per (user, store) run; operates on a Playwright page."""

    id: str

    @abstractmethod
    def home_url(self) -> str: ...

    @abstractmethod
    def login_url(self) -> str: ...

    @abstractmethod
    def cart_url(self) -> str: ...

    @abstractmethod
    def check_session(self, page) -> SessionStatus: ...

    @abstractmethod
    def search_and_add(self, page, line: GroceryLine) -> LineResult: ...
