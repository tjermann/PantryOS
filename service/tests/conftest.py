"""Suite-wide guards."""

import pytest


@pytest.fixture(autouse=True)
def _no_real_email(monkeypatch):
    """user_info.json on a live install holds a real Gmail app password; a test
    that forgets dry_run must fail, not mail the household."""

    def refuse(*a, **k):
        raise AssertionError("test tried to open a real SMTP connection")

    monkeypatch.setattr("smtplib.SMTP_SSL", refuse)
    monkeypatch.setattr("smtplib.SMTP", refuse)
