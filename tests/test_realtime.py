"""Realtime bridge tests against a local fake ASR server.

Every browser receive goes through a single per-socket reader thread that
feeds one queue, so a timed-out wait never loses a message.
"""
import asyncio
import json
import logging
import queue
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import budget
import app.conductor as conductor
import app.realtime as realtime
from app import store
from app.main import app
from tests.fake_asr import FakeASRServer


@pytest.fixture(autouse=True)
def setup_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("BLACKOUT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MODEL_API_KEY", "test-secret-key-0123456789")
    monkeypatch.setenv("BLACKOUT_TTS_TIMEOUT", "0.3")
    monkeypatch.setenv("BLACKOUT_ANNOUNCE_POLL", "0.02")
    monkeypatch.setenv("BLACKOUT_NUDGE_CHECK_INTERVAL", "0.02")
    monkeypatch.setenv("BLACKOUT_AUDIO_RECORD_INTERVAL", "0.05")
    monkeypatch.setenv("BLACKOUT_RECONNECT_FAST", "1")
    monkeypatch.setenv("BLACKOUT_COALESCE_SECONDS", "8")
    store.clear_memory()
    conductor.clear_memory()
    realtime._bridges.clear()
    yield
    realtime._bridges.clear()


def make_session() -> str:
    return str(store.create_session("想清楚方案")["id"])


def result(action: str = "listen", reply: str = "") -> Dict[str, Any]:
    return {"transcript": "", "action": action, "reply": reply, "reason": "理由", "end": False, "task_started": False, "budget_exhausted": False}


_readers: Dict[int, "queue.Queue[Any]"] = {}
_readers_lock = threading.Lock()


def _queue_for(ws: Any) -> "queue.Queue[Any]":
    """One reader thread per socket feeding one queue."""
    key: int = id(ws)
    with _readers_lock:
        existing: Any = _readers.get(key)
        if existing is not None:
            return existing
        q: "queue.Queue[Any]" = queue.Queue()
        _readers[key] = q

    def _pump() -> None:
        while True:
            try:
                msg: Any = ws.receive_json()
            except Exception as exc:
                try:
                    q.put(("closed", exc))
                except Exception:
                    pass
                break
            try:
                q.put(("message", msg))
            except Exception:
                break

    thread: threading.Thread = threading.Thread(target=_pump, daemon=True)
    thread.start()
    return q


def recv_json(ws: Any, timeout: float = 5.0) -> Dict[str, Any]:
    """Receive one JSON message; a timeout leaves later messages queued."""
    q: "queue.Queue[Any]" = _queue_for(ws)
    try:
        kind, payload = q.get(timeout=timeout)
    except queue.Empty:
        raise AssertionError(f"timed out after {timeout}s waiting for a browser WebSocket message")
    if kind == "closed":
        try:
            q.put((kind, payload))
        except Exception:
            pass
        raise payload
    return payload


def recv_until(ws: Any, kind: str, timeout: float = 5.0) -> Dict[str, Any]:
    deadline: float = time.time() + timeout
    seen: List[Any] = []
    while time.time() < deadline:
        remaining: float = deadline - time.time()
        if remaining <= 0:
            break
        try:
            data: Dict[str, Any] = recv_json(ws, timeout=max(0.1, remaining))
        except AssertionError:
            break
        seen.append(data.get("type"))
        if data.get("type") == kind:
            return data
    raise AssertionError(f"did not receive {kind!r} within {timeout}s; saw {seen}")


def expect_no_message(ws: Any, timeout: float = 0.3) -> None:
    q: "queue.Queue[Any]" = _queue_for(ws)
    try:
        kind, payload = q.get(timeout=timeout)
    except queue.Empty:
        return
    try:
        q.put((kind, payload))
    except Exception:
        pass
    if kind == "closed":
        raise payload
    raise AssertionError(f"expected no message but got {payload!r}")


