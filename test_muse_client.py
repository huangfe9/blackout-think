"""Tests for muse_client.py key loading and transcription."""
import json
import os
from pathlib import Path
from typing import Any

import pytest

import muse_client
from muse_client import BASE_URL, KEY_NAME, PLACEHOLDER, load_api_key, read_key_from_env_file, transcribe_wav


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def test_read_simple(tmp_path: Path) -> None:
    p: Path = tmp_path / ".env"
    _write(p, "MODEL_API_KEY=abc123-0123456789abcdef\n")
    assert read_key_from_env_file(p) == "abc123-0123456789abcdef"


def test_read_bom_quotes_spaces(tmp_path: Path) -> None:
    p: Path = tmp_path / ".env"
    p.write_bytes("\ufeffMODEL_API_KEY  =  \"secret-xyz-0123456789abcdef\"  \n".encode("utf-8"))
    assert read_key_from_env_file(p) == "secret-xyz-0123456789abcdef"
    p2: Path = tmp_path / ".env2"
    _write(p2, "MODEL_API_KEY='quoted-key-0123456789abcdef'\n")
    assert read_key_from_env_file(p2) == "quoted-key-0123456789abcdef"


def test_read_empty_returns_none(tmp_path: Path) -> None:
    p: Path = tmp_path / ".env"
    _write(p, "MODEL_API_KEY=\n")
    assert read_key_from_env_file(p) is None


def test_read_missing_returns_none(tmp_path: Path) -> None:
    assert read_key_from_env_file(tmp_path / "nope.env") is None


def test_read_ignores_other_keys(tmp_path: Path) -> None:
    p: Path = tmp_path / ".env"
    _write(p, "OTHER=1\nMODEL_API_KEY=good-key-0123456789abcdef\n")
    assert read_key_from_env_file(p) == "good-key-0123456789abcdef"


def test_env_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(KEY_NAME, "env-key-0123456789abcdef")
    monkeypatch.setattr(muse_client, "read_key_from_env_file", lambda *args: "file-key-0123456789abcdef")
    assert load_api_key() == "env-key-0123456789abcdef"


def test_placeholder_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(KEY_NAME, raising=False)
    monkeypatch.setattr(muse_client, "read_key_from_env_file", lambda *args: PLACEHOLDER)
    with pytest.raises(RuntimeError) as exc:
        load_api_key()
    msg: str = str(exc.value)
    assert msg.startswith("MODEL_API_KEY is not set")
    assert "https://dev.meta.ai/api-keys/" in msg
    assert ".env" in msg


def test_missing_key_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(KEY_NAME, raising=False)
    monkeypatch.setattr(muse_client, "read_key_from_env_file", lambda *args: None)
    with pytest.raises(RuntimeError) as exc:
        load_api_key()
    assert str(exc.value).startswith("MODEL_API_KEY is not set")
    assert "https://dev.meta.ai/api-keys/" in str(exc.value)


def test_file_key_used_when_env_has_placeholder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(KEY_NAME, PLACEHOLDER)
    monkeypatch.setattr(muse_client, "read_key_from_env_file", lambda *args: "file-key-0123456789abcdef")
    assert load_api_key() == "file-key-0123456789abcdef"


def test_base_url_correct() -> None:
    assert BASE_URL == "https://api.meta.ai/v1"
    assert muse_client.DEFAULT_ENV_FILE.name == ".env"
    assert muse_client.DEFAULT_ENV_FILE.parent == Path(muse_client.__file__).parent
    assert os.environ.get("UNUSED_SENTINEL_XYZ") is None


def test_transcribe_wav_sends_mandarin_chinese(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None
        def json(self) -> dict[str, str]:
            return {"transcript": "\u4f60\u597d"}
    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass
        def __enter__(self) -> "FakeClient":
            return self
        def __exit__(self, *args: Any) -> None:
            return None
        def post(self, url: str, files: Any = None, headers: Any = None) -> FakeResponse:
            captured["url"] = url
            captured["files"] = files
            captured["headers"] = headers
            return FakeResponse()
    monkeypatch.setattr(muse_client, "BudgetedHttpClient", FakeClient)
    monkeypatch.setattr(muse_client, "load_api_key", lambda: "test-key-0123456789abcdef")
    assert transcribe_wav(b"RIFFxxxxWAVE") == "\u4f60\u597d"
    payload: Any = captured["files"]["request"][1]
    settings: Any = json.loads(payload)
    assert "Mandarin Chinese" in settings["languageBias"]
    assert "Chinese" not in [x for x in settings["languageBias"] if x == "Chinese"]
    assert captured["headers"]["Authorization"] == "Bearer test-key-0123456789abcdef"
