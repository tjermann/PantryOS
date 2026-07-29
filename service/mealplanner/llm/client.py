"""Anthropic client factory — per-user key with operator env fallback."""

from __future__ import annotations

import anthropic

from ..config import UserConfig, resolve_api_key


def client_for_user(config: UserConfig) -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=resolve_api_key(config))
