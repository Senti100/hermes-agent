from types import SimpleNamespace
from unittest.mock import patch



def testcheck_via_pypi_detects_update():
    """check_via_pypi returns 1 when PyPI has newer version."""
    from hermes_cli.banner import check_via_pypi
    with patch("hermes_cli.banner.VERSION", "0.12.0"):
        with patch("hermes_cli.banner._fetch_pypi_latest", return_value="0.13.0"):
            result = check_via_pypi()
            assert result == 1


def testcheck_via_pypi_up_to_date():
    """check_via_pypi returns 0 when versions match."""
    from hermes_cli.banner import check_via_pypi
    with patch("hermes_cli.banner.VERSION", "0.13.0"):
        with patch("hermes_cli.banner._fetch_pypi_latest", return_value="0.13.0"):
            result = check_via_pypi()
            assert result == 0


def testcheck_via_pypi_network_failure():
    """check_via_pypi returns None on network error."""
    from hermes_cli.banner import check_via_pypi
    with patch("hermes_cli.banner._fetch_pypi_latest", return_value=None):
        result = check_via_pypi()
        assert result is None


def test_version_tuple_comparison():
    """Version comparison works with multi-segment versions."""
    from hermes_cli.banner import _version_tuple
    assert _version_tuple("0.13.0") > _version_tuple("0.12.0")
    assert _version_tuple("0.13.0") == _version_tuple("0.13.0")
    assert _version_tuple("1.0.0") > _version_tuple("0.99.99")


def test_build_welcome_banner_prefers_skin_raw_ansi_hero(monkeypatch):
    """Legacy Rich banner uses the same raw ANSI skin hero as the Ink TUI."""
    from rich.console import Console

    import hermes_cli.banner as banner
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
    monkeypatch.setattr("model_tools.check_tool_availability", lambda quiet=True: ([], []))
    monkeypatch.setattr("model_tools.TOOLSET_REQUIREMENTS", {})
    monkeypatch.setattr("tools.mcp_tool.get_mcp_status", lambda: [])
    monkeypatch.setattr("hermes_cli.profiles.get_active_profile_name", lambda: "default")

    console = Console(force_terminal=True, color_system="truecolor", width=120, record=True)
    banner.build_welcome_banner(console, "test-model", "/tmp", tools=[], context_length=128000)
    output = console.export_text(styles=True)

    assert "⣀⡀" in output
    assert "\x1b[38;2;100;217;255m" in output
    assert "FALLBACK_HERO_SHOULD_NOT_RENDER" not in output
