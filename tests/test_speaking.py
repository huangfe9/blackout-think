"""Stage 8B: conflict questions, reflections, and spoken failures."""
import asyncio
import json
import urllib.parse
import uuid
from typing import Any, Dict

import pytest

from app import asr, conductor, store
from app import state as state_mod
from app.messages import message


def _parsed(**overrides: Any) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "action": "listen", "reply": "", "reason": "", "user_asked_ai": False,
        "conflict_question": "", "add_points": [], "expand_points": [], "add_parking": [],
        "add_decisions": [], "add_todos": [], "add_questions": [], "resolve_questions": [],
        "add_contradictions": [], "task": {"kind": "none", "instruction": "", "under": ""},
    }
    data.update(overrides)
    return data


def _make_session(tmp_path: Any, monkeypatch: Any, goal: str = "想清楚方案", language: str = "zh") -> str:
    monkeypatch.setenv("BLACKOUT_DATA_DIR", str(tmp_path))
    conductor.clear_memory()
    session_id: str = uuid.uuid4().hex
    record: Dict[str, Any] = {
        "id": session_id, "created_at": store.now_iso(), "updated_at": store.now_iso(),
        "status": "active", "language": language,
        "state": state_mod.new_state(goal), "history": [], "tasks": [], "sketches": [],
        "result": None,
        "stats": {"user_turns": 0, "ai_spoke": 0, "listened": 0, "pull_backs": 0, "nudges": 0},
    }
    store.save_session(record)
    return session_id


def _fake(monkeypatch: Any, parsed: Dict[str, Any]) -> None:
    def fake(record: Dict[str, Any], text: str, seconds: Any) -> Dict[str, Any]:
        return dict(parsed)
    monkeypatch.setattr(conductor, "_call_model_once", fake)


def _record(session_id: str) -> Dict[str, Any]:
    record = store.get_session(session_id)
    assert record is not None
    return record


def _history_texts(session_id: str) -> list:
    return [str(item.get("content", "")) for item in _record(session_id).get("history", []) if item.get("role") == "user"]


def test_conflict_question_becomes_follow_up_and_counts(tmp_path: Any, monkeypatch: Any) -> None:
    session_id = _make_session(tmp_path, monkeypatch)
    question = "你刚说每周十小时，现在说二十，按哪个算？"
    _fake(monkeypatch, _parsed(conflict_question=question))
    result = conductor.process_speech(session_id, "一周至少二十个小时", now=1000.0)
    assert result["action"] == "follow_up"
    assert result["reply"] == question
    assert result["reason"] == "前后不一致"
    record = _record(session_id)
    assert record["stats"]["conflicts_asked"] == 1
    assert record["asked_conflicts"] == [question]


def test_same_conflict_asked_once_and_fourth_not_asked(tmp_path: Any, monkeypatch: Any) -> None:
    session_id = _make_session(tmp_path, monkeypatch)
    monkeypatch.setenv("BLACKOUT_MIN_SPEAK_GAP", "0")
    question = "你刚说十，现在说二十，按哪个算？"
    _fake(monkeypatch, _parsed(conflict_question=question))
    first = conductor.process_speech(session_id, "二十", now=1000.0)
    second = conductor.process_speech(session_id, "还是二十", now=1010.0)
    assert first["reply"] == question
    assert second["action"] == "listen" and second["reply"] == ""
    for index in range(1, 5):
        _fake(monkeypatch, _parsed(conflict_question=f"问题{index}不一样，按哪个算？"))
        result = conductor.process_speech(session_id, f"说法{index}", now=1100.0 + index * 20)
        if index <= 2:
            assert result["action"] == "follow_up"
        else:
            assert result["reply"] == "" or "问题" not in result["reply"]
    # First plus two more equals the cap of three; the later ones are not asked.
    assert _record(session_id)["stats"]["conflicts_asked"] == 3


