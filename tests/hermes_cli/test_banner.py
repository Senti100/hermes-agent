"""Tests for banner toolset name normalization and skin color usage."""

from types import SimpleNamespace
from unittest.mock import patch

from rich.console import Console

import hermes_cli.banner as banner
import model_tools
import tools.mcp_tool


def test_cprint_falls_back_to_plain_print_when_prompt_toolkit_has_no_console(capsys):
    with patch(
        "prompt_toolkit.print_formatted_text",
        side_effect=RuntimeError("no console screen buffer"),
    ):
        banner.cprint("fallback text")

    assert capsys.readouterr().out == "fallback text\n"








def test_build_welcome_banner_title_falls_back_when_no_tag():
    """Without a resolvable tag, the panel title renders as plain text (no hyperlink escape)."""
    import io
    from unittest.mock import patch as _patch
    import hermes_cli.banner as _banner
    import model_tools as _mt
    import tools.mcp_tool as _mcp

    _banner._latest_release_cache = None
    buf = io.StringIO()
    with (
        _patch.object(_mt, "check_tool_availability", return_value=(["web"], [])),
        _patch.object(_banner, "get_available_skills", return_value={}),
        _patch.object(_banner, "get_update_result", return_value=None),
        _patch.object(_mcp, "get_mcp_status", return_value=[]),
        _patch.object(_banner, "get_latest_release_tag", return_value=None),
    ):
        console = Console(file=buf, force_terminal=True, color_system="truecolor", width=160)
        _banner.build_welcome_banner(
            console=console, model="x", cwd="/tmp",
            session_id="abc123",
            tools=[{"function": {"name": "read_file"}}],
            get_toolset_for_tool=lambda n: "file",
        )

    raw = buf.getvalue()
    assert "Hermes Agent v" in raw, "Version label missing from title"
    assert "\x1b]8;" not in raw, "OSC-8 hyperlink should not be emitted without a tag"






def test_build_welcome_banner_non_moa_unchanged(tmp_path, monkeypatch):
    """A normal provider still renders the bare model slug, no MoA prefix."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    (tmp_path / ".hermes").mkdir()

    with (
        patch.object(model_tools, "check_tool_availability", return_value=([], [])),
        patch.object(banner, "get_available_skills", return_value={}),
        patch.object(banner, "get_update_result", return_value=None),
        patch.object(tools.mcp_tool, "get_mcp_status", return_value=[]),
    ):
        console = Console(record=True, force_terminal=False, color_system=None, width=160)
        banner.build_welcome_banner(
            console=console,
            model="anthropic/claude-opus-4.8",
            cwd="/tmp/project",
            tools=[],
            enabled_toolsets=[],
            provider="openrouter",
        )

    out = console.export_text()
    assert "claude-opus-4.8" in out
    assert "MoA:" not in out


def test_build_welcome_banner_prefers_skin_raw_ansi_hero(monkeypatch):
    """The Rich banner consumes the same raw ANSI skin hero as the Ink TUI."""
    from hermes_cli import skin_engine

    def color(key, fallback=""):
        colors = {
            "banner_accent": "#FF5BE0",
            "banner_dim": "#6F7C99",
            "banner_text": "#F6F4FF",
            "session_border": "#4A5168",
            "banner_title": "#C3F8FF",
            "banner_border": "#64D9FF",
        }
        return colors.get(key, fallback)

    skin = SimpleNamespace(
        banner_hero="FALLBACK_HERO_SHOULD_NOT_RENDER",
        banner_hero_ansi="\x1b[38;2;100;217;255m⣀⡀\x1b[0m\n",
        banner_logo="",
        get_color=color,
    )
    monkeypatch.setattr(skin_engine, "get_active_skin", lambda: skin)
    monkeypatch.setattr(banner, "get_available_skills", lambda: {})
    monkeypatch.setattr(banner, "get_update_result", lambda timeout=0.5: 0)
    monkeypatch.setattr(banner, "get_latest_release_tag", lambda: None)
    monkeypatch.setattr(banner, "format_banner_version_label", lambda: "Hermes Agent test")
    monkeypatch.setattr(model_tools, "check_tool_availability", lambda quiet=True: ([], []))
    monkeypatch.setattr(model_tools, "TOOLSET_REQUIREMENTS", {})
    monkeypatch.setattr(tools.mcp_tool, "get_mcp_status", lambda: [])
    monkeypatch.setattr("hermes_cli.profiles.get_active_profile_name", lambda: "default")

    console = Console(force_terminal=True, color_system="truecolor", width=120, record=True)
    banner.build_welcome_banner(console, "test-model", "/tmp", tools=[], context_length=128000)
    output = console.export_text(styles=True)

    assert "⣀⡀" in output
    assert "\x1b[38;2;100;217;255m" in output
    assert "FALLBACK_HERO_SHOULD_NOT_RENDER" not in output
