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
    # Only what's run out since the last order — the order itself resets the
    # queue, and anything the cart couldn't find is assumed sourced elsewhere.
    restock = store.load_restock()

    if not restock:
        print(f"[{user}] nothing to restock; no email")
        return 0

    lines = [f"  - {l.raw}" + (f" ({l.reason})" if l.reason and l.reason != "restock" else "")
             for l in restock]
    body = "Ran out this week:\n" + "\n".join(lines)
    body += "\n\nThese will be added to the next weekly order automatically."
    html = "<pre style='font-family: Georgia, serif;'>" + body + "</pre>"

    if dry_run:
        print(body)
        return 0
    send_email(to=config.email.to, cc=config.email.cc,
               subject="Mid-week restock check", text=body, html=html)
    print(f"[{user}] restock email sent")
    return 0