def test_conflict_held_in_gap_then_asked_and_dropped_after_45(tmp_path: Any, monkeypatch: Any) -> None:
    session_id = _make_session(tmp_path, monkeypatch)
    monkeypatch.setenv("BLACKOUT_MIN_SPEAK_GAP", "20")
    question = "你刚说十小时，现在说二十，按哪个算？"
    conductor._last_spoke[session_id] = 1000.0
    conductor._first_turn[session_id] = 900.0
    _fake(monkeypatch, _parsed(conflict_question=question))
    held = conductor.process_speech(session_id, "现在二十小时", now=1005.0)
    assert held["action"] == "listen" and held["reply"] == ""
    _fake(monkeypatch, _parsed(conflict_question=question))
    asked = conductor.process_speech(session_id, "继续想", now=1030.0)
    assert asked["action"] == "follow_up" and asked["reply"] == question
    # A second pending question dropped after 45 seconds, even if returned again.
    conductor._last_spoke[session_id] = 2000.0
    _fake(monkeypatch, _parsed(conflict_question="另一个问题，按哪个算？"))
    conductor.process_speech(session_id, "又变了", now=2005.0)
    _fake(monkeypatch, _parsed(conflict_question="另一个问题，按哪个算？"))
    dropped = conductor.process_speech(session_id, "继续", now=2060.0)
    assert dropped["reply"] == ""


def test_held_conflict_dropped_when_model_returns_empty(tmp_path: Any, monkeypatch: Any) -> None:
    session_id = _make_session(tmp_path, monkeypatch)
    monkeypatch.setenv("BLACKOUT_MIN_SPEAK_GAP", "20")
    question = "你刚说十小时，现在说二十，按哪个算？"
    conductor._last_spoke[session_id] = 1000.0
    conductor._first_turn[session_id] = 900.0
    _fake(monkeypatch, _parsed(conflict_question=question))
    held = conductor.process_speech(session_id, "现在二十小时", now=1005.0)
    assert held["action"] == "listen" and held["reply"] == ""
    _fake(monkeypatch, _parsed())
    dropped = conductor.process_speech(session_id, "对了就是三", now=1030.0)
    assert dropped["action"] == "listen" and dropped["reply"] == ""
    assert session_id not in conductor._pending_conflicts
    # And it is not resurrected on a later turn either.
    _fake(monkeypatch, _parsed())
    later = conductor.process_speech(session_id, "继续想", now=1040.0)
    assert later["reply"] == ""


def test_conflict_gap_is_shorter_than_speak_gap(tmp_path: Any, monkeypatch: Any) -> None:
    session_id = _make_session(tmp_path, monkeypatch)
    monkeypatch.setenv("BLACKOUT_MIN_SPEAK_GAP", "20")
    monkeypatch.setenv("BLACKOUT_MIN_CONFLICT_GAP", "6")
    question = "你刚说三个人，现在说五个人，按哪个算？"
    conductor._last_spoke[session_id] = 1000.0
    conductor._first_turn[session_id] = 900.0
    _fake(monkeypatch, _parsed(conflict_question=question))
    asked = conductor.process_speech(session_id, "现在五个人", now=1007.0)
    assert asked["action"] == "follow_up" and asked["reply"] == question
    other = _make_session(tmp_path, monkeypatch)
    monkeypatch.setenv("BLACKOUT_MIN_SPEAK_GAP", "20")
    monkeypatch.setenv("BLACKOUT_MIN_CONFLICT_GAP", "6")
    conductor._last_spoke[other] = 1000.0
    conductor._first_turn[other] = 900.0
    _fake(monkeypatch, _parsed(conflict_question=question))
    held = conductor.process_speech(other, "现在五个人", now=1004.0)
    assert held["action"] == "listen" and held["reply"] == ""


def test_pull_back_wins_over_pending(tmp_path: Any, monkeypatch: Any) -> None:
    session_id = _make_session(tmp_path, monkeypatch)
    monkeypatch.setenv("BLACKOUT_MIN_SPEAK_GAP", "20")
    conductor._last_spoke[session_id] = 1000.0
    conductor._first_turn[session_id] = 900.0
    _fake(monkeypatch, _parsed(conflict_question="十还是二十，按哪个算？"))
    conductor.process_speech(session_id, "二十", now=1005.0)
    _fake(monkeypatch, _parsed(action="pull_back", reply="这个记下了，我们回到方案。", add_parking=["火锅"]))
    result = conductor.process_speech(session_id, "对了吃火锅吧", now=1030.0)
    assert result["action"] == "pull_back"
    assert "火锅" not in result["reply"] or "回到" in result["reply"]
    assert result["reply"] == "这个记下了，我们回到方案。"


