"""Gmail SMTP sender. Credentials come from user_info.json (see
sample_user_info.json), with MEALPLANNER_SMTP_USER / MEALPLANNER_SMTP_PASS
environment variables as a fallback. Never from per-user config files."""

from __future__ import annotations

import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

from ..credentials import smtp_credentials


@dataclass(frozen=True)
class SmtpSettings:
    user: str
    password: str
    host: str = "smtp.gmail.com"
    port: int = 465
    from_name: str = "PantryOS"


def smtp_settings() -> SmtpSettings:
    user, password, from_name = smtp_credentials()
    if not user or not password:
        raise RuntimeError(
            "No email credentials: fill in the \"email\" block of user_info.json "
            "(copy sample_user_info.json) with your Gmail address and app password."
        )
    return SmtpSettings(user=user, password=password, from_name=from_name)


def build_message(
    settings: SmtpSettings,
    to: list[str],
    cc: list[str],
    subject: str,
    text: str,
    html: str,
) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = f"{settings.from_name} <{settings.user}>"
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = subject
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    return msg


def send_email(
    to: list[str],
    subject: str,
    text: str,
    html: str,
    cc: list[str] | None = None,
    settings: SmtpSettings | None = None,
) -> None:
    settings = settings or smtp_settings()
    msg = build_message(settings, to, cc or [], subject, text, html)
    with smtplib.SMTP_SSL(settings.host, settings.port) as server:
        server.login(settings.user, settings.password)
        server.send_message(msg)
