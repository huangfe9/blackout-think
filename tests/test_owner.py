"""Per-browser ownership tests (stage 7).

Two separate ``TestClient`` instances are two browsers: each has its own
cookie jar.  The server must give each browser an opaque ``blackout_owner``
cookie, store only its hash, show a browser only its own sessions, and make
another browser's session indistinguishable from a missing session on every
route -- including the WebSocket -- without spending anything.
"""
import asyncio
import hashlib
import json
import re
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import app.conductor as conductor
import app.poster as poster_mod
import app.routes as routes
import app.sketch as sketch_mod
import app.summary as summary
from app import store
from app.main import app
from tests.fake_asr import FakeASRServer

OWNER_COOKIE: str = "blackout_owner"
OWNER_VALUE_RE: re.Pattern = re.compile(r"^[A-Za-z0-9_-]{20,64}$")
NOT_FOUND_BODY: Dict[str, Any] = {"error": {"code": "not_found", "message": "会话不存在，请重新开始。"}}


def _client(**kwargs: Any) -> TestClient:
    return TestClient(app, **kwargs)


def _owner_cookie(client: TestClient) -> str:
    value: Optional[str] = client.cookies.get(OWNER_COOKIE)
    assert value, "client has no blackout_owner cookie"
    return str(value)


def _set_cookie_header(response: Any) -> str:
    headers: Any = response.headers
    if hasattr(headers, "get_list"):
        values: List[str] = list(headers.get_list("set-cookie"))
    else:
        raw: str = headers.get("set-cookie", "")
        values = [raw] if raw else []
    for value in values:
        if value.startswith(OWNER_COOKIE + "="):
            return value
    return ""


def _owner_value_from_set_cookie(header: str) -> str:
    match: Optional[re.Match] = re.search(OWNER_COOKIE + r"=([^;]+)", header)
    assert match is not None, header
    return match.group(1)


def _create_session(client: TestClient, goal: str = "我的目标") -> str:
    created: Any = client.post("/api/sessions", json={"goal": goal})
    assert created.status_code == 200, created.text
    return str(created.json()["session_id"])


def _wav() -> bytes:
    head: bytearray = bytearray(44)
    head[0:4] = b"RIFF"
    head[8:12] = b"WAVE"
    return bytes(head) + b"\x00\x00" * 100


# --- The owner cookie itself -------------------------------------------------

def test_first_request_sets_owner_cookie_http() -> None:
    client: TestClient = _client()
    response: Any = client.get("/")
    assert response.status_code == 200
    header: str = _set_cookie_header(response)
    assert header, "first response must set the owner cookie"
    assert "HttpOnly" in header
    assert "SameSite=Lax" in header
    assert "Secure" not in header
    value: str = _owner_cookie(client)
    assert OWNER_VALUE_RE.match(value), value


def test_first_request_sets_owner_cookie_secure_over_https() -> None:
    client: TestClient = _client(base_url="https://testserver")
    response: Any = client.get("/")
    assert response.status_code == 200
    header: str = _set_cookie_header(response)
    assert header, "first response must set the owner cookie"
    assert "HttpOnly" in header
    assert "SameSite=Lax" in header
    assert "Secure" in header
    assert OWNER_VALUE_RE.match(_owner_cookie(client))


def test_owner_cookie_is_stable_across_requests() -> None:
    client: TestClient = _client()
    client.get("/")
    first: str = _owner_cookie(client)
    response: Any = client.get("/api/sessions")
    assert response.status_code == 200
    assert _owner_cookie(client) == first
    # A valid cookie is not needlessly rotated.
    assert OWNER_COOKIE not in _set_cookie_header(response)


def test_stored_owner_is_a_hash_not_the_cookie_value() -> None:
    client: TestClient = _client()
    session_id: str = _create_session(client)
    cookie_value: str = _owner_cookie(client)
    record: Optional[Dict[str, Any]] = store.get_session(session_id)
    assert record is not None
    stored: str = str(record.get("owner", ""))
    assert stored
    assert stored != cookie_value
    assert stored == hashlib.sha256(cookie_value.encode("utf-8")).hexdigest()


