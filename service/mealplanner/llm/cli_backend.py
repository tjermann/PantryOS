"""Headless Claude Code backend — plan with a Claude subscription instead of
a metered API key.

`ClaudeCliClient` mimics the one method PantryOS uses from the Anthropic SDK
(`client.messages.parse(...)` returning `.parsed_output` / `.stop_reason` /
`.usage`), but executes `claude -p` (Claude Code's non-interactive mode) under
the hood. Structured output is enforced on our side: the prompt embeds the
JSON schema, the reply is parsed and pydantic-validated, and one retry with a
stricter instruction covers malformed output. Downstream, the same validation
+ repair loop + deterministic allergen backstop apply regardless of backend.
"""

from __future__ import annotations

import json
import re
import subprocess
from types import SimpleNamespace
from typing import Any

from pydantic import BaseModel


class ClaudeCliError(RuntimeError):
    pass


def _model_alias(model: str) -> str:
    """Map API model ids to Claude Code --model aliases."""
    lowered = model.lower()
    for tier in ("opus", "sonnet", "haiku"):
        if tier in lowered:
            return tier
    return model


def _flatten_messages(system: Any, messages: list[dict]) -> str:
    parts: list[str] = []
    if system:
        if isinstance(system, str):
            parts.append(system)
        else:  # list of content blocks
            parts.extend(b.get("text", "") for b in system if isinstance(b, dict))
    for m in messages:
        content = m.get("content", "")
        if not isinstance(content, str):
            content = json.dumps(content)
        parts.append(f"[{m.get('role', 'user').upper()}]\n{content}")
    return "\n\n".join(p for p in parts if p)


def _extract_json(text: str) -> str:
    """Pull the JSON object out of a possibly fenced / prosey reply."""
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        return fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ClaudeCliError(f"no JSON object in reply: {text[:200]!r}")
    return text[start : end + 1]


class _Messages:
    def __init__(self, outer: "ClaudeCliClient"):
        self._outer = outer

    def parse(
        self,
        *,
        model: str,
        messages: list[dict],
        output_format: type[BaseModel],
        system: Any = None,
        max_tokens: int = 16000,  # accepted for interface parity; CLI manages its own
        **_ignored: Any,
    ) -> SimpleNamespace:
        outer = self._outer
        schema = json.dumps(output_format.model_json_schema())
        base_prompt = (
            f"{_flatten_messages(system, messages)}\n\n"
            "[OUTPUT REQUIREMENTS]\n"
            "Respond with ONLY a single JSON object that validates against this "
            "JSON schema. No prose, no markdown fences, no explanation.\n"
            f"{schema}"
        )
        last_error: Exception | None = None
        usage = SimpleNamespace(input_tokens=0, output_tokens=0, cache_read_input_tokens=0)
        for attempt in range(2):
            prompt = base_prompt
            if attempt:
                prompt += (
                    "\n\nYour previous reply was not valid JSON for the schema "
                    f"({last_error}). Reply with ONLY the corrected JSON object."
                )
            envelope = outer._invoke(prompt, model)
            for field in ("input_tokens", "output_tokens", "cache_read_input_tokens"):
                current = getattr(usage, field)
                setattr(usage, field, current + int(envelope.get("usage", {}).get(field, 0) or 0))
            text = envelope.get("result")
            if not isinstance(text, str):
                text = json.dumps(envelope)
            try:
                parsed = output_format.model_validate_json(_extract_json(text))
                return SimpleNamespace(
                    parsed_output=parsed,
                    stop_reason=envelope.get("stop_reason", "end_turn"),
                    usage=usage,
                )
            except Exception as exc:  # malformed JSON or schema mismatch → one retry
                last_error = exc
        raise ClaudeCliError(f"claude CLI returned unusable output after retry: {last_error}")


class ClaudeCliClient:
    """Subscription-backed drop-in for the planner/importer client."""

    def __init__(self, binary: str = "claude", timeout_s: int = 900):
        self.binary = binary
        self.timeout_s = timeout_s
        self.messages = _Messages(self)

    def _invoke(self, prompt: str, model: str) -> dict:
        cmd = [
            self.binary, "-p",
            "--output-format", "json",
            "--model", _model_alias(model),
        ]
        try:
            proc = subprocess.run(
                cmd, input=prompt, capture_output=True, text=True, timeout=self.timeout_s
            )
        except FileNotFoundError:
            raise ClaudeCliError(
                f"'{self.binary}' not found. Install Claude Code and sign in "
                f"(https://claude.com/claude-code), or switch llm_backend back to 'api'."
            )
        except subprocess.TimeoutExpired:
            raise ClaudeCliError(f"claude CLI timed out after {self.timeout_s}s")
        if proc.returncode != 0:
            raise ClaudeCliError(
                f"claude CLI exited {proc.returncode}: {(proc.stderr or proc.stdout)[:300]}"
            )
        try:
            envelope = json.loads(proc.stdout)
        except json.JSONDecodeError:
            # Older CLIs or plain-text mode: treat stdout as the reply itself.
            envelope = {"result": proc.stdout, "stop_reason": "end_turn", "usage": {}}
        if envelope.get("is_error"):
            raise ClaudeCliError(f"claude CLI reported an error: {str(envelope)[:300]}")
        return envelope