def test_conflict_not_on_suppressed_or_ending_turn(tmp_path: Any, monkeypatch: Any) -> None:
    session_id = _make_session(tmp_path, monkeypatch)
    _fake(monkeypatch, _parsed(conflict_question="十还是二十，按哪个算？"))
    suppressed = conductor.process_speech(session_id, "先说二十，好，结束", now=1000.0)
    assert suppressed["end"] is True
    assert suppressed["reply"] != "十还是二十，按哪个算？"
    assert _record(session_id).get("stats", {}).get("conflicts_asked", 0) == 0
    other = _make_session(tmp_path / "two" if False else tmp_path, monkeypatch)
    # Pure ending makes no model call, so no question can be asked.
    calls = {"n": 0}
    def counting(record: Dict[str, Any], text: str, seconds: Any) -> Dict[str, Any]:
        calls["n"] += 1
        return _parsed(conflict_question="十还是二十？")
    monkeypatch.setattr(conductor, "_call_model_once", counting)
    ended = conductor.process_speech(other, "结束", now=2000.0)
    assert ended["end"] is True and calls["n"] == 0


def _seed_quiet_history(session_id: str, count: int = 12) -> None:
    record = _record(session_id)
    record["history"] = [{"role": "user", "content": f"第{i}点想法", "at": store.now_iso()} for i in range(count)]
    store.save_session(record)


def test_reflection_not_due_before_thresholds(tmp_path: Any, monkeypatch: Any) -> None:
    session_id = _make_session(tmp_path, monkeypatch)
    _fake(monkeypatch, _parsed(action="continue", reply="现在定了甲，还没定乙。"))
    result = conductor.process_speech(session_id, "刚说了一点", now=1000.0)
    # Default thresholds (10 turns / 150s) are not met: no server forcing, but
    # the model's own continue is still its reply; reflection is not counted.
    assert _record(session_id)["stats"].get("reflections", 0) == 0


def test_reflection_model_continue_spoken_and_counted(tmp_path: Any, monkeypatch: Any) -> None:
    session_id = _make_session(tmp_path, monkeypatch)
    monkeypatch.setenv("BLACKOUT_REFLECT_TURNS", "3")
    monkeypatch.setenv("BLACKOUT_REFLECT_SECONDS", "10")
    monkeypatch.setenv("BLACKOUT_MIN_SPEAK_GAP", "0")
    _seed_quiet_history(session_id)
    conductor._first_turn[session_id] = 100.0
    _fake(monkeypatch, _parsed(action="continue", reply="现在定了甲，还没定乙。"))
    result = conductor.process_speech(session_id, "这个话题说完了", now=1000.0)
    assert result["action"] == "continue" and result["reply"] == "现在定了甲，还没定乙。"
    assert _record(session_id)["stats"]["reflections"] == 1
    # Count starts again: the assistant line is in history, so not due now.
    _fake(monkeypatch, _parsed())
    again = conductor.process_speech(session_id, "继续想别的", now=1010.0)
    assert again["reply"] == ""
    assert _record(session_id)["stats"]["reflections"] == 1


def test_reflection_server_line_from_state_and_empty_state(tmp_path: Any, monkeypatch: Any) -> None:
    session_id = _make_session(tmp_path, monkeypatch)
    monkeypatch.setenv("BLACKOUT_REFLECT_TURNS", "3")
    monkeypatch.setenv("BLACKOUT_REFLECT_SECONDS", "10")
    monkeypatch.setenv("BLACKOUT_MIN_SPEAK_GAP", "0")
    record = _record(session_id)
    record["state"]["decisions"] = ["用实时模式"]
    record["state"]["open_questions"] = ["字幕怎么做"]
    store.save_session(record)
    _seed_quiet_history(session_id)
    conductor._first_turn[session_id] = 100.0
    _fake(monkeypatch, _parsed())
    result = conductor.process_speech(session_id, "这一段说完了", now=1000.0)
    assert result["action"] == "continue"
    assert result["reply"] == message("zh", "reflect_both", decision="用实时模式", open="字幕怎么做")
    assert _record(session_id)["stats"]["reflections"] == 1
    empty = _make_session(tmp_path, monkeypatch)
    monkeypatch.setenv("BLACKOUT_REFLECT_TURNS", "3")
    monkeypatch.setenv("BLACKOUT_REFLECT_SECONDS", "10")
    _seed_quiet_history(empty)
    conductor._first_turn[empty] = 100.0
    _fake(monkeypatch, _parsed())
    silent = conductor.process_speech(empty, "这一段说完了", now=1000.0)
    assert silent["reply"] == "" and silent["action"] == "listen"


