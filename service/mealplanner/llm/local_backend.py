"""Local / self-hosted LLM backend.

Talks to any OpenAI-compatible chat endpoint — Ollama, LM Studio, llama.cpp's
server, vLLM, or a private company gateway — so a household can plan meals
with no API bill and nothing leaving the house.

Structured output is enforced on our side exactly as with the Claude CLI
backend: the JSON schema goes in the prompt, the reply is parsed and
pydantic-validated, and one retry covers malformed output. Downstream, the
deterministic allergen backstop and validators apply regardless of which
model produced the plan — that's what makes a small local model safe here.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from types import SimpleNamespace
from typing import Any

from pydantic import BaseModel

from .cli_backend import _extract_json, _flatten_messages


class LocalLlmError(RuntimeError):
    pass


class _Messages:
    def __init__(self, outer: "LocalLlmClient"):
        self._outer = outer

    def parse(
        self,
        *,
        model: str,
        messages: list[dict],
        output_format: type[BaseModel],
        system: Any = None,
        max_tokens: int = 16000,
        **_ignored: Any,
    ) -> SimpleNamespace:
        outer = self._outer
        schema = json.dumps(output_format.model_json_schema())
        prompt = (
            f"{_flatten_messages(system, messages)}\n\n"
            "[OUTPUT REQUIREMENTS]\n"
            "Respond with ONLY a single JSON object matching this JSON schema. "
            "No prose, no markdown fences.\n"
            f"{schema}"
        )
        usage = SimpleNamespace(input_tokens=0, output_tokens=0, cache_read_input_tokens=0)
        last_error: Exception | None = None
        for attempt in range(2):
            body = prompt if attempt == 0 else (
                prompt + f"\n\nYour previous reply was not valid JSON for the schema "
                         f"({last_error}). Reply with ONLY the corrected JSON object."
            )
            text, counted = outer._chat(body, outer.model or model, max_tokens)
            usage.input_tokens += counted.get("prompt_tokens", 0)
            usage.output_tokens += counted.get("completion_tokens", 0)
            try:
                parsed = output_format.model_validate_json(_extract_json(text))
                return SimpleNamespace(
                    parsed_output=parsed, stop_reason="end_turn", usage=usage
                )
            except Exception as exc:
                last_error = exc
        raise LocalLlmError(
            f"local model at {outer.base_url} returned unusable output after a retry: "
            f"{last_error}"
        )


class LocalLlmClient:
    """Drop-in for the planner/importer client, backed by a local endpoint."""

    def __init__(self, base_url: str, model: str | None = None, timeout_s: int = 900,
                 api_key: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s
        self.api_key = api_key
        self.messages = _Messages(self)

    def _chat(self, prompt: str, model: str, max_tokens: int) -> tuple[str, dict]:
        payload = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.2,
            "stream": False,
        }).encode()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions", data=payload, headers=headers
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                data = json.loads(response.read().decode())
        except urllib.error.URLError as exc:
            raise LocalLlmError(
                f"couldn't reach the local model at {self.base_url} ({exc}). "
                f"Is it running? For Ollama: `ollama serve`, then `ollama pull <model>`."
            ) from exc
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise LocalLlmError(f"unexpected response shape: {str(data)[:200]}") from exc
        return text, data.get("usage", {}) or {}
