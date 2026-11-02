"""Security middleware tests."""
import hashlib
import re
import time
from pathlib import Path
from typing import Any, Optional

import pytest
from fastapi.testclient import TestClient

import app.security as security
from app import store
from app.main import app


@pytest.fixture(autouse=True)
def setup_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLACKOUT_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("BLACKOUT_ACCESS_TOKEN", raising=False)
    # conftest allows `testserver` for the test client; individual tests
    # override BLACKOUT_ALLOWED_HOSTS when they need a different value.
    monkeypatch.delenv("BLACKOUT_RATE_LIMIT", raising=False)
    security.reset_rate_limit()
    store.clear_memory()


def test_hosts() -> None:
    client: TestClient = TestClient(app, base_url="http://bad.example")
    assert client.get("/").status_code == 400
    for base in ("http://localhost", "http://127.0.0.1:8000", "http://testserver"):
        assert TestClient(app, base_url=base).get("/").status_code == 200


def test_testserver_only_via_allowed_hosts_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # `testserver` is not in the production allow-list: with the variable
    # empty it is refused, while the always-allowed loopback hosts pass.
    monkeypatch.setenv("BLACKOUT_ALLOWED_HOSTS", "")
    assert TestClient(app, base_url="http://testserver").get("/").status_code == 400
    assert TestClient(app, base_url="http://localhost").get("/").status_code == 200
    assert TestClient(app, base_url="http://127.0.0.1:8000").get("/").status_code == 200


def test_allowed_hosts_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLACKOUT_ALLOWED_HOSTS", "phone.local,192.168.1.5")
    assert TestClient(app, base_url="http://phone.local").get("/").status_code == 200
    assert TestClient(app, base_url="http://192.168.1.5:8000").get("/").status_code == 200


def test_origin_http_and_multipart() -> None:
    client: TestClient = TestClient(app)
    foreign: Any = client.post("/api/sessions", json={"goal": "x"}, headers={"Origin": "http://evil.example"})
    assert foreign.status_code == 403 and foreign.json()["error"]["code"] == "forbidden_origin"
    multi: Any = client.post("/api/transcribe", files={"audio": ("s.wav", b"x", "audio/wav")}, headers={"Origin": "http://evil.example"})
    assert multi.status_code == 403
    same: Any = client.post("/api/sessions", json={"goal": "x"}, headers={"Origin": "http://testserver"})
    assert same.status_code == 200
    absent: Any = client.post("/api/sessions", json={"goal": "y"})
    assert absent.status_code == 200


def test_websocket_foreign_origin_refused() -> None:
    sid: str = str(store.create_session("目标")["id"])
    client: TestClient = TestClient(app)
    with pytest.raises(Exception):
        with client.websocket_connect(f"/ws/sessions/{sid}", headers={"Origin": "http://evil.example"}) as ws:
            ws.receive_json()


def test_owner_cookie_set_hashed_and_replaced() -> None:
    client: TestClient = TestClient(app)
    response: Any = client.get("/")
    assert response.status_code == 200
    set_cookie: str = response.headers.get("set-cookie", "")
    assert "blackout_owner=" in set_cookie
    assert "HttpOnly" in set_cookie and "SameSite=Lax" in set_cookie
    assert "Secure" not in set_cookie
    value: Optional[str] = client.cookies.get("blackout_owner")
    assert value and re.match(r"^[A-Za-z0-9_-]{20,64}$", value)
    # The server-side identity is the hash of the cookie, never the cookie.
    created: Any = client.post("/api/sessions", json={"goal": "目标"})
    assert created.status_code == 200
    record: Any = store.get_session(created.json()["session_id"])
    assert record["owner"] == hashlib.sha256(value.encode("utf-8")).hexdigest()
    assert record["owner"] != value
    assert value not in response.text
    # A malformed cookie is replaced with a fresh valid one. Send it as a
    # raw Cookie header on a fresh client, and check the replacement
    # through the response's set-cookie header (reading the jar would
    # raise httpx.CookieConflict once both cookies are present).
    other: TestClient = TestClient(app)
    replaced: Any = other.get("/", headers={"Cookie": "blackout_owner=bogus cookie!!"})
    assert replaced.status_code == 200
    replaced_header: str = replaced.headers.get("set-cookie", "")
    assert "blackout_owner=" in replaced_header
    match: Optional[re.Match] = re.search(r"blackout_owner=([^;]+)", replaced_header)
    assert match is not None
    new_value: str = match.group(1)
    assert new_value != "bogus cookie!!"
    assert re.match(r"^[A-Za-z0-9_-]{20,64}$", new_value)


def test_owner_cookie_secure_only_over_https() -> None:
    secure_client: TestClient = TestClient(app, base_url="https://testserver")
    secure_response: Any = secure_client.get("/")
    assert secure_response.status_code == 200
    secure_header: str = secure_response.headers.get("set-cookie", "")
    assert "blackout_owner=" in secure_header
    assert "HttpOnly" in secure_header and "SameSite=Lax" in secure_header
    assert "Secure" in secure_header


def test_token_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLACKOUT_ACCESS_TOKEN", "secret-token")
    # The token cookie is Secure, so it is only stored/sent over https;
    # the implementation is right and the client must use an https base URL.
    client: TestClient = TestClient(app, base_url="https://testserver", follow_redirects=False)
    assert client.get("/").status_code == 401
    redirected: Any = client.get("/?token=secret-token")
    assert redirected.status_code == 303
    assert "token=" not in redirected.headers["location"]
    cookie: str = redirected.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=Strict" in cookie
    following: TestClient = TestClient(app, base_url="https://testserver")
    assert following.get("/?token=secret-token").status_code == 200
    assert following.get("/").status_code == 200
    assert client.get("/?token=wrong").status_code == 401
    with pytest.raises(Exception):
        with client.websocket_connect(f"/ws/sessions/{'0' * 32}") as ws:
            ws.receive_json()


