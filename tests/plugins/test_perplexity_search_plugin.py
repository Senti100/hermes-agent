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


def test_check_perplexity_available_uses_env(monkeypatch):
    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
    assert tools._check_perplexity_available() is False

    monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test")
    assert tools._check_perplexity_available() is True


def test_perplexity_search_requires_query(monkeypatch):
    monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test")

    result = json.loads(tools._handle_perplexity_search({}))

    assert result["success"] is False
    assert "query" in result["error"]


def test_perplexity_search_success(monkeypatch):
    monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-secret-value")
    captured = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {
                    "model": "sonar",
                    "choices": [{"message": {"content": "Answer with citations."}}],
                    "citations": ["https://example.com/source"],
                    "search_results": [{"title": "Source", "url": "https://example.com/source"}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                }
            ).encode()

    def fake_urlopen(request, timeout):
        captured["timeout"] = timeout
        captured["headers"] = dict(request.header_items())
        captured["payload"] = json.loads(request.data.decode())
        return Response()

    monkeypatch.setattr(tools.urllib.request, "urlopen", fake_urlopen)

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
    monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-secret-value")

    def fake_urlopen_with_body(_request, timeout):
        raise urllib.error.HTTPError(
            url="https://api.perplexity.ai/chat/completions",
            code=400,
            msg="Bad Request",
            hdrs=Message(),
            fp=io.BytesIO(json.dumps({"error": {"message": "bad max_tokens"}}).encode()),
        )

    monkeypatch.setattr(tools.urllib.request, "urlopen", fake_urlopen_with_body)

    result = json.loads(tools._handle_perplexity_search({"query": "hello"}))

    assert result["success"] is False
    assert result["status_code"] == 400
    assert "bad max_tokens" in result["error"]
    assert "pplx-secret-value" not in json.dumps(result)