def expect_socket_closed(ws: Any, timeout: float = 5.0) -> None:
    """The server closing the browser socket must surface as a receive error."""
    q: "queue.Queue[Any]" = _queue_for(ws)
    deadline: float = time.time() + timeout
    while True:
        remaining: float = deadline - time.time()
        if remaining <= 0:
            raise AssertionError(f"browser socket was not closed by the server within {timeout}s")
        try:
            kind, payload = q.get(timeout=remaining)
        except queue.Empty:
            raise AssertionError(f"browser socket was not closed by the server within {timeout}s")
        if kind == "closed":
            try:
                q.put((kind, payload))
            except Exception:
                pass
            return
        try:
            q.put((kind, payload))
        except Exception:
            pass
        raise AssertionError(f"expected the server to close the browser socket, got another message {payload!r}")


class ServerHandle:
    def __init__(self, server: FakeASRServer) -> None:
        self.server: FakeASRServer = server
        self.loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
        self.thread: Optional[threading.Thread] = None
    def start(self, monkeypatch: pytest.MonkeyPatch) -> FakeASRServer:
        ready: threading.Event = threading.Event()
        async def boot() -> None:
            await self.server.start()
            ready.set()
        self.thread = threading.Thread(target=self._run, args=(boot,), daemon=True)
        self.thread.start()
        assert ready.wait(5)
        monkeypatch.setenv("BLACKOUT_ASR_URL", self.server.url)
        return self.server
    def _run(self, boot: Any) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(boot())
        self.loop.run_forever()
    def send(self, event: Dict[str, Any]) -> None:
        asyncio.run_coroutine_threadsafe(self.server.send_event(event), self.loop).result(timeout=5)
    def close_current(self, code: int = 1011) -> None:
        asyncio.run_coroutine_threadsafe(self.server.close_current(code), self.loop).result(timeout=5)
    def stop(self) -> None:
        try:
            asyncio.run_coroutine_threadsafe(self.server.stop(), self.loop).result(timeout=5)
        except Exception:
            pass
        self.loop.call_soon_threadsafe(self.loop.stop)
        if self.thread is not None:
            self.thread.join(timeout=5)


@pytest.fixture()
def asr(monkeypatch: pytest.MonkeyPatch) -> Any:
    handles: List[ServerHandle] = []
    def factory(events: List[Dict[str, Any]], **kwargs: Any) -> ServerHandle:
        handle: ServerHandle = ServerHandle(FakeASRServer(events, **kwargs))
        handle.start(monkeypatch)
        handles.append(handle)
        return handle
    yield factory
    for handle in handles:
        handle.stop()


def wait_for(predicate: Any, timeout: float = 5.0, message: str = "condition not met") -> None:
    deadline: float = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError(message)


def test_handshake_failure_fallback(asr: Any) -> None:
    sid: str = make_session()
    asr([], fail_handshake=True)
    client: TestClient = TestClient(app)
    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        assert recv_until(ws, "fallback")["type"] == "fallback"
        expect_socket_closed(ws)


def test_turnid_zero_tick_and_say(asr: Any) -> None:
    sid: str = make_session()
    events: List[Dict[str, Any]] = [
        {"type": "speechStart", "turnId": 0},
        {"type": "transcript", "transcript": "你好", "final": False},
        {"type": "speechEnd", "turnId": 0},
        {"type": "speechComplete", "turnId": 0, "transcript": "你好世界"},
    ]
    handle: Any = asr(events)
    seen: List[str] = []
    def fake(session_id: str, text: str, now: float) -> Dict[str, Any]:
        seen.append(text)
        record: Any = store.get_session(session_id)
        record["history"].append({"role": "user", "content": text, "at": "x"})
        store.save_session(record)
        if len(seen) == 1:
            return result("listen")
        return result("answer", "继续说")
    client: TestClient = TestClient(app)
    with patch.object(conductor, "process_speech", side_effect=fake):
        with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
            assert recv_json(ws)["type"] == "ready"
            assert recv_until(ws, "tick")["type"] == "tick"
            assert seen == ["你好世界"]
            assert store.get_live(sid)["partial"] == ""
            handle.send({"type": "speechStart", "turnId": 1})
            handle.send({"type": "speechEnd", "turnId": 1})
            handle.send({"type": "speechComplete", "turnId": 1, "transcript": "第二个问题"})
            say: Dict[str, Any] = recv_until(ws, "say")
            assert say["text"] == "继续说" and say["kind"] == "reply"
            ws.send_json({"type": "tts_finished"})
    assert handle.server.handshake["model"] == "muse-voice-transcribe-1.0"


