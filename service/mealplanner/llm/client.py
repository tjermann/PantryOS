"""LLM client factory: metered API key, or headless Claude Code on a
subscription — both expose the same `messages.parse` surface downstream."""

from __future__ import annotations

from ..config import UserConfig, resolve_api_key


def client_for_user(config: UserConfig):
    if config.llm_backend == "claude-cli":
        from .cli_backend import ClaudeCliClient

        return ClaudeCliClient(binary=config.claude_cli_path)
    import anthropic

    return anthropic.Anthropic(api_key=resolve_api_key(config))
