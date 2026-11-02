"""Tests for user-supplied keys and the spend cap."""
import io
import logging
import os
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import budget
import muse_client
from app import keys, routes
from app.main import app
from app.security import csp_for

SECRET: str = "FAKEKEY-do-not-leak-1234567890"
ORIGIN: dict = {"Origin": "http://127.0.0.1:8000"}


def local_client() -> TestClient:
    return TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000))


def models_payload(missing: bool = False) -> dict:
    ids: list = list(keys.REQUIRED_MODELS)
    if missing:
        ids = ids[:-1]
    return {"data": [{"id": item} for item in ids]}


class FakeResponse:
    def __init__(self, status_code: int, payload: object = None, bad_json: bool = False) -> None:
        self.status_code: int = status_code
        self._payload: object = payload
        self._bad_json: bool = bad_json

    def json(self) -> object:
        if self._bad_json:
            raise ValueError("bad")
        return self._payload


def assert_no_secret(response: object) -> None:
    body: str = str(getattr(response, "text", ""))
    headers: str = str(getattr(response, "headers", {}))
    assert SECRET not in body
    assert SECRET[-8:] not in body
    assert SECRET not in headers
    assert SECRET[-8:] not in headers


def test_env_file_isolated_from_real_env(tmp_path: Path) -> None:
    assert (tmp_path in muse_client.ENV_FILE.parents) is True
    with pytest.raises(RuntimeError):
        muse_client.load_api_key()


def test_save_read_delete(tmp_path: Path) -> None:
    muse_client.save_key(SECRET)
    assert (muse_client.read_saved_key() == SECRET) is True
    assert (muse_client.load_api_key() == SECRET) is True
    assert muse_client.key_source() == "saved"
    leftovers: list = [item for item in tmp_path.iterdir() if item.name != "api_key" and "tmp" in item.name]
    assert leftovers == []
    if os.name != "nt":
        assert (muse_client.saved_key_path().stat().st_mode & 0o777) == 0o600
    assert muse_client.delete_saved_key() is True
    assert muse_client.read_saved_key() is None
    assert muse_client.delete_saved_key() is False


@pytest.mark.parametrize("value", ["has space in it 123456", "line\nbreak-1234567890", "ctrl\x01value-1234567890", "short", "your-api-key-here", "your-key-here"])
def test_is_plausible_refuses(value: str) -> None:
    assert muse_client.is_plausible_key(value) is False


def test_load_order_and_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file: Path = tmp_path / "sample.env"
    env_file.write_text("MODEL_API_KEY=envfilekey-1234567890\n", encoding="utf-8")
    monkeypatch.setattr(muse_client, "ENV_FILE", env_file)
    muse_client.save_key(SECRET)
    assert (muse_client.load_api_key() == "envfilekey-1234567890") is True
    assert muse_client.key_source() == "env_file"
    monkeypatch.setenv("MODEL_API_KEY", "envkey-123456789012")
    assert (muse_client.load_api_key() == "envkey-123456789012") is True
    assert muse_client.key_source() == "environment"
    monkeypatch.delenv("MODEL_API_KEY")
    env_file.write_text("", encoding="utf-8")
    assert (muse_client.load_api_key() == SECRET) is True
    assert muse_client.key_source() == "saved"


