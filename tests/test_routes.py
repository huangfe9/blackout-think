"""HTTP route tests."""
import asyncio
import json
from pathlib import Path
from typing import Any, Callable, Dict, List
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import app.conductor as conductor
import app.poster as poster_mod
import app.routes as routes
import app.sketch as sketch_mod
import app.summary as summary
from app import store
from app.main import app


@pytest.fixture(autouse=True)
def setup_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLACKOUT_DATA_DIR", str(tmp_path / "data"))
    store.clear_memory(); conductor.clear_memory()


def _wav() -> bytes:
    head: bytearray = bytearray(44); head[0:4] = b"RIFF"; head[8:12] = b"WAVE"; return bytes(head) + b"\x00\x00" * 100


def fake_for(payloads: Dict[str, Any]) -> Any:
    def make() -> Any:
        mock: MagicMock = MagicMock()
        def create(**kwargs: Any) -> Any:
            name: str = str(kwargs.get("text", {}).get("format", {}).get("name", ""))
            resp: MagicMock = MagicMock(); resp.status = "completed"
            key: str = "summary" if "summary" in name else "turn"
            resp.output_text = json.dumps(payloads[key], ensure_ascii=False); return resp
        mock.responses.create.side_effect = create; return mock
    return make


def turn(action: str = "listen") -> Dict[str, Any]:
    return {"action": action, "reply": "", "reason": "", "user_asked_ai": False, "add_points": [], "expand_points": [], "add_parking": [], "add_decisions": ["决定一"], "add_todos": [], "add_questions": [], "resolve_questions": [], "add_contradictions": [], "task": {"kind": "none", "instruction": ""}}


class CapturingExecutor:
    """Poster executor fake: records submitted work, draws nothing."""

    def __init__(self) -> None:
        self.submitted: List[Any] = []

    def submit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        self.submitted.append((fn, args, kwargs))


def _create_session(client: TestClient, goal: str = "目标") -> str:
    created: Any = client.post("/api/sessions", json={"goal": goal})
    assert created.status_code == 200
    return str(created.json()["session_id"])


def _set_poster(session_id: str, **values: Any) -> None:
    record: Any = store.get_session(session_id)
    assert record is not None
    current: Dict[str, Any] = record.get("poster") if isinstance(record.get("poster"), dict) else {}
    current.update(values)
    record["poster"] = current
    store.save_session(record)


def _poster_brief() -> Dict[str, Any]:
    return {"title": "标题", "blocks": [{"type": "list", "heading": "要点", "items": ["要点一"]}]}


def test_full_flow_and_restart() -> None:
    client: TestClient = TestClient(app)
    maker: Any = fake_for({"turn": turn(), "summary": {"title": "成果", "decisions": ["决定一"], "todos": [], "open_questions": []}})
    with patch.object(conductor, "create_client", side_effect=maker):
        with patch.object(summary, "create_client", side_effect=maker):
            created: Any = client.post("/api/sessions", json={"goal": "想清楚方案"})
            assert created.status_code == 200
            sid: str = created.json()["session_id"]
            turned: Any = client.post(f"/api/sessions/{sid}/text-turns", json={"text": "我决定这样做"})
            assert turned.status_code == 200 and turned.json()["action"] == "listen"
            finished: Any = client.post(f"/api/sessions/{sid}/finish")
            assert finished.status_code == 200 and finished.json()["decisions"] == ["决定一"]
            assert finished.json()["map"]["text"] == "想清楚方案"
    store.clear_memory(); conductor.clear_memory()
    loaded: Any = client.get(f"/api/sessions/{sid}")
    assert loaded.status_code == 200 and loaded.json()["state"]["decisions"] == ["决定一"]
    assert loaded.json()["map"]["kind"] == "goal"
    assert loaded.json()["map"]["text"] == "想清楚方案"
    # This client's address is not loopback, so spend amounts are withheld;
    # loopback-only amounts are covered in tests/test_owner.py.
    status: Any = client.get("/api/status").json()
    assert status["ledger_ok"] is True and status["can_spend"] is True
    assert "spent_usd" not in status and "limit_usd" not in status