def test_malformed_owner_cookie_is_replaced() -> None:
    client: TestClient = _client()
    response: Any = client.get("/", headers={"Cookie": f"{OWNER_COOKIE}=not a valid owner!!"})
    assert response.status_code == 200
    header: str = _set_cookie_header(response)
    assert header, "a malformed owner cookie must be replaced"
    value: str = _owner_value_from_set_cookie(header)
    assert value != "not a valid owner!!"
    assert OWNER_VALUE_RE.match(value), value
    # The replacement owner works: it can create and list its own session.
    session_id: str = _create_session(client)
    listed: Any = client.get("/api/sessions")
    assert [item["id"] for item in listed.json()["sessions"]] == [session_id]


def test_empty_owner_cookie_is_replaced() -> None:
    client: TestClient = _client()
    response: Any = client.get("/", headers={"Cookie": f"{OWNER_COOKIE}="})
    assert response.status_code == 200
    header: str = _set_cookie_header(response)
    assert header, "an empty owner cookie must be replaced"
    value: str = _owner_value_from_set_cookie(header)
    assert OWNER_VALUE_RE.match(value), value


# --- Listing isolation ---------------------------------------------------------

def test_sessions_are_listed_only_for_their_owner() -> None:
    alice: TestClient = _client()
    bob: TestClient = _client()
    alice_id: str = _create_session(alice, "爱丽丝的目标")
    bob_id: str = _create_session(bob, "鲍勃的目标")
    alice_list: Any = alice.get("/api/sessions")
    assert alice_list.status_code == 200
    assert [item["id"] for item in alice_list.json()["sessions"]] == [alice_id]
    assert alice_list.json()["sessions"][0]["goal"] == "爱丽丝的目标"
    bob_list: Any = bob.get("/api/sessions")
    assert bob_list.status_code == 200
    assert [item["id"] for item in bob_list.json()["sessions"]] == [bob_id]
    assert bob_list.json()["sessions"][0]["goal"] == "鲍勃的目标"


def test_client_with_no_cookie_gets_an_empty_list() -> None:
    alice: TestClient = _client()
    _create_session(alice)
    fresh: TestClient = _client()
    assert fresh.cookies.get(OWNER_COOKIE) is None
    listed: Any = fresh.get("/api/sessions")
    assert listed.status_code == 200
    assert listed.json() == {"sessions": []}


# --- Every route treats another browser's session as missing -------------------

def test_foreign_session_is_404_on_every_route_without_spend() -> None:
    alice: TestClient = _client()
    bob: TestClient = _client()
    session_id: str = _create_session(alice)
    missing_id: str = "0" * 32
    turn_client: MagicMock = MagicMock(side_effect=AssertionError("model called for foreign session"))
    summary_client: MagicMock = MagicMock(side_effect=AssertionError("model called for foreign session"))
    sketch_call: MagicMock = MagicMock(side_effect=AssertionError("model called for foreign session"))
    transcribe_call: MagicMock = MagicMock(side_effect=AssertionError("transcribe called for foreign session"))
    poster_submit: MagicMock = MagicMock(side_effect=AssertionError("poster started for foreign session"))
    with patch.object(conductor, "create_client", turn_client):
        with patch.object(summary, "create_client", summary_client):
            with patch.object(sketch_mod, "process_sketch", sketch_call):
                with patch.object(routes, "transcribe_wav", transcribe_call):
                    with patch.object(poster_mod, "start_poster", poster_submit):
                        checks: List[Any] = [
                            bob.get(f"/api/sessions/{session_id}"),
                            bob.get(f"/api/sessions/{session_id}/live"),
                            bob.post(f"/api/sessions/{session_id}/announcements"),
                            bob.post(f"/api/sessions/{session_id}/text-turns", json={"text": "你好"}),
                            bob.post(f"/api/sessions/{session_id}/turns", files={"audio": ("s.wav", _wav(), "audio/wav")}),
                            bob.post(f"/api/sessions/{session_id}/finish"),
                            bob.get(f"/api/sessions/{session_id}/poster"),
                            bob.post(f"/api/sessions/{session_id}/poster"),
                            bob.post(f"/api/sessions/{session_id}/sketches", files={"image": ("s.png", b"\x89PNG\r\n\x1a\nxxxx", "image/png")}),
                            bob.delete(f"/api/sessions/{session_id}"),
                        ]
    for response in checks:
        assert response.status_code == 404, response.text
        assert response.json() == NOT_FOUND_BODY, response.text
    turn_client.assert_not_called()
    summary_client.assert_not_called()
    sketch_call.assert_not_called()
    transcribe_call.assert_not_called()
    poster_submit.assert_not_called()
    # The foreign attempts did nothing: the owner still has the session,
    # untouched, and a genuinely missing session looks exactly the same.
    owned: Any = alice.get(f"/api/sessions/{session_id}")
    assert owned.status_code == 200
    assert owned.json()["history"] == []
    assert owned.json()["status"] == "active"
    missing: Any = bob.get(f"/api/sessions/{missing_id}")
    assert missing.status_code == 404
    assert missing.json() == NOT_FOUND_BODY


