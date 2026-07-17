from __future__ import annotations

from pathlib import Path

import requests

from agent import tts_registry
from tools import tts_tool


class _Response:
    def __init__(self, content: bytes = b"RIFF-test-audio") -> None:
        self.content = content
        self.raise_called = False

    def raise_for_status(self) -> None:
        self.raise_called = True


def test_qwen3_is_reserved_as_a_builtin_provider() -> None:
    assert "qwen3" in tts_registry._BUILTIN_NAMES
    assert "qwen3" in tts_tool.BUILTIN_TTS_PROVIDERS


def test_generate_qwen3_tts_uses_profile_config_and_secret_env(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}
    response = _Response()

    def fake_post(url, *, headers, json, timeout):
        captured.update(
            url=url,
            headers=headers,
            json=json,
            timeout=timeout,
        )
        return response

    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr(
        tts_tool,
        "get_env_value",
        lambda name: "unit-test-key" if name == "HERMES_QWEN3_TTS_API_KEY" else None,
    )

    output = tmp_path / "speech.wav"
    result = tts_tool._generate_qwen3_tts(
        "hello from Hermes",
        str(output),
        {
            "qwen3": {
                "base_url": "https://tts.example.com/",
                "endpoint": "/v1/audio/speech",
                "model": "qwen3-tts-test",
                "voice": "operator-test",
                "output_format": "wav",
                "language": "English",
                "timeout": 45,
                "ref_audio": "https://assets.example.com/reference.wav",
                "ref_text": "public test reference",
                "api_key_env": "HERMES_QWEN3_TTS_API_KEY",  # gitleaks:allow -- key name
            }
        },
    )

    assert result == str(output)
    assert output.read_bytes() == b"RIFF-test-audio"
    assert response.raise_called is True
    assert captured["url"] == "https://tts.example.com/v1/audio/speech"
    assert captured["timeout"] == 45
    assert captured["headers"] == {
        "Content-Type": "application/json",
        "Authorization": "Bearer unit-test-key",
    }
    assert captured["json"] == {
        "input": "hello from Hermes",
        "output_format": "wav",
        "language": "English",
        "model": "qwen3-tts-test",
        "voice": "operator-test",
        "ref_audio": "https://assets.example.com/reference.wav",
        "refAudio": "https://assets.example.com/reference.wav",
        "ref_text": "public test reference",
        "refText": "public test reference",
    }


def test_generate_qwen3_tts_omits_authorization_without_configured_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_post(url, *, headers, json, timeout):
        captured.update(url=url, headers=headers, json=json, timeout=timeout)
        return _Response()

    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr(tts_tool, "get_env_value", lambda _name: None)

    output = tmp_path / "speech.wav"
    tts_tool._generate_qwen3_tts(
        "hello",
        str(output),
        {"qwen3": {"base_url": "http://127.0.0.1:19380"}},
    )

    assert captured["url"] == "http://127.0.0.1:19380/v1/audio/speech"
    assert captured["headers"] == {"Content-Type": "application/json"}
