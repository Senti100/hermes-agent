"""Focused contract tests for the native Qwen3 TTS provider."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import tools.tts_tool as tts_tool


def test_qwen3_requirements_accept_default_loopback_without_network() -> None:
    """Status polling must expose Qwen3 without probing or waking its server."""
    with patch.object(
        tts_tool,
        "_load_tts_config",
        return_value={"provider": "qwen3", "qwen3": {}},
    ), patch("requests.get", side_effect=AssertionError("network probe forbidden")), patch(
        "requests.post", side_effect=AssertionError("network probe forbidden")
    ):
        assert tts_tool.check_tts_requirements() is True


def test_qwen3_requirements_reject_non_http_url() -> None:
    with patch.object(
        tts_tool,
        "_load_tts_config",
        return_value={
            "provider": "qwen3",
            "qwen3": {"base_url": "file:///tmp/not-a-tts-proxy"},
        },
    ):
        assert tts_tool.check_tts_requirements() is False


def test_generate_qwen3_tts_sends_clone_identity_payload(tmp_path: Path) -> None:
    """The HTTP path must bind both snake/camel reference fields for proxies."""
    output_path = tmp_path / "voice.wav"
    calls: list[dict] = []

    class _Response:
        content = b"RIFF-qwen3-test"

        @staticmethod
        def raise_for_status() -> None:
            return None

    def _post(url, *, headers, json, timeout):
        calls.append(
            {
                "url": url,
                "headers": headers,
                "json": json,
                "timeout": timeout,
            }
        )
        return _Response()

    config = {
        "qwen3": {
            "base_url": "http://127.0.0.1:19380/",
            "endpoint": "/v1/audio/speech",
            "model": "Qwen3-TTS-12Hz-1.7B-Base",
            "output_format": "wav",
            "language": "English",
            "timeout": 17,
            "ref_audio": "/srv/voices/carlotta.wav",
            "ref_text": "The exact locked reference transcript.",
            "api_key_env": "",
        }
    }

    with patch("requests.post", side_effect=_post):
        result = tts_tool._generate_qwen3_tts(
            "Testing the locked voice.", str(output_path), config
        )

    assert result == str(output_path)
    assert output_path.read_bytes() == _Response.content
    assert len(calls) == 1
    call = calls[0]
    assert call["url"] == "http://127.0.0.1:19380/v1/audio/speech"
    assert call["timeout"] == 17
    assert call["headers"] == {"Content-Type": "application/json"}
    assert call["json"]["input"] == "Testing the locked voice."
    assert call["json"]["ref_audio"] == "/srv/voices/carlotta.wav"
    assert call["json"]["refAudio"] == "/srv/voices/carlotta.wav"
    assert call["json"]["ref_text"] == "The exact locked reference transcript."
    assert call["json"]["refText"] == "The exact locked reference transcript."
