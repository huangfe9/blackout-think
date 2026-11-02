"""Hardening tests: one per reviewed key-handling item, no real network."""
import asyncio
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List

import pytest
from fastapi.testclient import TestClient

import build_with_muse
import muse_client
from app import keys as keys_mod
from app.asr import AsrStream
from app.main import app

FAKE_KEY: str = "fake-test-key-1234567890abcdef"
REAL_URL: str = "wss://api.meta.ai/v1/asr/realtime"


def _fake_ws(host: Any, remote_ip: str = "157.240.1.1") -> Any:
    if host is None:
        return SimpleNamespace(remote_address=(remote_ip, 443))
    request: Any = SimpleNamespace(headers={"Host": host})
    return SimpleNamespace(request=request, remote_address=(remote_ip, 443))


def test_asr_host_check_accepts_real_api_host() -> None:
    stream: AsrStream = AsrStream(REAL_URL, FAKE_KEY)
    ws: Any = _fake_ws("api.meta.ai", remote_ip="157.240.1.1")
    assert stream._matches_expected_endpoint(ws) is True


def test_asr_host_check_accepts_real_host_any_remote() -> None:
    stream: AsrStream = AsrStream(REAL_URL, FAKE_KEY)
    ws: Any = _fake_ws("api.meta.ai", remote_ip="10.0.0.5")
    assert stream._matches_expected_endpoint(ws) is True


def test_asr_host_check_refuses_other_host() -> None:
    stream: AsrStream = AsrStream(REAL_URL, FAKE_KEY)
    ws: Any = _fake_ws("evil.example", remote_ip="157.240.1.1")
    assert stream._matches_expected_endpoint(ws) is False


def test_asr_host_check_refuses_missing_request() -> None:
    stream: AsrStream = AsrStream(REAL_URL, FAKE_KEY)
    ws: Any = SimpleNamespace(remote_address=("157.240.1.1", 443))
    assert stream._matches_expected_endpoint(ws) is False


def test_asr_host_check_matches_ip_port() -> None:
    stream: AsrStream = AsrStream("ws://127.0.0.1:61727/x", FAKE_KEY)
    ws: Any = _fake_ws("127.0.0.1:61727", remote_ip="127.0.0.1")
    assert stream._matches_expected_endpoint(ws) is True


def test_asr_redirect_never_sends_key_to_second_server() -> None:
    async def scenario() -> tuple[bool, List[Any]]:
        from websockets.asyncio.server import serve
        from websockets.datastructures import Headers
        from websockets.http11 import Response

        received: List[Any] = []

        async def target(ws: Any) -> None:
            async for message in ws:
                received.append(message)

        target_server: Any = await serve(target, "127.0.0.1", 0)
        target_port: int = int(target_server.sockets[0].getsockname()[1])

        def redirect(connection: Any, request: Any) -> Any:
            return Response(302, "Found", Headers([("Location", f"ws://127.0.0.1:{target_port}")]), b"")

        async def unused(ws: Any) -> None:
            async for message in ws:
                received.append(message)

        origin_server: Any = await serve(unused, "127.0.0.1", 0, process_request=redirect)
        origin_port: int = int(origin_server.sockets[0].getsockname()[1])
        stream: AsrStream = AsrStream(f"ws://127.0.0.1:{origin_port}", FAKE_KEY)
        try:
            ok: bool = await stream.connect()
            await asyncio.sleep(0.1)
            return ok, received
        finally:
            await stream.close()
            target_server.close()
            origin_server.close()

    ok, received = asyncio.run(scenario())
    assert ok is False
    assert received == []