def test_foreign_404_matches_missing_404_for_write_routes() -> None:
    alice: TestClient = _client()
    bob: TestClient = _client()
    session_id: str = _create_session(alice)
    missing_id: str = "0" * 32
    foreign: Any = bob.post(f"/api/sessions/{session_id}/text-turns", json={"text": "你好"})
    missing: Any = bob.post(f"/api/sessions/{missing_id}/text-turns", json={"text": "你好"})
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json() == NOT_FOUND_BODY
    foreign_finish: Any = bob.post(f"/api/sessions/{session_id}/finish")
    missing_finish: Any = bob.post(f"/api/sessions/{missing_id}/finish")
    assert foreign_finish.status_code == missing_finish.status_code == 404
    assert foreign_finish.json() == missing_finish.json() == NOT_FOUND_BODY


# --- WebSocket ownership, against the fake upstream ----------------------------

class _RunningFakeASR:
    """Run the async fake speech server on its own thread and event loop."""

    def __init__(self) -> None:
        self.server: FakeASRServer = FakeASRServer()
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.thread: Optional[threading.Thread] = None
        self._ready: threading.Event = threading.Event()

    @property
    def url(self) -> str:
        return self.server.url

    def __enter__(self) -> "_RunningFakeASR":
        def run() -> None:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.loop.run_until_complete(self.server.start())
            self._ready.set()
            assert self.loop is not None
            self.loop.run_forever()

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        assert self._ready.wait(timeout=10), "fake ASR server did not start"
        return self

    def __exit__(self, *args: Any) -> None:
        if self.loop is not None:
            future: Any = asyncio.run_coroutine_threadsafe(self.server.stop(), self.loop)
            try:
                future.result(timeout=10)
            except Exception:
                pass
            self.loop.call_soon_threadsafe(self.loop.stop)
        if self.thread is not None:
            self.thread.join(timeout=10)


