"""ClaudeCliClient tests with a faked subprocess — no live CLI calls."""

import json

import pytest
from pydantic import BaseModel

import mealplanner.llm.cli_backend as cli_backend
from mealplanner.config import EmailConfig, UserConfig
from mealplanner.llm.cli_backend import ClaudeCliClient, ClaudeCliError, _model_alias
from mealplanner.llm.client import client_for_user
from mealplanner.schemas.domain import Household


class Answer(BaseModel):
    ok: bool
    note: str


def fake_run(responses):
    """Returns a stand-in for subprocess.run yielding queued stdout payloads."""
    calls = []

    class Proc:
        def __init__(self, stdout):
            self.stdout = stdout
            self.stderr = ""
            self.returncode = 0

    def _run(cmd, input, capture_output, text, timeout):
        calls.append({"cmd": cmd, "input": input})
        return Proc(responses.pop(0))

    return _run, calls


def envelope(result: str) -> str:
    return json.dumps({
        "is_error": False, "stop_reason": "end_turn", "result": result,
        "usage": {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 50},
    })


def test_parses_clean_json(monkeypatch):
    run, calls = fake_run([envelope('{"ok": true, "note": "hi"}')])
    monkeypatch.setattr(cli_backend.subprocess, "run", run)
    response = ClaudeCliClient().messages.parse(
        model="claude-opus-5", messages=[{"role": "user", "content": "go"}],
        output_format=Answer, system="be terse",
    )
    assert response.parsed_output == Answer(ok=True, note="hi")
    assert response.stop_reason == "end_turn"
    assert response.usage.input_tokens == 100
    # Prompt embeds system text and the JSON schema; model mapped to alias.
    assert "be terse" in calls[0]["input"]
    assert '"ok"' in calls[0]["input"]
    assert calls[0]["cmd"][calls[0]["cmd"].index("--model") + 1] == "opus"


def test_strips_fences_and_prose(monkeypatch):
    run, _ = fake_run([envelope('Sure!\n```json\n{"ok": false, "note": "x"}\n```')])
    monkeypatch.setattr(cli_backend.subprocess, "run", run)
    response = ClaudeCliClient().messages.parse(
        model="claude-opus-5", messages=[{"role": "user", "content": "go"}],
        output_format=Answer,
    )
    assert response.parsed_output.ok is False


def test_retries_once_on_bad_json(monkeypatch):
    run, calls = fake_run([
        envelope("I cannot answer in JSON, sorry {broken"),
        envelope('{"ok": true, "note": "second try"}'),
    ])
    monkeypatch.setattr(cli_backend.subprocess, "run", run)
    response = ClaudeCliClient().messages.parse(
        model="claude-opus-5", messages=[{"role": "user", "content": "go"}],
        output_format=Answer,
    )
    assert response.parsed_output.note == "second try"
    assert len(calls) == 2
    assert "ONLY the corrected JSON" in calls[1]["input"]
    # Usage accumulates across both attempts.
    assert response.usage.input_tokens == 200


def test_gives_up_after_retry(monkeypatch):
    run, _ = fake_run([envelope("nope"), envelope("still nope")])
    monkeypatch.setattr(cli_backend.subprocess, "run", run)
    with pytest.raises(ClaudeCliError):
        ClaudeCliClient().messages.parse(
            model="claude-opus-5", messages=[{"role": "user", "content": "go"}],
            output_format=Answer,
        )


def test_model_aliases():
    assert _model_alias("claude-opus-5") == "opus"
    assert _model_alias("claude-haiku-4-5") == "haiku"
    assert _model_alias("some-custom-model") == "some-custom-model"


class TestLocalBackend:
    def _client(self, monkeypatch, replies):
        import json as _json
        from mealplanner.llm import local_backend

        calls = []

        class FakeResponse:
            def __init__(self, payload):
                self._payload = payload
            def read(self):
                return _json.dumps(self._payload).encode()
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False

        def fake_urlopen(request, timeout=None):
            calls.append(_json.loads(request.data))
            return FakeResponse({
                "choices": [{"message": {"content": replies.pop(0)}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            })

        monkeypatch.setattr(local_backend.urllib.request, "urlopen", fake_urlopen)
        return local_backend.LocalLlmClient("http://localhost:11434/v1", "llama3.1"), calls

    def test_parses_openai_shape(self, monkeypatch):
        client, calls = self._client(monkeypatch, ['{"ok": true, "note": "n"}'])
        r = client.messages.parse(model="ignored", messages=[{"role": "user", "content": "go"}],
                                  output_format=Answer)
        assert r.parsed_output.ok is True
        assert r.usage.input_tokens == 10
        assert calls[0]["model"] == "llama3.1"      # config model wins
        assert '"ok"' in calls[0]["messages"][0]["content"]  # schema in prompt

    def test_retries_then_succeeds(self, monkeypatch):
        client, calls = self._client(monkeypatch, ["not json at all", '{"ok": false, "note": "x"}'])
        r = client.messages.parse(model="m", messages=[{"role": "user", "content": "go"}],
                                  output_format=Answer)
        assert r.parsed_output.ok is False and len(calls) == 2

    def test_selected_by_config(self):
        from mealplanner.llm.local_backend import LocalLlmClient

        config = UserConfig(
            name="T", email=EmailConfig(to=["t@example.com"]), recipe_library="/tmp",
            llm_backend="local", local_base_url="http://box:1234/v1", local_model="mistral",
            household=Household(id="t", name="T", people=[{"id": "p", "name": "P"}]),
        )
        client = client_for_user(config)
        assert isinstance(client, LocalLlmClient)
        assert client.base_url == "http://box:1234/v1" and client.model == "mistral"


def test_backend_selection_needs_no_api_key():
    config = UserConfig(
        name="T", email=EmailConfig(to=["t@example.com"]), recipe_library="/tmp",
        llm_backend="claude-cli",
        household=Household(id="t", name="T", people=[{"id": "p", "name": "P"}]),
    )
    client = client_for_user(config)  # must not raise about missing keys
    assert isinstance(client, ClaudeCliClient)