def test_session_language_defaults_and_english() -> None:
    client: TestClient = TestClient(app)
    default_sid: str = _create_session(client, "默认目标")
    default_record: Any = client.get(f"/api/sessions/{default_sid}")
    assert default_record.status_code == 200
    assert default_record.json().get("language", "zh") == "zh"
    created_en: Any = client.post("/api/sessions", json={"goal": "Plan the launch", "language": "en"})
    assert created_en.status_code == 200
    en_sid: str = created_en.json()["session_id"]
    en_record: Any = client.get(f"/api/sessions/{en_sid}")
    assert en_record.status_code == 200
    assert en_record.json()["language"] == "en"
    assert en_record.json()["state"]["goal"] == "Plan the launch"
    # An unknown language falls back to Chinese rather than failing.
    created_bad: Any = client.post("/api/sessions", json={"goal": "目标", "language": "fr"})
    assert created_bad.status_code == 200
    bad_record: Any = client.get(f"/api/sessions/{created_bad.json()['session_id']}")
    assert bad_record.json().get("language", "zh") == "zh"


def test_transcribe_language_bias_follows_session_language() -> None:
    client: TestClient = TestClient(app)
    en_sid: str = client.post("/api/sessions", json={"goal": "Goal", "language": "en"}).json()["session_id"]
    zh_sid: str = _create_session(client, "目标")
    seen: List[Any] = []
    def fake_transcribe(data: bytes, bias: Any = None) -> str:
        seen.append(bias)
        return "transcribed words"
    maker: Any = fake_for({"turn": turn(), "summary": {}})
    with patch.object(routes, "transcribe_wav", side_effect=fake_transcribe):
        with patch.object(conductor, "create_client", side_effect=maker):
            en_resp: Any = client.post(f"/api/sessions/{en_sid}/turns", files={"audio": ("s.wav", _wav(), "audio/wav")})
            zh_resp: Any = client.post(f"/api/sessions/{zh_sid}/turns", files={"audio": ("s.wav", _wav(), "audio/wav")})
    assert en_resp.status_code == 200 and zh_resp.status_code == 200
    assert seen[0] is not None and list(seen[0])[0] == "English"
    assert seen[1] is not None and list(seen[1])[0] == "Mandarin Chinese"
    with patch.object(routes, "transcribe_wav", side_effect=fake_transcribe):
        ok_en: Any = client.post("/api/transcribe?language=en", files={"audio": ("s.wav", _wav(), "audio/wav")})
        ok_zh: Any = client.post("/api/transcribe", files={"audio": ("s.wav", _wav(), "audio/wav")})
    assert ok_en.status_code == 200 and ok_zh.status_code == 200
    assert list(seen[-2])[0] == "English"
    assert list(seen[-1])[0] == "Mandarin Chinese"


def test_envelope_and_validation() -> None:
    client: TestClient = TestClient(app)
    bad: Any = client.post("/api/sessions", json={"goal": ""})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "invalid_input"
    long_goal: Any = client.post("/api/sessions", json={"goal": "x" * 2001})
    assert long_goal.status_code == 400 and "error" in long_goal.json()
    missing: Any = client.get("/api/sessions/" + "0" * 32)
    assert missing.status_code == 404 and "error" in missing.json()
    traversal: Any = client.get("/api/sessions/..%2F..%2Fetc")
    assert traversal.status_code in (400, 404)
    invalid: Any = client.post("/api/sessions/" + "0" * 32 + "/turns")
    assert invalid.status_code == 400
    missing_turn: Any = client.post("/api/sessions/" + "0" * 32 + "/text-turns", json={"text": "hi"})
    assert missing_turn.status_code == 404
    empty_text: Any = client.post("/api/sessions", json={"goal": "g"})
    sid: str = empty_text.json()["session_id"]
    assert client.post(f"/api/sessions/{sid}/text-turns", json={"text": "  "}).status_code == 400
    assert client.post(f"/api/sessions/{sid}/text-turns", json={"text": "x" * 2001}).status_code == 400
    assert client.delete(f"/api/sessions/{sid}").status_code == 200
    assert client.get(f"/api/sessions/{sid}").status_code == 404


