"""Mid-week restock reminder: current restock list + last order's not-founds."""

from __future__ import annotations

from pathlib import Path

from ..config import load_user_config, user_dir
from ..emailer.sender import send_email
from ..state.store import StateStore


def run_restock(user: str, *, base: Path | None = None, dry_run: bool = False) -> int:
    config = load_user_config(user, base)
    if not config.emails_enabled.restock:
        return 0
    store = StateStore(user_dir(user, base))
    restock = store.load_restock()
    not_found: list[str] = []
    orders = store.load_orders(limit=1)
    if orders:
        _, last = orders[0]
        for cart in last.get("carts") or []:
            not_found.extend(cart.get("not_found") or [])

    if not restock and not not_found:
        print(f"[{user}] nothing to restock; no email")
        return 0

    lines = [f"  - {l.raw}" + (f" ({l.reason})" if l.reason and l.reason != "restock" else "")
             for l in restock]
    body = "Running restock list:\n" + ("\n".join(lines) or "  (empty)")
    if not_found:
        body += "\n\nStill unsourced from the last order:\n" + "\n".join(
            f"  - {n}" for n in not_found
        )
    body += "\n\nThese will be added to the next weekly order automatically."
    html = "<pre style='font-family: Georgia, serif;'>" + body + "</pre>"

    if dry_run:
        print(body)
        return 0
    send_email(to=config.email.to, cc=config.email.cc,
               subject="Mid-week restock check", text=body, html=html)
    print(f"[{user}] restock email sent")
    return 0