def test_partials_only_update_live(asr: Any) -> None:
    sid: str = make_session()
    handle: Any = asr([{"type": "speechStart", "turnId": 0}, {"type": "transcript", "transcript": "半句话", "final": False}])
    called: List[str] = []
    client: TestClient = TestClient(app)
    with patch.object(conductor, "process_speech", side_effect=lambda *a: called.append("x") or result()):
        with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
            recv_json(ws)
            wait_for(lambda: store.get_live(sid)["partial"] == "半句话", message="partial never reached live state")
    assert called == []
    assert handle.server.received_bytes >= 0


def test_coalesces_while_thinking(asr: Any) -> None:
    sid: str = make_session()
    handle: Any = asr([])
    calls: List[str] = []
    def fake(session_id: str, text: str, now: float) -> Dict[str, Any]:
        calls.append(text)
        if len(calls) == 1:
            time.sleep(0.4)
        return result("listen")
    client: TestClient = TestClient(app)
    with patch.object(conductor, "process_speech", side_effect=fake):
        with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
            recv_json(ws)
            for idx, text in enumerate(["第一", "第二", "第三"]):
                handle.send({"type": "speechComplete", "turnId": idx, "transcript": text})
                time.sleep(0.08)
            wait_for(lambda: len(calls) >= 2, message="queued turns were never coalesced")
    assert calls[0] == "第一"
    assert "第二" in calls[1] and "第三" in calls[1]


def test_reply_discarded_if_speech_started_during_thinking(asr: Any) -> None:
    sid: str = make_session()
    handle: Any = asr([])
    def fake(session_id: str, text: str, now: float) -> Dict[str, Any]:
        record: Any = store.get_session(session_id)
        record["history"].append({"role": "user", "content": text, "at": "x"})
        store.save_session(record)
        handle.send({"type": "speechStart", "turnId": 9})
        time.sleep(0.1)
        handle.send({"type": "speechEnd", "turnId": 9})
        return result("answer", "不应播出")
    client: TestClient = TestClient(app)
    with patch.object(conductor, "process_speech", side_effect=fake):
        with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
            recv_json(ws)
            handle.send({"type": "speechComplete", "turnId": 0, "transcript": "问题"})
            expect_no_message(ws, timeout=0.8)
    assert store.get_session(sid)["history"][0]["content"] == "问题"


def test_delivery_waits_user_and_tts_and_announcement(asr: Any) -> None:
    sid: str = make_session()
    handle: Any = asr([])
    store.add_announcement(sid, "后台好了")
    client: TestClient = TestClient(app)
    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        recv_json(ws)
        handle.send({"type": "speechStart", "turnId": 0})
        time.sleep(0.3)
        handle.send({"type": "speechEnd", "turnId": 0})
        say: Dict[str, Any] = recv_until(ws, "say")
        assert say["text"] == "后台好了"
        ws.send_json({"type": "tts_started"})
        store.add_announcement(sid, "第二条")
        time.sleep(0.3)
        ws.send_json({"type": "tts_finished"})
        assert recv_until(ws, "say")["text"] == "第二条"
        ws.send_json({"type": "tts_finished"})