def test_setup_key_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    remote = TestClient(app, base_url="http://127.0.0.1:8000", client=("203.0.113.9", 50000))
    response = remote.post("/api/setup/key", headers=ORIGIN, json={"key": SECRET})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_local"
    client = local_client()
    response = client.post("/api/setup/key", json={"key": SECRET})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden_origin"
    response = client.post("/api/setup/key", headers={"Origin": "http://evil.example"}, json={"key": SECRET})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden_origin"
    response = client.post("/api/setup/key", headers={**ORIGIN, "Content-Type": "text/plain"}, content=b"{}")
    assert response.status_code == 415
    monkeypatch.setenv("MODEL_API_KEY", SECRET)
    response = client.post("/api/setup/key", headers=ORIGIN, json={"key": SECRET})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "key_from_env"
    monkeypatch.delenv("MODEL_API_KEY")
    response = client.post("/api/setup/key", headers=ORIGIN, json={"key": "bad key"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_key_format"
    assert_no_secret(response)


def test_setup_key_spoofed_host_rejected() -> None:
    client = local_client()
    response = client.post("/api/setup/key", headers={"Host": "testserver", "Origin": "http://testserver"}, json={"key": SECRET})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_local"


@pytest.mark.parametrize("result,status,code", [("invalid_key", 400, "invalid_key"), ("missing_models", 400, "key_missing_models"), ("network", 502, "network")])
def test_setup_key_check_failures_save_nothing(monkeypatch: pytest.MonkeyPatch, result: str, status: int, code: str) -> None:
    monkeypatch.setattr(keys, "check_key", lambda value: result)
    client = local_client()
    response = client.post("/api/setup/key", headers=ORIGIN, json={"key": SECRET})
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert muse_client.read_saved_key() is None
    assert_no_secret(response)


def test_setup_key_ok_saves(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(keys, "check_key", lambda value: "ok")
    client = local_client()
    response = client.post("/api/setup/key", headers=ORIGIN, json={"key": SECRET})
    assert response.status_code == 200
    assert response.headers.get("cache-control") == "no-store"
    assert (muse_client.read_saved_key() == SECRET) is True
    assert_no_secret(response)
    setup = client.get("/api/setup")
    assert setup.json() == {"has_key": True, "source": "saved", "can_change": True}
    assert_no_secret(setup)


def test_secret_never_in_responses_or_logs(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    real_check = keys.check_key
    monkeypatch.setattr(keys, "check_key", lambda value: "ok")
    client = local_client()
    responses: list = [
        client.get("/api/setup"),
        client.post("/api/setup/key", headers=ORIGIN, json={"key": SECRET}),
        client.get("/api/setup"),
        client.get("/api/status"),
        client.post("/api/sessions", json={"goal": "think"}),
        client.post("/api/setup/key", headers=ORIGIN, json={"key": "bad"}),
    ]
    for response in responses:
        assert_no_secret(response)
    def broken(url: str, **kwargs: object) -> object:
        raise RuntimeError(SECRET)
    monkeypatch.setattr(httpx, "get", broken)
    with caplog.at_level(logging.DEBUG):
        assert real_check(SECRET) == "network"
    assert SECRET not in caplog.text
    assert SECRET[-8:] not in caplog.text


def test_log_redaction_removes_secret() -> None:
    previous_factory = logging.getLogRecordFactory()
    keys.install_log_redaction()
    keys.install_log_redaction()
    keys.remember_secret(SECRET)
    keys.remember_secret("short")
    assert (keys.redact(f"a {SECRET} b") == "a [key] b") is True
    stream: io.StringIO = io.StringIO()
    handler: logging.Handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(levelname)s:%(message)s"))
    test_logger: logging.Logger = logging.getLogger("blackout.test.redaction")
    old_level: int = test_logger.level
    old_propagate: bool = test_logger.propagate
    test_logger.setLevel(logging.DEBUG)
    test_logger.propagate = False
    test_logger.addHandler(handler)
    try:
        test_logger.warning("x %s", SECRET)
        test_logger.warning(SECRET)
        try:
            raise RuntimeError(SECRET)
        except RuntimeError:
            test_logger.exception("oops")
        handler.flush()
        output: str = stream.getvalue()
        assert SECRET not in output
        assert SECRET[-8:] not in output
        assert "[key]" in output
    finally:
        test_logger.removeHandler(handler)
        test_logger.setLevel(old_level)
        test_logger.propagate = old_propagate
        logging.setLogRecordFactory(previous_factory)
        handler.close()


@pytest.mark.parametrize("response,expected", [
    (FakeResponse(200, models_payload()), "ok"),
    (FakeResponse(200, models_payload(True)), "missing_models"),
    (FakeResponse(401), "invalid_key"),
    (FakeResponse(403), "invalid_key"),
    (FakeResponse(302), "network"),
    (FakeResponse(500), "network"),
    (FakeResponse(200, bad_json=True), "network"),
])
def test_check_key_mapping(monkeypatch: pytest.MonkeyPatch, response: object, expected: str) -> None:
    seen: dict = {}
    def fake_get(url: str, **kwargs: object) -> object:
        seen.update(kwargs)
        seen["url"] = url
        return response
    monkeypatch.setattr(httpx, "get", fake_get)
    assert keys.check_key(SECRET) == expected
    assert seen["url"] == keys.META_MODELS_URL
    assert seen["follow_redirects"] is False


def test_check_key_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(url: str, **kwargs: object) -> object:
        raise RuntimeError("boom")
    monkeypatch.setattr(httpx, "get", broken)
    assert keys.check_key(SECRET) == "network"


def test_cached_status(monkeypatch: pytest.MonkeyPatch) -> None:
    keys.clear_cache()
    assert keys.cached_status() == "no_key"
    monkeypatch.setenv("MODEL_API_KEY", SECRET)
    calls: list = []
    def fake_check(value: str) -> str:
        calls.append(value)
        return "ok"
    monkeypatch.setattr(keys, "check_key", fake_check)
    assert keys.cached_status() == "ok"
    assert keys.cached_status() == "ok"
    assert len(calls) == 1
    assert SECRET not in str(keys._cache)
    keys.clear_cache()


@pytest.mark.parametrize("value,status,code", [("no_key", 409, "no_key"), ("invalid_key", 401, "key_rejected"), ("missing_models", 403, "key_missing_models"), ("network", 503, "network")])
def test_sessions_require_ok_key(monkeypatch: pytest.MonkeyPatch, value: str, status: int, code: str) -> None:
    monkeypatch.setattr(routes, "_key_status", lambda: value)
    client = local_client()
    response = client.post("/api/sessions", json={"goal": "think"})
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


def test_sessions_ok_creates() -> None:
    client = local_client()
    response = client.post("/api/sessions", json={"goal": "think"})
    assert response.status_code == 200
    assert response.json()["session_id"]


def test_csp_for() -> None:
    policy: str = csp_for("127.0.0.1:8000")
    assert "127.0.0.1:8000" in policy
    assert "ws: " not in policy
    assert "wss: " not in policy
    assert "ws://127.0.0.1:8000" in policy
    fallback: str = csp_for("bad host; evil")
    assert "connect-src 'self';" in fallback


def test_resolve_stop_at(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file: Path = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.delenv("BLACKOUT_STOP_AT_USD", raising=False)
    assert budget._resolve_stop_at(env_file) == 10.0
    monkeypatch.setenv("BLACKOUT_STOP_AT_USD", "25")
    assert budget._resolve_stop_at(env_file) == 25.0
    monkeypatch.setenv("BLACKOUT_STOP_AT_USD", "999")
    assert budget._resolve_stop_at(env_file) == 140.0
    monkeypatch.setenv("BLACKOUT_STOP_AT_USD", "nope")
    assert budget._resolve_stop_at(env_file) == 10.0
    monkeypatch.delenv("BLACKOUT_STOP_AT_USD")
    env_file.write_text("BLACKOUT_STOP_AT_USD=33\n", encoding="utf-8")
    assert budget._resolve_stop_at(env_file) == 33.0


def test_example_and_gitignore() -> None:
    root: Path = Path(__file__).resolve().parent.parent
    example: str = (root / ".env.example").read_text(encoding="utf-8")
    ignored: str = (root / ".gitignore").read_text(encoding="utf-8")
    assert "your-api-key-here" in example
    assert ".env" in ignored
    assert "api_key" in ignored