def test_invalid_id_404_and_no_lock_table_entry() -> None:
    client: TestClient = TestClient(app)
    locks_before: set = set(store._locks.keys())
    for raw_id in ("not-a-session", "0" * 31, "0" * 33, "g" * 32):
        resp: Any = client.get(f"/api/sessions/{raw_id}")
        assert resp.status_code == 404, raw_id
        assert resp.json()["error"]["code"] == "not_found"
        assert raw_id not in store._locks
    # A trailing newline, percent-encoded, must not slip past the id
    # check (a `$`-anchored match would accept it) or create a lock.
    newline_id: str = "0" * 32 + "\n"
    resp = client.get("/api/sessions/" + "0" * 32 + "%0a")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"
    assert newline_id not in store._locks
    assert set(store._locks.keys()) == locks_before


def test_audio_flow_and_validation() -> None:
    client: TestClient = TestClient(app)
    sid: str = client.post("/api/sessions", json={"goal": "目标"}).json()["session_id"]
    maker: Any = fake_for({"turn": turn(), "summary": {}})
    with patch.object(routes, "transcribe_wav", return_value="语音内容"):
        with patch.object(conductor, "create_client", side_effect=maker):
            resp: Any = client.post(f"/api/sessions/{sid}/turns", files={"audio": ("s.wav", _wav(), "audio/wav")})
    assert resp.status_code == 200 and resp.json()["transcript"] == "语音内容"
    bad: Any = client.post(f"/api/sessions/{sid}/turns", files={"audio": ("s.wav", b"not wav at all", "audio/wav")})
    assert bad.status_code == 400 and "error" in bad.json()
    bad2: Any = client.post("/api/transcribe", files={"audio": ("s.wav", b"nope", "audio/wav")})
    assert bad2.status_code == 400
    with patch.object(routes, "transcribe_wav", return_value="目标语音"):
        ok: Any = client.post("/api/transcribe", files={"audio": ("s.wav", _wav(), "audio/wav")})
    assert ok.status_code == 200 and ok.json() == {"transcript": "目标语音"}


def test_list_announcements_live_finish_404() -> None:
    client: TestClient = TestClient(app)
    created: Any = client.post("/api/sessions", json={"goal": "一"})
    sid: str = created.json()["session_id"]
    client.post("/api/sessions", json={"goal": "二"})
    listed: Any = client.get("/api/sessions")
    assert listed.status_code == 200 and len(listed.json()["sessions"]) == 2
    assert client.post(f"/api/sessions/{sid}/announcements").json() == {"announcements": []}
    live: Any = client.get(f"/api/sessions/{sid}/live")
    assert live.status_code == 200 and set(live.json().keys()) == {"mic", "partial", "last_user", "last_reply", "last_action", "last_reason"}
    assert client.get("/api/sessions/" + "0" * 32 + "/live").status_code == 404
    assert client.post("/api/sessions/" + "0" * 32 + "/finish").status_code == 404


def test_list_only_shows_the_callers_sessions() -> None:
    # One client is one browser: a second client must not see the first
    # client's sessions (full matrix in tests/test_owner.py).
    first: TestClient = TestClient(app)
    second: TestClient = TestClient(app)
    sid: str = _create_session(first, "我的")
    _create_session(second, "别人的")
    first_listed: Any = first.get("/api/sessions")
    assert [item["id"] for item in first_listed.json()["sessions"]] == [sid]
    second_listed: Any = second.get("/api/sessions")
    assert sid not in [item["id"] for item in second_listed.json()["sessions"]]
    assert second.get(f"/api/sessions/{sid}").status_code == 404


def test_get_session_never_exposes_owner() -> None:
    client: TestClient = TestClient(app)
    sid: str = _create_session(client)
    record: Any = client.get(f"/api/sessions/{sid}")
    assert record.status_code == 200
    assert "owner" not in record.json()
    cookie_value: str = str(client.cookies.get("blackout_owner") or "")
    assert cookie_value
    assert cookie_value not in record.text
    finished: Any = client.post(f"/api/sessions/{sid}/finish")
    assert finished.status_code == 200
    assert "owner" not in finished.json()
    assert cookie_value not in finished.text


def test_announcements_are_post_only_and_get_does_not_drain() -> None:
    client: TestClient = TestClient(app)
    sid: str = client.post("/api/sessions", json={"goal": "一"}).json()["session_id"]
    store.add_announcement(sid, "后台好了")
    # Draining mutates state, so it is POST-only: GET must not drain.
    got: Any = client.get(f"/api/sessions/{sid}/announcements")
    assert got.status_code == 405
    drained: Any = client.post(f"/api/sessions/{sid}/announcements")
    assert drained.status_code == 200
    assert drained.json() == {"announcements": [{"text": "后台好了", "kind": "announcement"}]}
    assert client.post(f"/api/sessions/{sid}/announcements").json() == {"announcements": []}
    assert client.post("/api/sessions/" + "0" * 32 + "/announcements").status_code == 404


