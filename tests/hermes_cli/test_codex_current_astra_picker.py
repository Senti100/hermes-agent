"""Fork policy for keeping an explicitly configured Astra model visible."""

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