def _patch_asr_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give the bridge a fake key through whichever seam it exposes."""
    for env_name in ("MUSE_API_KEY", "META_API_KEY", "META_AI_API_KEY", "MUSE_SPARK_API_KEY", "API_KEY"):
        monkeypatch.setenv(env_name, "test-key")
    fake_client: SimpleNamespace = SimpleNamespace(api_key="test-key", key="test-key", access_token="test-key")
    try:
        import app.realtime as realtime_mod
    except Exception:
        return
    for name in dir(realtime_mod):
        if name in ("create_client",):
            monkeypatch.setattr(realtime_mod, name, lambda *a, **k: fake_client, raising=False)
        elif name in ("get_api_key", "api_key", "get_key", "load_api_key", "_api_key", "get_access_token"):
            monkeypatch.setattr(realtime_mod, name, lambda *a, **k: "test-key", raising=False)


def test_foreign_and_cookieless_websockets_close_1008_without_upstream(monkeypatch: pytest.MonkeyPatch) -> None:
    alice: TestClient = _client()
    bob: TestClient = _client()
    session_id: str = _create_session(alice)
    bob.get("/")  # Bob is a real second browser, with his own owner cookie.
    assert _owner_cookie(bob) != _owner_cookie(alice)
    with _RunningFakeASR() as fake:
        monkeypatch.setenv("BLACKOUT_ASR_URL", fake.url)
        _patch_asr_key(monkeypatch)
        with pytest.raises(WebSocketDisconnect) as foreign_exc:
            with bob.websocket_connect(f"/ws/sessions/{session_id}") as ws:
                ws.receive_json()
        assert foreign_exc.value.code == 1008
        stranger: TestClient = _client()
        assert stranger.cookies.get(OWNER_COOKIE) is None
        with pytest.raises(WebSocketDisconnect) as stranger_exc:
            with stranger.websocket_connect(f"/ws/sessions/{session_id}") as ws:
                ws.receive_json()
        assert stranger_exc.value.code == 1008
        # Neither rejection ever reached the speech service.
        assert fake.server.connection_count == 0
        assert fake.server.received_bytes == 0


def test_owner_websocket_works(monkeypatch: pytest.MonkeyPatch) -> None:
    alice: TestClient = _client()
    session_id: str = _create_session(alice)
    with _RunningFakeASR() as fake:
        monkeypatch.setenv("BLACKOUT_ASR_URL", fake.url)
        _patch_asr_key(monkeypatch)
        with alice.websocket_connect(f"/ws/sessions/{session_id}") as ws:
            message: Any = ws.receive_json()
        assert message.get("type") == "ready", message
        assert fake.server.connection_count == 1
        assert fake.server.handshake is not None


# --- Ownerless (pre-ownership) sessions -----------------------------------------

def test_ownerless_session_is_unlisted_but_reachable_by_exact_id() -> None:
    record: Dict[str, Any] = store.create_session("以前的目标")
    session_id: str = str(record["id"])
    assert not record.get("owner")
    alice: TestClient = _client()
    bob: TestClient = _client()
    _create_session(alice, "现在的目标")
    for client in (alice, bob):
        listed: Any = client.get("/api/sessions")
        assert listed.status_code == 200
        assert session_id not in [item["id"] for item in listed.json()["sessions"]]
        reached: Any = client.get(f"/api/sessions/{session_id}")
        assert reached.status_code == 200, reached.text
        assert reached.json()["state"]["goal"] == "以前的目标"
    fresh: TestClient = _client()
    assert fresh.get("/api/sessions").json() == {"sessions": []}
    assert fresh.get(f"/api/sessions/{session_id}").status_code == 200


# --- The owner value never leaks --------------------------------------------------

def test_no_response_body_contains_owner_field_or_cookie_value() -> None:
    alice: TestClient = _client()
    session_id: str = _create_session(alice)
    cookie_value: str = _owner_cookie(alice)
    responses: List[Any] = [
        alice.post("/api/sessions", json={"goal": "另一个目标"}),
        alice.get("/api/sessions"),
        alice.get(f"/api/sessions/{session_id}"),
        alice.get(f"/api/sessions/{session_id}/live"),
        alice.post(f"/api/sessions/{session_id}/announcements"),
        alice.post(f"/api/sessions/{session_id}/finish"),
        alice.get("/api/status"),
        alice.get("/"),
    ]
    for response in responses:
        assert cookie_value not in response.text, response.text
        assert '"owner"' not in response.text, response.text
    record_response: Any = alice.get(f"/api/sessions/{session_id}")
    assert "owner" not in record_response.json()


def test_session_file_on_disk_does_not_contain_raw_cookie_value() -> None:
    alice: TestClient = _client()
    session_id: str = _create_session(alice)
    cookie_value: str = _owner_cookie(alice)
    path: Optional[Path] = store.session_path(session_id)
    assert path is not None and path.is_file()
    on_disk: str = path.read_text(encoding="utf-8")
    assert cookie_value not in on_disk
    parsed: Dict[str, Any] = json.loads(on_disk)
    assert parsed["owner"] == hashlib.sha256(cookie_value.encode("utf-8")).hexdigest()


# --- Money visibility --------------------------------------------------------------

def test_status_gives_spent_usd_to_loopback_clients_only() -> None:
    loopback: TestClient = _client(client=("127.0.0.1", 50000))
    local: Any = loopback.get("/api/status")
    assert local.status_code == 200
    assert "spent_usd" in local.json()
    assert "limit_usd" in local.json()
    assert isinstance(local.json()["spent_usd"], (int, float))
    remote: TestClient = _client()
    other: Any = remote.get("/api/status")
    assert other.status_code == 200
    assert "spent_usd" not in other.json()
    assert "limit_usd" not in other.json()
    assert other.json()["ledger_ok"] is True
    assert other.json()["can_spend"] is True