def test_tts_timeout_allows_next(asr: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLACKOUT_TTS_TIMEOUT", "0.15")
    sid: str = make_session()
    asr([])
    store.add_announcement(sid, "第一条")
    store.add_announcement(sid, "第二条")
    client: TestClient = TestClient(app)
    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        recv_json(ws)
        assert recv_until(ws, "say")["text"] == "第一条"
        assert recv_until(ws, "say")["text"] == "第二条"


def test_nudges_and_pause(asr: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLACKOUT_NUDGE_SECONDS", "0.2")
    sid: str = make_session()
    asr([])
    client: TestClient = TestClient(app)
    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        recv_json(ws)
        say: Dict[str, Any] = recv_until(ws, "say")
        assert say["kind"] == "nudge"
        ws.send_json({"type": "tts_finished"})
        ws.send_json({"type": "pause"})
        wait_for(lambda: store.get_live(sid)["mic"] == "paused", message="pause never reached live state")
        ws.send_json({"type": "resume"})


def test_budget_before_connect(asr: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    sid: str = make_session()
    handle: Any = asr([])
    client: TestClient = TestClient(app)
    with patch.object(realtime.budget, "can_spend", return_value=False):
        with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
            data: Dict[str, Any] = recv_until(ws, "end")
            assert data["reason"] == "budget"
    assert handle.server.connection_count == 0


def test_audio_accounting_and_pacing(asr: Any, tmp_path: Path) -> None:
    sid: str = make_session()
    handle: Any = asr([])
    recorded: List[float] = []
    client: TestClient = TestClient(app)
    with patch.object(realtime.budget, "record_audio_seconds", side_effect=lambda s: recorded.append(s) or s * 0.18 / 3600):
        with patch.object(realtime.budget, "can_spend", return_value=True):
            with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
                recv_json(ws)
                for _ in range(100):
                    ws.send_bytes(b"\x00" * 3840)
                time.sleep(0.5)
    assert handle.server.received_bytes <= 48000 * 4
    assert recorded and abs(sum(recorded) - handle.server.received_bytes / 48000) < 0.2
    assert handle.server.end_stream_received is True


def test_reconnect_1011_and_fallback_1008(asr: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLACKOUT_RECONNECT_FAST", "1")
    sid: str = make_session()
    asr([], close_code=1011)
    client: TestClient = TestClient(app)
    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        assert recv_json(ws)["type"] == "ready"
        assert recv_until(ws, "reconnecting")["type"] == "reconnecting"
    sid2: str = make_session()
    asr([], close_code=1008)
    with client.websocket_connect(f"/ws/sessions/{sid2}") as ws:
        recv_json(ws)
        assert recv_until(ws, "fallback")["type"] == "fallback"


def test_end_phrase_once_and_key_not_sent_to_browser(asr: Any, caplog: pytest.LogCaptureFixture) -> None:
    sid: str = make_session()
    handle: Any = asr([])
    def fake(session_id: str, text: str, now: float) -> Dict[str, Any]:
        out: Dict[str, Any] = result("summarize")
        out["end"] = True
        return out
    client: TestClient = TestClient(app)
    with caplog.at_level(logging.DEBUG):
        with patch.object(conductor, "process_speech", side_effect=fake):
            with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
                recv_json(ws)
                handle.send({"type": "speechComplete", "turnId": 0, "transcript": "结束"})
                data: Dict[str, Any] = recv_until(ws, "end")
                assert data == {"type": "end", "reason": "phrase"}
                expect_socket_closed(ws)
    assert "test-secret-key-0123456789" not in caplog.text
    assert handle.server.handshake["authorization"]["accessToken"] == "Bearer test-secret-key-0123456789"


def test_1_reconnect_pacing_is_per_connection(asr: Any) -> None:
    sid: str = make_session()
    handle: Any = asr([])
    client: TestClient = TestClient(app)
    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        assert recv_json(ws)["type"] == "ready"
        ws.send_bytes(b"\x00" * 3840)
        wait_for(lambda: handle.server.connection_count >= 1 and handle.server.received_bytes_by_connection[0] > 0, message="first connection received no audio")
        handle.close_current(1011)
        assert recv_until(ws, "reconnecting")["type"] == "reconnecting"
        wait_for(lambda: handle.server.connection_count >= 2, message="no reconnect happened")
        ws.send_bytes(b"\x01" * 3840)
        wait_for(lambda: len(handle.server.received_bytes_by_connection) >= 2 and handle.server.received_bytes_by_connection[1] > 0, message="new connection received no browser audio (pacing leaked across connections?)")


def test_2a_refused_reconnects_end_in_fallback(asr: Any) -> None:
    sid: str = make_session()
    asr([], close_code=1011, fail_handshake_from=2, event_delay=0.02)
    client: TestClient = TestClient(app)
    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        assert recv_json(ws)["type"] == "ready"
        assert recv_until(ws, "fallback", timeout=8)["type"] == "fallback"
        expect_socket_closed(ws)


def test_2b_immediately_closing_reconnects_end_in_fallback(asr: Any) -> None:
    sid: str = make_session()
    asr([], close_after_handshake_code=1011, event_delay=0.02)
    client: TestClient = TestClient(app)
    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        assert recv_until(ws, "fallback", timeout=8)["type"] == "fallback"
        expect_socket_closed(ws)


def test_3_end_arriving_during_slow_turn_is_separate(asr: Any) -> None:
    sid: str = make_session()
    handle: Any = asr([])
    calls: List[str] = []
    def fake(session_id: str, text: str, now: float) -> Dict[str, Any]:
        calls.append(text)
        if len(calls) == 1:
            time.sleep(0.5)
        out: Dict[str, Any] = result("listen")
        if text.strip() == "结束":
            out = result("summarize")
            out["end"] = True
        return out
    client: TestClient = TestClient(app)
    with patch.object(conductor, "process_speech", side_effect=fake):
        with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
            assert recv_json(ws)["type"] == "ready"
            handle.send({"type": "speechComplete", "turnId": 0, "transcript": "第一句"})
            wait_for(lambda: len(calls) == 1, message="first turn never started")
            handle.send({"type": "speechComplete", "turnId": 1, "transcript": "上一句"})
            time.sleep(0.05)
            handle.send({"type": "speechComplete", "turnId": 2, "transcript": "结束"})
            data: Dict[str, Any] = recv_until(ws, "end", timeout=8)
            assert data["reason"] == "phrase"
            expect_socket_closed(ws)
    assert calls[0] == "第一句"
    assert "上一句" in calls, calls
    assert "结束" in calls, calls
    assert calls[calls.index("结束")] == "结束"
    assert all("结束" not in c or c == "结束" for c in calls), calls
    assert calls.index("上一句") < calls.index("结束")


def test_4a_silence_pump_sends_roughly_realtime(asr: Any) -> None:
    sid: str = make_session()
    handle: Any = asr([])
    client: TestClient = TestClient(app)
    started: float = time.time()
    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        assert recv_json(ws)["type"] == "ready"
        time.sleep(1.2)
        received: int = handle.server.received_bytes
        elapsed: float = time.time() - started
    expected: float = elapsed * 48000
    assert received > expected * 0.3, f"pump sent too little silence: {received} bytes in {elapsed:.2f}s"
    assert received < expected * 1.6, f"pump sent too much: {received} bytes in {elapsed:.2f}s"


def test_4b_pump_adds_almost_nothing_at_realtime(asr: Any) -> None:
    sid: str = make_session()
    handle: Any = asr([])
    client: TestClient = TestClient(app)
    frame: bytes = b"\x00" * 3840
    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        assert recv_json(ws)["type"] == "ready"
        sent: int = 0
        deadline: float = time.time() + 1.0
        while time.time() < deadline:
            ws.send_bytes(frame)
            sent += len(frame)
            time.sleep(0.08)
        time.sleep(0.2)
        received: int = handle.server.received_bytes
    assert received >= int(sent * 0.8), f"browser audio lost: sent {sent}, upstream got {received}"
    assert received <= sent + 48000 // 2, f"pump added too much on top of real-time audio: sent {sent}, upstream got {received}"


def test_5_reply_discarded_at_delivery_announcement_still_delivered(asr: Any) -> None:
    sid: str = make_session()
    handle: Any = asr([])
    def fake(session_id: str, text: str, now: float) -> Dict[str, Any]:
        return result("answer", "过时的回复")
    client: TestClient = TestClient(app)
    with patch.object(conductor, "process_speech", side_effect=fake):
        with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
            assert recv_json(ws)["type"] == "ready"
            ws.send_json({"type": "tts_started", "text": "过时的回复"})
            handle.send({"type": "speechComplete", "turnId": 0, "transcript": "问题一"})
            time.sleep(0.5)
            handle.send({"type": "speechStart", "turnId": 1})
            handle.send({"type": "transcript", "transcript": "我想换个话题说说", "final": False})
            time.sleep(0.1)
            handle.send({"type": "speechEnd", "turnId": 1})
            store.add_announcement(sid, "后台通知")
            ws.send_json({"type": "tts_finished"})
            say: Dict[str, Any] = recv_until(ws, "say", timeout=8)
            assert say["text"] == "后台通知", say
            assert say["kind"] == "announcement"
            ws.send_json({"type": "tts_finished"})
            expect_no_message(ws, timeout=0.5)


def test_6_announcements_and_nudges_note_spoken(asr: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLACKOUT_NUDGE_SECONDS", "0.2")
    sid: str = make_session()
    asr([])
    client: TestClient = TestClient(app)
    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        assert recv_json(ws)["type"] == "ready"
        first: Dict[str, Any] = recv_until(ws, "say")
        assert first["kind"] in ("nudge", "announcement")
        ws.send_json({"type": "tts_finished"})
        if first["kind"] != "nudge":
            second: Dict[str, Any] = recv_until(ws, "say")
            assert second["kind"] == "nudge"
            ws.send_json({"type": "tts_finished"})
        store.add_announcement(sid, "后台做完了")
        ann: Dict[str, Any] = recv_until(ws, "say")
        assert ann["text"] == "后台做完了"
        ws.send_json({"type": "tts_finished"})
        wait_for(lambda: store.get_session(sid) is not None and store.get_session(sid)["stats"]["nudges"] >= 1, message="nudge never reached note_spoken / stats.nudges")
    record: Any = store.get_session(sid)
    contents: List[str] = [str(h.get("content", "")) for h in record["history"] if h.get("role") == "assistant"]
    assert any("后台做完了" in c for c in contents), contents
    assert record["stats"]["ai_spoke"] >= 2


def test_7_finished_session_end_without_upstream(asr: Any) -> None:
    sid: str = make_session()
    record: Any = store.get_session(sid)
    record["status"] = "finished"
    store.save_session(record)
    handle: Any = asr([])
    client: TestClient = TestClient(app)
    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        data: Dict[str, Any] = recv_until(ws, "end")
        assert data["type"] == "end"
        expect_socket_closed(ws)
    assert handle.server.connection_count == 0


def test_8_stuck_tts_stops_blocking_delivery(asr: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(realtime, "TTS_STUCK_SECONDS", 0.3)
    sid: str = make_session()
    asr([])
    store.add_announcement(sid, "第一条消息")
    client: TestClient = TestClient(app)
    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        assert recv_json(ws)["type"] == "ready"
        assert recv_until(ws, "say")["text"] == "第一条消息"
        ws.send_json({"type": "tts_started"})
        store.add_announcement(sid, "第二条消息")
        say: Dict[str, Any] = recv_until(ws, "say", timeout=8)
        assert say["text"] == "第二条消息"
        ws.send_json({"type": "tts_finished"})


def test_10_budget_check_with_real_can_spend_and_temp_ledger(asr: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ledger: Path = tmp_path / "ledger.jsonl"
    ledger.write_text(json.dumps({"model": "muse-spark-1.3", "usd": budget.STOP_AT_USD}) + "\n", encoding="utf-8")
    monkeypatch.setattr(budget, "LEDGER_FILE", ledger)
    assert budget.can_spend() is False
    sid: str = make_session()
    handle: Any = asr([])
    client: TestClient = TestClient(app)
    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        data: Dict[str, Any] = recv_until(ws, "end")
        assert data["reason"] == "budget"
        expect_socket_closed(ws)
    assert handle.server.connection_count == 0
    ledger.write_text(json.dumps({"model": "muse-spark-1.3", "usd": 1.0}) + "\n", encoding="utf-8")
    assert budget.can_spend() is True
    sid2: str = make_session()
    handle2: Any = asr([])
    with client.websocket_connect(f"/ws/sessions/{sid2}") as ws:
        assert recv_json(ws)["type"] == "ready"
    assert handle2.server.connection_count == 1


def test_11_key_and_transcript_never_logged_or_sent(asr: Any, caplog: pytest.LogCaptureFixture) -> None:
    secret_text: str = "秘密口述内容XYZ987"
    sid: str = make_session()
    handle: Any = asr([])
    received: List[Dict[str, Any]] = []
    def fake(session_id: str, text: str, now: float) -> Dict[str, Any]:
        return result("answer", "好的继续")
    client: TestClient = TestClient(app)
    with caplog.at_level(logging.DEBUG):
        with patch.object(conductor, "process_speech", side_effect=fake):
            with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
                received.append(recv_json(ws))
                handle.send({"type": "speechStart", "turnId": 0})
                handle.send({"type": "speechEnd", "turnId": 0})
                handle.send({"type": "speechComplete", "turnId": 0, "transcript": secret_text})
                received.append(recv_until(ws, "say"))
                ws.send_json({"type": "tts_finished"})
    blob: str = json.dumps(received, ensure_ascii=False)
    assert "test-secret-key-0123456789" not in blob
    assert secret_text not in blob
    assert "test-secret-key-0123456789" not in caplog.text
    assert secret_text not in caplog.text
    assert handle.server.handshake["authorization"]["accessToken"] == "Bearer test-secret-key-0123456789"


# --- Echo and interruption ---------------------------------------------

def bridge_for(sid: str) -> Any:
    return realtime._bridges.get(sid)


def test_echo_during_playback_no_turn_no_stop_no_speaking(asr: Any) -> None:
    sid: str = make_session()
    handle: Any = asr([])
    calls: List[str] = []
    def fake(session_id: str, text: str, now: float) -> Dict[str, Any]:
        calls.append(text)
        return result("listen")
    spoken: str = "黑屏开始我在听你直接说就行"
    client: TestClient = TestClient(app)
    with patch.object(conductor, "process_speech", side_effect=fake):
        with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
            assert recv_json(ws)["type"] == "ready"
            ws.send_json({"type": "tts_started", "text": spoken})
            time.sleep(0.1)
            handle.send({"type": "speechStart", "turnId": 0})
            handle.send({"type": "transcript", "transcript": spoken, "final": False})
            handle.send({"type": "speechEnd", "turnId": 0})
            handle.send({"type": "speechComplete", "turnId": 0, "transcript": spoken})
            expect_no_message(ws, timeout=0.6)  # no tick, no say, no stop_speech
            bridge: Any = bridge_for(sid)
            assert bridge is not None and bridge.user_speaking is False
            assert bridge.speech_start_counter == 0
            ws.send_json({"type": "tts_finished"})
    assert calls == []


def test_real_partial_during_playback_stop_speech_once_and_turn(asr: Any) -> None:
    sid: str = make_session()
    handle: Any = asr([])
    calls: List[str] = []
    def fake(session_id: str, text: str, now: float) -> Dict[str, Any]:
        calls.append(text)
        return result("listen")
    client: TestClient = TestClient(app)
    with patch.object(conductor, "process_speech", side_effect=fake):
        with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
            assert recv_json(ws)["type"] == "ready"
            ws.send_json({"type": "tts_started", "text": "黑屏开始我在听你直接说就行"})
            time.sleep(0.1)
            handle.send({"type": "speechStart", "turnId": 0})
            handle.send({"type": "transcript", "transcript": "我明天一早先写提示词", "final": False})
            stop: Dict[str, Any] = recv_until(ws, "stop_speech")
            assert stop["type"] == "stop_speech"
            # A second differing partial must not send stop_speech again.
            handle.send({"type": "transcript", "transcript": "我明天一早先写提示词再开会", "final": False})
            expect_no_message(ws, timeout=0.4)
            handle.send({"type": "speechEnd", "turnId": 0})
            handle.send({"type": "speechComplete", "turnId": 0, "transcript": "我明天一早先写提示词"})
            assert recv_until(ws, "tick")["type"] == "tick"
            ws.send_json({"type": "tts_finished"})
    assert calls == ["我明天一早先写提示词"]


def test_reply_delivered_while_echo_turn_open(asr: Any) -> None:
    sid: str = make_session()
    handle: Any = asr([])
    spoken: str = "黑屏开始我在听你直接说就行"
    def fake(session_id: str, text: str, now: float) -> Dict[str, Any]:
        # While the model is thinking, an echo turn opens (suspect) and stays open.
        handle.send({"type": "speechStart", "turnId": 7})
        handle.send({"type": "transcript", "transcript": spoken, "final": False})
        time.sleep(0.2)
        return result("answer", "这是给你的回复")
    client: TestClient = TestClient(app)
    with patch.object(conductor, "process_speech", side_effect=fake):
        with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
            assert recv_json(ws)["type"] == "ready"
            ws.send_json({"type": "tts_started", "text": spoken})
            time.sleep(0.1)
            handle.send({"type": "speechComplete", "turnId": 0, "transcript": "我有个问题想问"})
            # End the entry playback; the suspect echo turn is still open,
            # but it must not block or discard the reply.
            time.sleep(0.4)
            ws.send_json({"type": "tts_finished"})
            say: Dict[str, Any] = recv_until(ws, "say", timeout=8)
            assert say["text"] == "这是给你的回复"
            ws.send_json({"type": "tts_finished"})
            # Now the echo completes and is discarded.
            handle.send({"type": "speechEnd", "turnId": 7})
            handle.send({"type": "speechComplete", "turnId": 7, "transcript": spoken})
            expect_no_message(ws, timeout=0.5)


def test_speech_start_half_second_after_tts_finished_is_suspect(asr: Any) -> None:
    sid: str = make_session()
    handle: Any = asr([])
    client: TestClient = TestClient(app)
    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        assert recv_json(ws)["type"] == "ready"
        ws.send_json({"type": "tts_started", "text": "黑屏开始我在听"})
        ws.send_json({"type": "tts_finished"})
        time.sleep(0.5)
        handle.send({"type": "speechStart", "turnId": 0})
        time.sleep(0.3)
        bridge: Any = bridge_for(sid)
        assert bridge is not None
        assert bridge.user_speaking is False, "0.5s after tts_finished must be suspect"
        assert bridge.speech_start_counter == 0
        handle.send({"type": "speechEnd", "turnId": 0})
        handle.send({"type": "speechComplete", "turnId": 0, "transcript": "黑屏开始我在听"})
        time.sleep(0.2)
        assert bridge.speech_start_counter == 0


def test_speech_start_two_seconds_after_tts_finished_not_suspect(asr: Any) -> None:
    sid: str = make_session()
    handle: Any = asr([])
    client: TestClient = TestClient(app)
    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        assert recv_json(ws)["type"] == "ready"
        ws.send_json({"type": "tts_started", "text": "黑屏开始我在听"})
        ws.send_json({"type": "tts_finished"})
        time.sleep(2.1)
        handle.send({"type": "speechStart", "turnId": 0})
        wait_for(lambda: bridge_for(sid) is not None and bridge_for(sid).user_speaking is True, message="2s after tts_finished should be a normal speaking turn")
        bridge: Any = bridge_for(sid)
        assert bridge.speech_start_counter == 1
        handle.send({"type": "speechEnd", "turnId": 0})