def test_token_nonascii_returns_401_not_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLACKOUT_ACCESS_TOKEN", "secret-token")
    client: TestClient = TestClient(app, base_url="https://testserver", follow_redirects=False)
    # Non-ASCII tokens must not blow up hmac.compare_digest into a 500.
    resp: Any = client.get("/?token=tökén-秘密")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"
    # The test client cannot send a non-ASCII cookie header, so exercise the
    # token comparison directly with raw non-ASCII cookie bytes.
    raw_cookie: bytes = "blackout_access_token=tökén-秘密".encode("utf-8")
    scope: Any = {"query_string": b"", "headers": [(b"cookie", raw_cookie)]}
    headers: Any = security._headers(scope)
    assert security._token_ok(scope, headers) is False


def test_token_alternative_headers_do_not_grant_access(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLACKOUT_ACCESS_TOKEN", "secret-token")
    client: TestClient = TestClient(app, base_url="https://testserver", follow_redirects=False)
    by_x_header: Any = client.get("/", headers={"x-access-token": "secret-token"})
    assert by_x_header.status_code == 401
    by_auth: Any = client.get("/", headers={"Authorization": "secret-token"})
    assert by_auth.status_code == 401
    by_bearer: Any = client.get("/", headers={"Authorization": "Bearer secret-token"})
    assert by_bearer.status_code == 401
    # Sanity: the real channels (query -> cookie) still work.
    assert client.get("/?token=secret-token").status_code == 303


def test_no_token_passes() -> None:
    assert TestClient(app).get("/api/status").status_code == 200


def test_rate_limit_and_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLACKOUT_RATE_LIMIT", "3")
    monkeypatch.setenv("BLACKOUT_RATE_WINDOW", "60")
    security.reset_rate_limit()
    client: TestClient = TestClient(app)
    codes: list = [client.get("/api/status").status_code for _ in range(4)]
    assert codes[-1] == 429
    body: Any = client.get("/api/status")
    assert body.json()["error"]["code"] == "rate_limited"
    security.reset_rate_limit()
    assert client.get("/api/status").status_code == 200


def test_rate_window_slides() -> None:
    security.reset_rate_limit()
    assert security.check_rate_limit("1.2.3.4", now=1000.0) is True
    bucket: Any = security._window_state["1.2.3.4"]
    assert bucket
    assert security.check_rate_limit("1.2.3.4", now=1000.0 + 3600) is True


def _assert_security_headers(resp: Any) -> None:
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["referrer-policy"] == "no-referrer"
    assert resp.headers["x-frame-options"] == "DENY"
    csp: str = resp.headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "blob:" in csp
    assert "frame-ancestors 'none'" in csp
    assert "base-uri 'none'" in csp
    assert "form-action 'self'" in csp


def test_headers() -> None:
    resp: Any = TestClient(app).get("/")
    _assert_security_headers(resp)


def test_headers_on_rejection_responses() -> None:
    # Host rejection (400) is answered by the middleware itself.
    bad_host: Any = TestClient(app, base_url="http://bad.example").get("/")
    assert bad_host.status_code == 400
    _assert_security_headers(bad_host)
    # Origin rejection (403) likewise.
    foreign: Any = TestClient(app).post("/api/sessions", json={"goal": "x"}, headers={"Origin": "http://evil.example"})
    assert foreign.status_code == 403
    _assert_security_headers(foreign)


def test_headers_on_redirect_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLACKOUT_ACCESS_TOKEN", "secret-token")
    client: TestClient = TestClient(app, base_url="https://testserver", follow_redirects=False)
    redirected: Any = client.get("/?token=secret-token")
    assert redirected.status_code == 303
    _assert_security_headers(redirected)


def test_chunked_post_without_content_length_is_411() -> None:
    client: TestClient = TestClient(app)
    # An iterable body makes httpx send Transfer-Encoding: chunked with
    # no Content-Length, which the middleware must refuse before reading.
    def chunks() -> Any:
        yield b'{"goal": "x"}'

    resp: Any = client.post("/api/sessions", content=chunks(), headers={"Content-Type": "application/json"})
    assert resp.status_code == 411
    assert resp.json()["error"]["code"] == "length_required"
    _assert_security_headers(resp)


def test_finish_post_without_body_passes_chunked_check() -> None:
    client: TestClient = TestClient(app)
    sid: str = client.post("/api/sessions", json={"goal": "目标"}).json()["session_id"]
    resp: Any = client.post(f"/api/sessions/{sid}/finish")
    assert resp.status_code == 200
    assert resp.json()["title"]


def test_content_length_refused_before_body() -> None:
    client: TestClient = TestClient(app)
    resp: Any = client.post("/api/sessions", content=b"x", headers={"Content-Length": "999999", "Content-Type": "application/json"})
    assert resp.status_code == 400 and resp.json()["error"]["code"] == "invalid_input"
    resp2: Any = client.post("/api/transcribe", content=b"x", headers={"Content-Length": str(100 * 1024 * 1024), "Content-Type": "multipart/form-data"})
    assert resp2.status_code == 400
    assert time.time() > 0