def test_get_session_and_finish_include_map() -> None:
    client: TestClient = TestClient(app)
    sid: str = client.post("/api/sessions", json={"goal": "地图目标"}).json()["session_id"]
    record: Any = client.get(f"/api/sessions/{sid}")
    assert record.status_code == 200
    assert record.json()["map"]["kind"] == "goal"
    assert record.json()["map"]["text"] == "地图目标"
    finished: Any = client.post(f"/api/sessions/{sid}/finish")
    assert finished.status_code == 200
    assert finished.json()["map"]["kind"] == "goal"
    assert finished.json()["map"]["text"] == "地图目标"


def test_blocking_work_off_event_loop() -> None:
    client: TestClient = TestClient(app)
    sid: str = client.post("/api/sessions", json={"goal": "目标"}).json()["session_id"]
    def assert_off_loop_process(session_id: str, text: str) -> Dict[str, Any]:
        with pytest.raises(RuntimeError):
            asyncio.get_running_loop()
        return {"transcript": text, "action": "listen", "reply": "", "reason": "", "end": False, "task_started": False, "budget_exhausted": False}
    with patch.object(conductor, "process_speech", side_effect=assert_off_loop_process):
        resp: Any = client.post(f"/api/sessions/{sid}/text-turns", json={"text": "你好"})
    assert resp.status_code == 200
    def assert_off_loop_transcribe(data: bytes, *args: Any, **kwargs: Any) -> str:
        with pytest.raises(RuntimeError):
            asyncio.get_running_loop()
        return "转写结果"
    with patch.object(routes, "transcribe_wav", side_effect=assert_off_loop_transcribe):
        resp2: Any = client.post("/api/transcribe", files={"audio": ("s.wav", _wav(), "audio/wav")})
    assert resp2.status_code == 200 and resp2.json()["transcript"] == "转写结果"
    def assert_off_loop_sketch(session_id: str, data: bytes) -> Dict[str, Any]:
        with pytest.raises(RuntimeError):
            asyncio.get_running_loop()
        return {"title": "成果"}
    with patch.object(sketch_mod, "process_sketch", side_effect=assert_off_loop_sketch):
        resp3: Any = client.post(f"/api/sessions/{sid}/sketches", files={"image": ("s.png", b"\x89PNG\r\n\x1a\nxxxx", "image/png")})
    assert resp3.status_code == 200


def test_status_corrupt_ledger() -> None:
    # Amounts are loopback-only, so ask from a loopback client address.
    client: TestClient = TestClient(app, client=("127.0.0.1", 50000))
    def corrupt() -> float:
        raise ValueError("corrupt")
    with patch.object(routes.budget, "spent_usd", side_effect=corrupt):
        status: Any = client.get("/api/status")
    assert status.status_code == 200
    body: Any = status.json()
    assert body["ledger_ok"] is False and body["can_spend"] is False and body["spent_usd"] == 0.0


def test_status_amounts_only_for_loopback() -> None:
    loopback: TestClient = TestClient(app, client=("127.0.0.1", 50000))
    body: Any = loopback.get("/api/status").json()
    assert body["ledger_ok"] is True and body["can_spend"] is True
    assert {"spent_usd", "limit_usd"} <= set(body.keys())
    remote: TestClient = TestClient(app)
    remote_body: Any = remote.get("/api/status").json()
    assert remote_body["ledger_ok"] is True and remote_body["can_spend"] is True
    assert "spent_usd" not in remote_body and "limit_usd" not in remote_body


def test_get_session_returns_copy() -> None:
    client: TestClient = TestClient(app)
    sid: str = client.post("/api/sessions", json={"goal": "目标"}).json()["session_id"]
    first: Any = client.get(f"/api/sessions/{sid}").json()
    first["state"]["decisions"].append("外部改动")
    second: Any = client.get(f"/api/sessions/{sid}").json()
    assert second["state"]["decisions"] == []


# --- Poster routes ----------------------------------------------------------

def test_get_poster_404_when_none() -> None:
    client: TestClient = TestClient(app)
    sid: str = _create_session(client)
    resp: Any = client.get(f"/api/sessions/{sid}/poster")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"
    assert resp.json()["error"]["message"]


