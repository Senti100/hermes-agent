from __future__ import annotations

import io
import json
import urllib.error
from email.message import Message

from plugins.perplexity_search import register
from plugins.perplexity_search import tools


class _DummyContext:
    def __init__(self):
        self.calls = []

    def register_tool(self, **kwargs):
        self.calls.append(kwargs)


def test_perplexity_plugin_registers_tool():
    ctx = _DummyContext()

    register(ctx)

    assert len(ctx.calls) == 1
    call = ctx.calls[0]
    assert call["name"] == "perplexity_search"
    assert call["toolset"] == "perplexity_search"
    assert call["requires_env"] == ["PERPLEXITY_API_KEY"]
    assert call["check_fn"] is tools._check_perplexity_available


def test_check_perplexity_available_uses_profile_scoped_config(monkeypatch):
    monkeypatch.setattr(tools, "get_env_value", lambda _name: None)
    assert tools._check_perplexity_available() is False

    monkeypatch.setattr(tools, "get_env_value", lambda _name: "pplx-test")
    assert tools._check_perplexity_available() is True


def test_perplexity_search_requires_query(monkeypatch):
    monkeypatch.setattr(tools, "get_env_value", lambda _name: "pplx-test")

    result = json.loads(tools._handle_perplexity_search({}))

    assert result["success"] is False
    assert "query" in result["error"]


def test_perplexity_search_success(monkeypatch):
    monkeypatch.setenv("PERPLEXITY_API_KEY", "wrong-global-profile-key")
    monkeypatch.setattr(tools, "get_env_value", lambda _name: "pplx-secret-value")
    captured = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit=-1):
            return json.dumps(
                {
                    "model": "sonar",
                    "choices": [{"message": {"content": "Answer with citations."}}],
                    "citations": ["https://example.com/source"],
                    "search_results": [{"title": "Source", "url": "https://example.com/source"}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                }
            ).encode()

    def fake_open_credentialed_url(request, *, timeout):
        captured["timeout"] = timeout
        captured["headers"] = dict(request.header_items())
        captured["payload"] = json.loads(request.data.decode())
        return Response()

    monkeypatch.setattr(tools, "open_credentialed_url", fake_open_credentialed_url)

    result = json.loads(
        tools._handle_perplexity_search(
            {
                "query": "What is Hermes Agent?",
                "max_tokens": 1,
                "temperature": 9,
                "search_recency_filter": "week",
                "search_domain_filter": ["example.com"],
                "return_related_questions": "true",
            }
        )
    )

    assert result["success"] is True
    assert result["provider"] == "perplexity"
    assert result["model"] == "sonar"
    assert result["answer"] == "Answer with citations."
    assert result["citations"] == ["https://example.com/source"]
    assert result["usage"] == {"completion_tokens": 5, "prompt_tokens": 10, "total_tokens": 15}
    assert captured["payload"]["max_tokens"] == 16  # Perplexity minimum is enforced.
    assert captured["payload"]["temperature"] == 2.0
    assert captured["payload"]["search_recency_filter"] == "week"
    assert captured["payload"]["search_domain_filter"] == ["example.com"]
    assert captured["payload"]["return_related_questions"] is True
    assert captured["headers"]["Authorization"] == "Bearer pplx-secret-value"
    assert "pplx-secret-value" not in json.dumps(result)


def test_perplexity_search_http_error_is_sanitized(monkeypatch):
    monkeypatch.setattr(tools, "get_env_value", lambda _name: "pplx-secret-value")

    def fake_urlopen_with_body(_request, timeout):
        raise urllib.error.HTTPError(
            url="https://api.perplexity.ai/chat/completions",
            code=400,
            msg="Bad Request",
            hdrs=Message(),
            fp=io.BytesIO(json.dumps({"error": {"message": "bad max_tokens"}}).encode()),
        )

    monkeypatch.setattr(tools, "open_credentialed_url", fake_urlopen_with_body)

    result = json.loads(tools._handle_perplexity_search({"query": "hello"}))

    assert result["success"] is False
    assert result["status_code"] == 400
    assert "bad max_tokens" in result["error"]
    assert "pplx-secret-value" not in json.dumps(result)


def test_perplexity_search_rejects_oversized_response(monkeypatch):
    monkeypatch.setattr(tools, "get_env_value", lambda _name: "pplx-test")

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, limit):
            return b"x" * limit

    monkeypatch.setattr(tools, "open_credentialed_url", lambda *_a, **_k: Response())
    result = json.loads(tools._handle_perplexity_search({"query": "hello"}))
    assert result["success"] is False
    assert "exceeds" in result["error"]


def test_perplexity_search_bounds_provider_output(monkeypatch):
    monkeypatch.setattr(tools, "get_env_value", lambda _name: "pplx-test")
    payload = {
        "choices": [{"message": {"content": "a" * (tools._MAX_ANSWER_CHARS + 10)}}],
        "citations": ["c" * 3000] * (tools._MAX_CITATIONS + 5),
        "search_results": [{"title": "t" * 20_000}] * (tools._MAX_SEARCH_RESULTS + 5),
        "related_questions": ["q" * 2000] * (tools._MAX_RELATED_QUESTIONS + 5),
    }

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return json.dumps(payload).encode()

    monkeypatch.setattr(tools, "open_credentialed_url", lambda *_a, **_k: Response())
    result = json.loads(tools._handle_perplexity_search({"query": "hello"}))
    assert len(result["answer"]) == tools._MAX_ANSWER_CHARS
    assert len(result["citations"]) == tools._MAX_CITATIONS
    assert len(result["citations"][0]) == 2048
    assert len(result["search_results"]) == tools._MAX_SEARCH_RESULTS
    assert len(result["search_results"][0]["title"]) == 10_000
    assert len(result["related_questions"]) == tools._MAX_RELATED_QUESTIONS
