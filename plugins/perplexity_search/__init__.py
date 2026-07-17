"""Perplexity Search plugin for Hermes.

Registers a ``perplexity_search`` toolset/tool backed by Perplexity's
OpenAI-compatible chat completions API. The tool is gated by
``PERPLEXITY_API_KEY`` so profiles without a key do not expose it to models.
"""

from __future__ import annotations

from .tools import (
    PERPLEXITY_SEARCH_SCHEMA,
    _check_perplexity_available,
    _handle_perplexity_search,
)


def register(ctx) -> None:
    """Register the Perplexity search/research tool."""
    ctx.register_tool(
        name="perplexity_search",
        toolset="perplexity_search",
        schema=PERPLEXITY_SEARCH_SCHEMA,
        handler=_handle_perplexity_search,
        check_fn=_check_perplexity_available,
        requires_env=["PERPLEXITY_API_KEY"],
        emoji="🔎",
    )
