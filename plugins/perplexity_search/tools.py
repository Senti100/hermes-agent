"""Perplexity Sonar search/research tool implementation."""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from typing import Any

from hermes_cli.config import get_env_value
from hermes_cli.urllib_security import open_credentialed_url
from tools.registry import tool_error, tool_result

_API_URL = "https://api.perplexity.ai/chat/completions"
_DEFAULT_MODEL = "sonar"
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_MAX_ANSWER_CHARS = 50_000
_MAX_CITATIONS = 100
_MAX_SEARCH_RESULTS = 50
_MAX_RELATED_QUESTIONS = 20
_ALLOWED_RECENCY = {"day", "week", "month", "year"}
_USAGE_KEYS = {
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "citation_tokens",
    "num_search_queries",
    "search_context_size",
}

PERPLEXITY_SEARCH_SCHEMA = {
    "type": "function",
    "function": {
        "name": "perplexity_search",
        "description": (
            "Search the live web with Perplexity Sonar and return a synthesized "
            "answer with citations. Use this when you need a second current-search "
            "lane or source-backed research beyond the default web_search tool."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Research/search question to ask Perplexity.",
                },
                "model": {
                    "type": "string",
                    "description": (
                        "Perplexity model id. Defaults to sonar. Common options include "
                        "sonar, sonar-pro, sonar-reasoning, and sonar-deep-research when "
                        "available on the account."
                    ),
                },
                "max_tokens": {
                    "type": "integer",
                    "minimum": 16,
                    "maximum": 8000,
                    "description": "Maximum completion tokens. Perplexity requires at least 16. Default: 1024.",
                },
                "temperature": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 2,
                    "description": "Sampling temperature. Default: 0.2 for research stability.",
                },
                "search_domain_filter": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional Perplexity domain filter. Use bare domains to include "
                        "or prefix with '-' to exclude, e.g. ['fcc.gov'] or ['-reddit.com']."
                    ),
                },
                "search_recency_filter": {
                    "type": "string",
                    "enum": sorted(_ALLOWED_RECENCY),
                    "description": "Optional recency filter: day, week, month, or year.",
                },
                "return_related_questions": {
                    "type": "boolean",
                    "description": "Whether to ask Perplexity for related questions. Default: false.",
                },
            },
            "required": ["query"],
        },
    },
}


def _check_perplexity_available() -> bool:
    """Return True when the profile has a Perplexity API key in the environment."""
    return bool((get_env_value("PERPLEXITY_API_KEY") or "").strip())


def _coerce_int(raw: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(raw)
    except Exception:
        value = default
    return max(minimum, min(maximum, value))


def _coerce_float(raw: Any, *, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(raw)
    except Exception:
        value = default
    return max(minimum, min(maximum, value))


def _coerce_bool(raw: Any, default: bool = False) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        value = raw.strip().lower()
        if value in {"1", "true", "yes", "on"}:
            return True
        if value in {"0", "false", "no", "off"}:
            return False
    return default


def _coerce_str_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        items = [raw]
    elif isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        return []
    return [str(item).strip() for item in items if str(item).strip()]


def _extract_error_message(body: str) -> str:
    try:
        payload = json.loads(body)
    except Exception:
        return body.strip()[:500] or "unknown provider error"

    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        message = error.get("message") or error.get("type") or error.get("code")
        return str(message or error)[:500]
    if error:
        return str(error)[:500]
    return str(payload)[:500]


def _usage_summary(usage: Any) -> dict[str, Any]:
    if not isinstance(usage, dict):
        return {}
    return {key: usage[key] for key in sorted(_USAGE_KEYS) if key in usage}


def _read_bounded_response(response: Any, *, limit: int = _MAX_RESPONSE_BYTES) -> bytes:
    """Read one provider response without allowing unbounded memory growth."""
    raw = response.read(limit + 1)
    if len(raw) > limit:
        raise ValueError(f"Perplexity response exceeds {limit} bytes")
    return raw


def _bounded_strings(value: Any, *, count: int, chars: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item)[:chars] for item in value[:count]]


def _bounded_results(value: Any) -> list[dict[str, Any]]:
    """Keep search-result metadata useful while bounding nested provider data."""
    if not isinstance(value, list):
        return []
    bounded: list[dict[str, Any]] = []
    for item in value[:_MAX_SEARCH_RESULTS]:
        if not isinstance(item, dict):
            continue
        bounded.append(
            {
                str(key)[:100]: str(raw)[:10_000]
                for key, raw in list(item.items())[:30]
                if raw is not None
            }
        )
    return bounded


def _handle_perplexity_search(args: dict, **_kwargs: Any) -> str:
    """Run a Perplexity Sonar query and return answer/citation JSON."""
    query = str(args.get("query") or args.get("q") or "").strip()
    if not query:
        return tool_error("query is required", success=False)

    api_key = (get_env_value("PERPLEXITY_API_KEY") or "").strip()
    if not api_key:
        return tool_error("PERPLEXITY_API_KEY is not set for this Hermes profile", success=False)

    model = str(args.get("model") or _DEFAULT_MODEL).strip() or _DEFAULT_MODEL
    max_tokens = _coerce_int(args.get("max_tokens"), default=1024, minimum=16, maximum=8000)
    temperature = _coerce_float(args.get("temperature"), default=0.2, minimum=0.0, maximum=2.0)

    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Answer as a concise research assistant. Prioritize current, source-backed "
                    "facts. Include citations in the response when Perplexity provides them."
                ),
            },
            {"role": "user", "content": query},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    domain_filter = _coerce_str_list(args.get("search_domain_filter"))
    if domain_filter:
        payload["search_domain_filter"] = domain_filter

    recency = str(args.get("search_recency_filter") or "").strip().lower()
    if recency:
        if recency not in _ALLOWED_RECENCY:
            return tool_error(
                "search_recency_filter must be one of: day, week, month, year",
                success=False,
            )
        payload["search_recency_filter"] = recency

    if "return_related_questions" in args:
        payload["return_related_questions"] = _coerce_bool(args.get("return_related_questions"))

    request = urllib.request.Request(
        _API_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "hermes-agent-perplexity-search/1.0",
        },
        method="POST",
    )

    try:
        with open_credentialed_url(request, timeout=60) as response:
            raw = _read_bounded_response(response).decode("utf-8", "replace")
            data = json.loads(raw)
    except urllib.error.HTTPError as exc:
        body = exc.read(2000).decode("utf-8", "replace")
        return tool_error(
            f"Perplexity API error {exc.code}: {_extract_error_message(body)}",
            success=False,
            status_code=exc.code,
        )
    except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
        return tool_error(f"Perplexity request failed: {type(exc).__name__}: {exc}", success=False)
    except json.JSONDecodeError as exc:
        return tool_error(f"Perplexity returned invalid JSON: {exc}", success=False)
    except ValueError as exc:
        return tool_error(str(exc), success=False)

    choices = data.get("choices") if isinstance(data, dict) else None
    message = (choices[0].get("message") if choices and isinstance(choices[0], dict) else {}) or {}
    answer = str(message.get("content") or "").strip()[:_MAX_ANSWER_CHARS]

    return tool_result(
        success=True,
        provider="perplexity",
        model=data.get("model") or model,
        query=query,
        answer=answer,
        citations=_bounded_strings(data.get("citations"), count=_MAX_CITATIONS, chars=2_048),
        search_results=_bounded_results(data.get("search_results")),
        related_questions=_bounded_strings(
            data.get("related_questions"), count=_MAX_RELATED_QUESTIONS, chars=1_000
        ),
        usage=_usage_summary(data.get("usage")),
    )