class _FakeError(Exception):
    def __init__(self, text: str, status: Any = None) -> None:
        super().__init__(text)
        if status is not None:
            self.status_code = status


def test_failure_kinds_and_retry(tmp_path: Any, monkeypatch: Any) -> None:
    _make_session(tmp_path, monkeypatch)
    record: Dict[str, Any] = {"id": "x", "state": {}, "history": [], "tasks": []}
    cases = [
        (_FakeError("nope", 401), "key", 1),
        (_FakeError("insufficient_quota", 429), "credits", 1),
        (_FakeError("boom"), "network", 2),
        (_FakeError("pay", 402), "budget", 1),
    ]
    for exc, kind, expected_calls in cases:
        calls = {"n": 0}
        def raising(record_arg: Dict[str, Any], text: str, seconds: Any, exc: Any = exc, calls: Any = calls) -> Dict[str, Any]:
            calls["n"] += 1
            raise exc
        monkeypatch.setattr(conductor, "_call_model_once", raising)
        parsed, failure = conductor._call_model_with_retry(record, "hi", None)
        assert parsed is None and failure == kind
        assert calls["n"] == expected_calls


def test_failure_speech_timing_and_recovery(tmp_path: Any, monkeypatch: Any) -> None:
    session_id = _make_session(tmp_path, monkeypatch)
    def raising_key(record: Dict[str, Any], text: str, seconds: Any) -> Dict[str, Any]:
        raise _FakeError("bad key", 401)
    monkeypatch.setattr(conductor, "_call_model_once", raising_key)
    first = conductor.process_speech(session_id, "第一句话", now=1000.0)
    assert first["ai_failed"] == "key" and first["reply"] == message("zh", "key_rejected")
    second = conductor.process_speech(session_id, "第二句话", now=1030.0)
    assert second["ai_failed"] == "key" and second["reply"] == ""
    assert "第一句话" in _history_texts(session_id) and "第二句话" in _history_texts(session_id)
    _fake(monkeypatch, _parsed())
    back = conductor.process_speech(session_id, "第三句话", now=1040.0)
    assert back["reply"] == message("zh", "ai_back") and back["ai_failed"] == ""


def test_network_speech_on_second_failure(tmp_path: Any, monkeypatch: Any) -> None:
    session_id = _make_session(tmp_path, monkeypatch)
    def raising(record: Dict[str, Any], text: str, seconds: Any) -> Dict[str, Any]:
        raise _FakeError("down")
    monkeypatch.setattr(conductor, "_call_model_once", raising)
    first = conductor.process_speech(session_id, "先说一句", now=1000.0)
    assert first["ai_failed"] == "network" and first["reply"] == ""
    second = conductor.process_speech(session_id, "再说一句", now=1010.0)
    assert second["ai_failed"] == "network" and second["reply"] == message("zh", "ai_unreachable")
    third = conductor.process_speech(session_id, "还说一句", now=1020.0)
    assert third["reply"] == ""
    assert _history_texts(session_id) == ["先说一句", "再说一句", "还说一句"]


def test_asr_auth_failed_on_unauthorized(monkeypatch: Any) -> None:
    class FakeRequest:
        def __init__(self, host: str) -> None:
            self.headers: Dict[str, str] = {"Host": host}
    class FakeSocket:
        def __init__(self, host: str) -> None:
            self.request = FakeRequest(host)
        async def send(self, data: str) -> None:
            return None
        async def recv(self) -> str:
            return json.dumps({"type": "error", "message": "Unauthorized: bad key"})
        async def close(self) -> None:
            return None
    async def fake_connect(url: str, compression: Any = None) -> Any:
        return FakeSocket(urllib.parse.urlparse(url).netloc)
    monkeypatch.setattr(asr.websockets, "connect", fake_connect)
    stream = asr.AsrStream("wss://127.0.0.1/asr", "secret", "zh")
    assert asyncio.run(stream.connect()) is False
    assert stream.auth_failed is True
