"""Fork policy for keeping an explicitly configured Astra model visible."""

from types import SimpleNamespace

from hermes_cli import model_switch_providers as provider_rows
from hermes_cli.model_switch_providers import _include_explicit_current_codex_model


def test_configured_current_astra_is_kept_when_live_catalog_lags():
    models = _include_explicit_current_codex_model(
        ["gpt-5.6-sol", "gpt-5.5"],
        current_provider="openai-codex",
        current_model="gpt-6-astra",
    )

    assert models == ["gpt-6-astra", "gpt-5.6-sol", "gpt-5.5"]


def test_unconfigured_astra_is_not_advertised():
    models = _include_explicit_current_codex_model(
        ["gpt-5.6-sol"],
        current_provider="openai-codex",
        current_model="gpt-5.6-sol",
    )

    assert models == ["gpt-5.6-sol"]


def test_other_provider_cannot_inject_astra_into_codex_picker():
    models = _include_explicit_current_codex_model(
        ["gpt-5.6-sol"],
        current_provider="openrouter",
        current_model="gpt-6-astra",
    )

    assert models == ["gpt-5.6-sol"]


def test_discovered_current_astra_is_not_duplicated():
    models = _include_explicit_current_codex_model(
        ["gpt-6-astra", "gpt-5.6-sol"],
        current_provider="openai-codex",
        current_model="gpt-6-astra",
    )

    assert models == ["gpt-6-astra", "gpt-5.6-sol"]


def test_overlay_row_calls_configured_astra_preservation(monkeypatch):
    overlay = SimpleNamespace(keyless=False, auth_type="oauth")
    monkeypatch.setattr(
        "hermes_cli.providers.HERMES_OVERLAYS", {"openai-codex": overlay}
    )
    monkeypatch.setattr("agent.models_dev.PROVIDER_TO_MODELS_DEV", {})
    monkeypatch.setattr(provider_rows, "_overlay_has_creds", lambda *_args: True)
    monkeypatch.setattr(
        "hermes_cli.models.cached_provider_model_ids",
        lambda slug: ["gpt-5.6-sol"] if slug == "openai-codex" else [],
    )

    build = provider_rows._PickerBuild(
        current_provider="openai-codex",
        current_base_url="",
        current_model="gpt-6-astra",
        max_models=20,
        for_picker=True,
        force_fresh_nous_tier=False,
        probe_custom_providers=False,
        probe_current_custom_provider=False,
        refresh=True,
        excluded=set(),
        curated={},
    )
    provider_rows._lap_overlay_rows(build, {})

    assert len(build.results) == 1
    assert build.results[0]["slug"] == "openai-codex"
    assert build.results[0]["models"][0] == "gpt-6-astra"
