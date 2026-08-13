"""LLM client factory: metered API key, or headless Claude Code on a
subscription — both expose the same `messages.parse` surface downstream."""

from __future__ import annotations

from ..config import UserConfig, resolve_api_key


def client_for_user(config: UserConfig):
    if config.llm_backend == "claude-cli":
        from .cli_backend import ClaudeCliClient

        return ClaudeCliClient(binary=config.claude_cli_path)
    if config.llm_backend == "local":
        from .local_backend import LocalLlmClient

        return LocalLlmClient(
            base_url=config.local_base_url,
            model=config.local_model,
            api_key=config.anthropic_api_key,  # some gateways want a token
        )
    import anthropic

    return anthropic.Anthropic(api_key=resolve_api_key(config))
