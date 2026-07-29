"""Gmail SMTP sender. Credentials come from the environment only:
MEALPLANNER_SMTP_USER / MEALPLANNER_SMTP_PASS (a Gmail app password) —
never from user config files."""

from __future__ import annotations

import os
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage


@dataclass(frozen=True)
class SmtpSettings:
    user: str
    password: str
    host: str = "smtp.gmail.com"
    port: int = 465
    from_name: str = "Meal Planner"


def smtp_from_env() -> SmtpSettings:
    user = os.environ.get("MEALPLANNER_SMTP_USER")
    password = os.environ.get("MEALPLANNER_SMTP_PASS")
    if not user or not password:
        raise RuntimeError(
            "Set MEALPLANNER_SMTP_USER and MEALPLANNER_SMTP_PASS (Gmail app password) "
            "in the environment to send email."
        )
    return SmtpSettings(user=user, password=password)


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
    settings = settings or smtp_from_env()
    msg = build_message(settings, to, cc or [], subject, text, html)
    with smtplib.SMTP_SSL(settings.host, settings.port) as server:
        server.login(settings.user, settings.password)
        server.send_message(msg)
