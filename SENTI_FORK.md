# Senti100 Hermes Fork

This repository is a public customization fork of [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent). It is not an official Nous Research distribution.

## Purpose

The fork keeps a small, reviewable patch series for the Hermes installation operated by Senti100. Its `main` branch represents the latest **locally verified custom release**, not a mirror of upstream development `main`.

The initial bootstrap preserves the exact upstream source revision already deployed before the fork was created:

- Upstream source commit: `2d0f2185cf3bbf996128dfd5341eea1395b3aca7`
- Hermes version label at bootstrap: `v0.18.2` / `2026.7.7.2`
- Important provenance note: that source revision is newer than the `v2026.7.7.2` tag. It is retained for an exact, low-risk migration rather than silently downgrading the running installation.

After bootstrap, upstream updates are promoted only from a new official tag. Each promotion is built on a release-candidate branch, has the custom commits reapplied, and must pass tests, builds, privacy scans, and a local smoke check before `main` moves.

## Customization groups

The fork currently carries focused changes for:

- Qwen3 TTS through a configurable HTTP proxy
- User-skin ANSI banner artwork across the CLI and TUI
- Native Discord slash-command aliases
- Optional Perplexity search plugin, gated by `PERPLEXITY_API_KEY`
- Reverse-proxy-safe dashboard Host and WebSocket Origin validation using the configured dashboard public URL
- Desktop wallpaper support and the Senti_100 Packet Noir theme
- Senti_100 dashboard favicon

Changes that become available upstream should be removed from this patch series during the next tagged-release promotion.

## Configuration and public-safety policy

No real credentials, private infrastructure addresses, personal paths, customer data, or internal deployment details belong in this repository.

- **Secrets** such as API keys, tokens, and passwords belong in the active Hermes profile's local `.env` file or configured secret manager. `.env` is ignored by Git.
- **Non-secret behavior and deployment settings** belong in profile-local `config.yaml`, following Hermes' configuration conventions, rather than being hardcoded in source.
- Committed `.env.example` content may contain variable names and obvious placeholders only.
- Tests and documentation use reserved example domains and documentation address ranges instead of live infrastructure identifiers.
- Generated build output, runtime logs, profile state, BRV data, and local backups are not committed.

Before every public push, inspect the complete diff and run secret/privacy scans over both tracked content and the outgoing commits.

## Artwork provenance

`apps/desktop/src/assets/senti-100-packet-noir-bg.webp` is an AI-generated Senti_100 wallpaper created with OpenAI GPT Image for this project and selected by Senti100. It depicts a fictional adult anime nekomimi operator and contains no intended real-person likeness, readable private information, third-party logo, or watermark.

The Senti_100 favicon is original project artwork derived for this fork's public visual identity.

## Upstream update workflow

1. Fetch official tags from the `upstream` remote.
2. Wait for a newer official Hermes tag; do not promote arbitrary upstream `main` commits.
3. Create a candidate branch from the new tag.
4. Reapply or cherry-pick each still-needed customization commit.
5. Resolve conflicts and remove patches already implemented upstream.
6. Run focused Python tests, TUI/Desktop tests and builds, dashboard security tests, secret/privacy scans, and a clean-install smoke check.
7. Preserve the prior customized release branch/tag for rollback.
8. Promote the verified candidate to the fork's `main` only after review.
9. Update the live checkout from the fork and verify Hermes, the gateway, dashboard, and Desktop surfaces.

Do not use GitHub's one-click **Sync fork** action on this customized `main`; upstream synchronization is deliberate and tag-gated.
