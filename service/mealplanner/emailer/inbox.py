"""Reply-to-email feedback: poll the sender Gmail inbox for replies from
household members and feed their words straight into planning context.

Katy replies "less spicy please, and Tuesday's shrimp was great" to the
weekly email; on the next inbox poll that lands in learnings.md and shapes
the next plan. No webpage required.
"""

from __future__ import annotations

import email
import email.utils
import imaplib
import re
from datetime import date
from pathlib import Path

from ..config import list_users, load_user_config, user_dir
from ..state.store import StateStore
from .sender import smtp_settings

IMAP_HOST = "imap.gmail.com"
MAX_FEEDBACK_CHARS = 1500

_QUOTE_MARKERS = (
    # Gmail wraps this attribution across lines, so match the start of it and
    # let the trailing 'wrote:' land wherever it lands.
    re.compile(r"^On\s+\w.{0,160}?(?:wrote:|<[^>]+@[^>]+>)\s*$"),
    re.compile(r"^On\s+(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\s"),
    re.compile(r"^-{2,}\s*Original Message\s*-{2,}", re.IGNORECASE),
    re.compile(r"^_{5,}\s*$"),
    re.compile(r"^From: .*@.*$"),
    re.compile(r"^Sent from my \w+", re.IGNORECASE),
)


def strip_quoted_reply(body: str) -> str:
    """Keep only the person's own words: drop quoted history and signatures."""
    lines: list[str] = []
    for line in body.splitlines():
        if any(marker.match(line.strip()) for marker in _QUOTE_MARKERS):
            break
        if line.strip().startswith(">"):
            continue
        if line.strip() == "--":  # signature delimiter
            break
        lines.append(line)
    text = "\n".join(lines).strip()
    return text[:MAX_FEEDBACK_CHARS]


def _plain_text(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode(part.get_content_charset() or "utf-8", "replace")
        return ""
    payload = msg.get_payload(decode=True)
    return payload.decode(msg.get_content_charset() or "utf-8", "replace") if payload else ""


def poll_inbox(base: Path | None = None, dry_run: bool = False) -> int:
    """Read unseen replies from any configured household member; returns count."""
    settings = smtp_settings()
    # sender address -> (user, member name) for every household
    senders: dict[str, tuple[str, str]] = {}
    for user in list_users(base):
        config = load_user_config(user, base)
        for addr in [*config.email.to, *config.email.cc]:
            senders[addr.lower()] = (user, addr.split("@")[0])

    ingested = 0
    with imaplib.IMAP4_SSL(IMAP_HOST) as imap:
        imap.login(settings.user, settings.password)
        imap.select("INBOX")
        _, data = imap.search(None, "UNSEEN")
        for num in data[0].split():
            _, fetched = imap.fetch(num, "(RFC822)")
            if not fetched or fetched[0] is None:
                continue
            msg = email.message_from_bytes(fetched[0][1])
            sender = email.utils.parseaddr(msg.get("From", ""))[1].lower()
            if sender not in senders:
                continue  # not a household member; leave untouched for a human
            user, name = senders[sender]
            text = strip_quoted_reply(_plain_text(msg))
            if dry_run:
                if text:
                    print(f"[{user}] would ingest from {name}: {text[:80]!r}")
                continue
            if text:
                _ingest(user, name, text, base)
                ingested += 1
            # Processed either way — clear it from the inbox (Gmail keeps an
            # archived copy in All Mail; nothing is destroyed).
            imap.store(num, "+FLAGS", "\\Deleted")
        if not dry_run:
            imap.expunge()
    return ingested


def _ingest(user: str, name: str, text: str, base: Path | None) -> None:
    """A reply can both choose this week's meals and leave a lasting preference.
    It is read for picks first; only the preference part becomes a learning, so
    one week's choices don't steer every future week."""
    store = StateStore(user_dir(user, base))
    stamp = date.today().isoformat()
    applied = config = None
    try:
        from ..config import load_user_config
        from ..jobs.reply import apply_reply

        config = load_user_config(user, base)
        applied = apply_reply(user, config, text, base)
    except Exception as exc:
        # Never lose the message because the clever path broke.
        print(f"[{user}] could not read {name}'s reply as picks: {exc}")

    if applied is not None and applied.changed:
        print(f"[{user}] {name} picked {len(applied.dinners)} dinner(s), "
              f"{len(applied.lunches)} lunch(es)"
              + (f", carried over {len(applied.carried)}" if applied.carried else ""))
        if applied.notes:
            store.append_learning(f"Email feedback from {name} ({stamp}): {applied.notes}")
    else:
        if applied is not None and applied.unmatched:
            print(f"[{user}] {name} asked for meals but nothing matched: "
                  f"{applied.unmatched}")
        store.append_learning(f"Email feedback from {name} ({stamp}): {text}")
        print(f"[{user}] feedback from {name} recorded ({len(text)} chars)")

    if applied is not None and config is not None:
        try:
            from ..jobs.reply import confirm_email, settle_fingerprint

            if applied.changed:
                # After the learning is written, so the settled plan matches the
                # state the iterate job will compare against.
                settle_fingerprint(user, base)
            confirm_email(user, config, applied, base)
        except Exception as exc:
            print(f"[{user}] could not confirm picks to {name}: {exc}")