def test_get_poster_serves_png_with_no_store() -> None:
    client: TestClient = TestClient(app)
    sid: str = _create_session(client)
    png: bytes = poster_mod.PNG_SIGNATURE + b"route-poster"
    path: Any = poster_mod.poster_path(sid)
    assert path is not None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
    resp: Any = client.get(f"/api/sessions/{sid}/poster")
    assert resp.status_code == 200
    assert resp.content == png
    assert "image/png" in resp.headers.get("content-type", "")
    assert resp.headers.get("cache-control") == "no-store"


def test_get_poster_invalid_id_404_envelope() -> None:
    client: TestClient = TestClient(app)
    for raw_id in ("not-a-session", "g" * 32, "0" * 31):
        resp: Any = client.get(f"/api/sessions/{raw_id}/poster")
        assert resp.status_code == 404, raw_id
        assert resp.json()["error"]["code"] == "not_found"
    missing: Any = client.get("/api/sessions/" + "0" * 32 + "/poster")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"


def test_post_poster_409_when_already_drawing(monkeypatch: pytest.MonkeyPatch) -> None:
    client: TestClient = TestClient(app)
    executor: CapturingExecutor = CapturingExecutor()
    monkeypatch.setattr(poster_mod, "_executor", executor)
    sid: str = _create_session(client)
    _set_poster(sid, brief=_poster_brief(), status="drawing", attempts=0, version=0, error="", language="zh")
    resp: Any = client.post(f"/api/sessions/{sid}/poster")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "poster_drawing"
    assert executor.submitted == []


def test_post_poster_409_when_no_brief(monkeypatch: pytest.MonkeyPatch) -> None:
    client: TestClient = TestClient(app)
    executor: CapturingExecutor = CapturingExecutor()
    monkeypatch.setattr(poster_mod, "_executor", executor)
    sid: str = _create_session(client)
    resp: Any = client.post(f"/api/sessions/{sid}/poster")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "no_poster_brief"
    # An explicitly empty brief is also not drawable.
    _set_poster(sid, brief={"title": "t", "blocks": [{"type": "list", "heading": "", "items": []}]}, status="done")
    resp2: Any = client.post(f"/api/sessions/{sid}/poster")
    assert resp2.status_code == 409
    assert resp2.json()["error"]["code"] == "no_poster_brief"
    assert executor.submitted == []


def test_post_poster_429_at_attempt_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    client: TestClient = TestClient(app)
    executor: CapturingExecutor = CapturingExecutor()
    monkeypatch.setattr(poster_mod, "_executor", executor)
    monkeypatch.setenv("BLACKOUT_MAX_POSTERS_PER_SESSION", "2")
    sid: str = _create_session(client)
    _set_poster(sid, brief=_poster_brief(), status="failed", attempts=2, version=1, error="", language="zh")
    resp: Any = client.post(f"/api/sessions/{sid}/poster")
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "poster_limit"
    assert executor.submitted == []


def test_post_poster_success_starts_drawing_with_fake_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    client: TestClient = TestClient(app)
    executor: CapturingExecutor = CapturingExecutor()
    monkeypatch.setattr(poster_mod, "_executor", executor)
    sid: str = _create_session(client)
    _set_poster(sid, brief=_poster_brief(), status="done", attempts=0, version=1, error="", language="zh")
    resp: Any = client.post(f"/api/sessions/{sid}/poster")
    assert resp.status_code == 200
    body: Any = resp.json()
    assert body["poster"]["status"] == "drawing"
    assert body["poster"]["version"] == 1
    # The fake executor captured the job but drew nothing.
    assert len(executor.submitted) == 1
    path: Any = poster_mod.poster_path(sid)
    assert path is not None and not path.exists()
    record: Any = store.get_session(sid)
    assert record["poster"]["status"] == "drawing"
    assert record["poster"]["attempts"] == 1


def test_post_poster_invalid_and_missing_session_404() -> None:
    client: TestClient = TestClient(app)
    invalid: Any = client.post("/api/sessions/not-a-session/poster")
    assert invalid.status_code == 404
    assert invalid.json()["error"]["code"] == "not_found"
    missing: Any = client.post("/api/sessions/" + "0" * 32 + "/poster")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