def test_generator_refuses_sensitive_context_paths(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("MODEL_API_KEY=context-secret-value-123", encoding="utf-8")
    (tmp_path / ".env.local").write_text("context-secret-value-123", encoding="utf-8")
    (tmp_path / "api_key").write_text("context-secret-value-123", encoding="utf-8")
    (tmp_path / "cert.pem").write_text("context-secret-value-123", encoding="utf-8")
    (tmp_path / "cert.key").write_text("context-secret-value-123", encoding="utf-8")
    (tmp_path / "ok.txt").write_text("visible-content", encoding="utf-8")
    result: str = build_with_muse._collect_selected([".env", ".env.local", "api_key", "cert.pem", "cert.key", "../ok.txt", "/etc/passwd", str(tmp_path / "ok.txt"), "ok.txt"], root=tmp_path)
    assert "context-secret-value-123" not in result
    assert "visible-content" in result


def test_generator_raw_output_key_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(build_with_muse, "load_api_key", lambda: FAKE_KEY)
    assert build_with_muse.raw_contains_current_key("prefix " + FAKE_KEY) is True
    assert build_with_muse.raw_contains_current_key("clean output") is False


@pytest.mark.parametrize("header", ["x-forwarded-for", "forwarded", "x-real-ip", "via"])
def test_setup_key_refuses_forwarded_headers(header: str) -> None:
    client: TestClient = TestClient(app)
    response: Any = client.post("/api/setup/key", json={"key": FAKE_KEY}, headers={"Host": "127.0.0.1", "Origin": "http://127.0.0.1", header: "203.0.113.1"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_local"


def test_setup_key_refuses_non_loopback_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLACKOUT_ALLOWED_HOSTS", "testserver,example.com")
    client: TestClient = TestClient(app)
    response: Any = client.post("/api/setup/key", json={"key": FAKE_KEY}, headers={"Host": "example.com", "Origin": "http://example.com"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_local"


def test_cached_status_remembers_late_key(monkeypatch: pytest.MonkeyPatch) -> None:
    keys_mod.clear_cache()
    monkeypatch.setattr(keys_mod, "load_api_key", lambda: FAKE_KEY)
    monkeypatch.setattr(keys_mod, "check_key", lambda key: "ok")
    assert keys_mod.cached_status() == "ok"
    assert keys_mod.redact("seen " + FAKE_KEY) == "seen [key]"
    keys_mod.clear_cache()


def test_remember_secret_escaped_forms() -> None:
    value: str = 'abc"def\\ghi1234567890'
    keys_mod.remember_secret(value)
    assert value not in keys_mod.redact(json.dumps(value))
    assert "[key]" in keys_mod.redact(json.dumps(value))
    assert value not in keys_mod.redact(repr(value))
    assert "[key]" in keys_mod.redact(repr(value))


def test_env_and_file_keys_require_plausible_format(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "bad\x01key-with-plenty-length")
    assert muse_client._env_key() is None
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    env_file: Path = tmp_path / ".env"
    env_file.write_text("MODEL_API_KEY=bad-kéy-with-plenty-length\n", encoding="utf-8")
    monkeypatch.setattr(muse_client, "ENV_FILE", env_file)
    assert muse_client._file_key() is None
    assert muse_client.key_source() == "none"


@pytest.mark.parametrize("site", ["cross-site", "same-site"])
def test_sec_fetch_site_refused(site: str) -> None:
    client: TestClient = TestClient(app)
    response: Any = client.post("/api/sessions", json={"goal": "test"}, headers={"Sec-Fetch-Site": site})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden_origin"


def test_root_conftest_isolation() -> None:
    assert "MODEL_API_KEY" not in os.environ
    assert not Path(muse_client.ENV_FILE).exists()
    assert os.environ.get("BLACKOUT_KEY_FILE")


def test_gitignore_rules() -> None:
    git: str | None = shutil.which("git")
    root: Path = Path(__file__).resolve().parents[1]
    if git is None or not (root / ".git").exists():
        pytest.skip("git not available")
    ignored: List[str] = ["some.env", ".env", ".envrc", ".api_key.abc.tmp", "my_api_key.txt", "mysecret.txt", "credentials123.json", ".venv/lib.py", "venv/lib.py"]
    for path in ignored:
        proc: Any = subprocess.run([git, "check-ignore", "--quiet", "--", path], cwd=str(root))
        assert proc.returncode == 0, path
    proc_example: Any = subprocess.run([git, "check-ignore", "--quiet", "--", ".env.example"], cwd=str(root))
    assert proc_example.returncode != 0


def test_saved_key_path_refuses_repo_location(monkeypatch: pytest.MonkeyPatch) -> None:
    inside: Path = Path(muse_client.__file__).resolve().parent / "api_key"
    monkeypatch.setenv("BLACKOUT_KEY_FILE", str(inside))
    assert muse_client.saved_key_path() != inside


def test_save_key_only_chmods_created_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if os.name == "nt":
        pytest.skip("posix modes only")
    existing: Path = tmp_path / "existing"
    existing.mkdir()
    os.chmod(existing, 0o755)
    monkeypatch.setenv("BLACKOUT_KEY_FILE", str(existing / "api_key"))
    muse_client.save_key(FAKE_KEY)
    assert stat.S_IMODE(existing.stat().st_mode) == 0o755
    created: Path = tmp_path / "created"
    monkeypatch.setenv("BLACKOUT_KEY_FILE", str(created / "api_key"))
    muse_client.save_key(FAKE_KEY)
    assert stat.S_IMODE(created.stat().st_mode) == 0o700


def test_delete_saved_key_removes_tmp_leftovers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder: Path = tmp_path / "keys"
    monkeypatch.setenv("BLACKOUT_KEY_FILE", str(folder / "api_key"))
    muse_client.save_key(FAKE_KEY)
    leftover: Path = folder / ".api_key.abc123.tmp"
    leftover.write_text("partial", encoding="utf-8")
    assert muse_client.delete_saved_key() is True
    assert not (folder / "api_key").exists()
    assert not leftover.exists()
