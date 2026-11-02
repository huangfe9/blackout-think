"""Conductor tests."""
import inspect
import json
import threading
import time
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

import app.conductor as conductor
from app import store
from app.state import build_map


@pytest.fixture(autouse=True)
def setup_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLACKOUT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BLACKOUT_MIN_SPEAK_GAP", "20")
    monkeypatch.setenv("BLACKOUT_NUDGE_SECONDS", "60")
    store.clear_memory()
    conductor.clear_memory()


def fake_client(payload: Any) -> Any:
    mock: MagicMock = MagicMock()
    resp: MagicMock = MagicMock()
    resp.status = "completed"
    resp.output_text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    mock.responses.create.return_value = resp
    return mock


def payload(action: str = "listen", reply: str = "", **extra: Any) -> Dict[str, Any]:
    data: Dict[str, Any] = {"action": action, "reply": reply, "reason": "理由", "user_asked_ai": False, "add_points": [], "expand_points": [], "add_parking": [], "add_decisions": [], "add_todos": [], "add_questions": [], "resolve_questions": [], "add_contradictions": [], "task": {"kind": "none", "instruction": "", "under": ""}}
    data.update(extra)
    return data


def make() -> str:
    return str(store.create_session("写计划")["id"])


def make_en() -> str:
    """Create an English session, however the store exposes the language."""
    try:
        record: Any = store.create_session("Plan the work", language="en")  # type: ignore[call-arg]
    except TypeError:
        record = store.create_session("Plan the work")
        record["language"] = "en"
        store.save_session(record)
    return str(record["id"])


def test_input_contains_current_text() -> None:
    sid: str = make()
    fake: Any = fake_client(payload())
    with patch.object(conductor, "create_client", return_value=fake):
        conductor.process_speech(sid, "独特的话XYZ", time.time())
    dumped: str = json.dumps(fake.responses.create.call_args.kwargs, ensure_ascii=False) + json.dumps(fake.responses.create.call_args.args, ensure_ascii=False)
    assert "current_user_text" in dumped and "独特的话XYZ" in dumped
    kwargs: Any = fake.responses.create.call_args.kwargs
    assert kwargs["reasoning"] == {"effort": "low"} and kwargs["max_output_tokens"] == 4000


def test_listen_silent_records() -> None:
    sid: str = make()
    fake: Any = fake_client(payload("listen", "不该说话", add_decisions=["决定一"]))
    with patch.object(conductor, "create_client", return_value=fake):
        result: Any = conductor.process_speech(sid, "我决定这样", time.time())
    assert result["reply"] == ""
    record: Any = store.get_session(sid)
    assert record["history"][0]["content"] == "我决定这样"
    assert record["state"]["decisions"] == ["决定一"]
    assert record["stats"]["listened"] == 1


def test_gap_downgrades_and_asked_exempt() -> None:
    sid: str = make()
    conductor._last_spoke[sid] = 1000.0
    fake: Any = fake_client(payload("follow_up", "追问一句"))
    with patch.object(conductor, "create_client", return_value=fake):
        result: Any = conductor.process_speech(sid, "说了一半", 1005.0)
    assert result["action"] == "listen" and result["reply"] == ""
    fake2: Any = fake_client(payload("follow_up", "回答追问", user_asked_ai=True))
    with patch.object(conductor, "create_client", return_value=fake2):
        result2: Any = conductor.process_speech(sid, "为什么", 1006.0)
    assert result2["action"] == "follow_up"
    sid2: str = make()
    conductor._last_spoke[sid2] = 1000.0
    fake3: Any = fake_client(payload("continue", "继续问"))
    with patch.object(conductor, "create_client", return_value=fake3):
        assert conductor.process_speech(sid2, "一段", 1005.0)["action"] == "listen"


def test_pull_back_exempt_stores_parking() -> None:
    sid: str = make()
    conductor._last_spoke[sid] = 1000.0
    fake: Any = fake_client(payload("pull_back", "这个我先记下了，我们回到计划", add_parking=["团建"]))
    with patch.object(conductor, "create_client", return_value=fake):
        result: Any = conductor.process_speech(sid, "去团建", 1001.0)
    assert result["action"] == "pull_back"
    assert store.get_session(sid)["state"]["parking_lot"] == ["团建"]
    assert store.get_session(sid)["stats"]["pull_backs"] == 1


def test_answer_exempt_from_gap() -> None:
    sid: str = make()
    conductor._last_spoke[sid] = 1000.0
    fake: Any = fake_client(payload("answer", "可以", user_asked_ai=True))
    with patch.object(conductor, "create_client", return_value=fake):
        result: Any = conductor.process_speech(sid, "行吗", 1001.0)
    assert result["action"] == "answer" and result["reply"] == "可以"


def test_end_phrases_no_model() -> None:
    for phrase in ["结束", "结束吧", "停", "先这样", "结束了", "我说完了"]:
        conductor.clear_memory(); store.clear_memory()
        sid = make()
        fake: Any = fake_client(payload("continue", "x"))
        with patch.object(conductor, "create_client", return_value=fake) as maker:
            result: Any = conductor.process_speech(sid, phrase, time.time())
        assert result["end"] is True and not maker.called
    sid2: str = make()
    fake2: Any = fake_client(payload())
    with patch.object(conductor, "create_client", return_value=fake2):
        assert conductor.process_speech(sid2, "我想讨论怎么结束", time.time())["end"] is False


def test_english_end_phrases_no_model() -> None:
    for phrase in ["Stop.", "OK, stop.", "I'm done.", "That's all."]:
        conductor.clear_memory(); store.clear_memory()
        sid: str = make_en()
        fake: Any = fake_client(payload("continue", "x"))
        with patch.object(conductor, "create_client", return_value=fake) as maker:
            result: Any = conductor.process_speech(sid, phrase, time.time())
        assert result["end"] is True and not maker.called
    sid2: str = make_en()
    fake2: Any = fake_client(payload())
    with patch.object(conductor, "create_client", return_value=fake2):
        result2: Any = conductor.process_speech(sid2, "I want to stop using the old design", time.time())
    assert result2["end"] is False


def test_summarize_confirmation() -> None:
    sid: str = make()
    fake: Any = fake_client(payload("summarize", "总结吧"))
    with patch.object(conductor, "create_client", return_value=fake):
        result: Any = conductor.process_speech(sid, "差不多了", time.time())
    assert result["end"] is False and result["reply"] == "要结束吗？说结束就行。"
    result2: Any = conductor.process_speech(sid, "对", time.time())
    assert result2["end"] is True
    for confirm in ["是", "好", "好的", "嗯", "可以", "是的"]:
        sidc: str = make()
        with patch.object(conductor, "create_client", return_value=fake_client(payload("summarize", "x"))):
            conductor.process_speech(sidc, "差不多了", time.time())
        assert conductor.process_speech(sidc, confirm, time.time())["end"] is True
    sid3: str = make()
    with patch.object(conductor, "create_client", return_value=fake_client(payload("summarize", "x"))):
        conductor.process_speech(sid3, "差不多了", time.time())
    with patch.object(conductor, "create_client", return_value=fake_client(payload())):
        conductor.process_speech(sid3, "继续想", time.time())
    assert sid3 not in conductor._awaiting_end


def test_english_summarize_confirmation_and_confirm_word() -> None:
    sid: str = make_en()
    fake: Any = fake_client(payload("summarize", "wrap up"))
    with patch.object(conductor, "create_client", return_value=fake):
        result: Any = conductor.process_speech(sid, "That is about it for today", time.time())
    assert result["end"] is False and result["reply"] == "Want to finish? Just say stop."
    assert conductor.process_speech(sid, "yes", time.time())["end"] is True


def test_failure_falls_back_listen_and_retries_once() -> None:
    sid: str = make()
    mock: MagicMock = MagicMock(); mock.responses.create.side_effect = Exception("boom")
    with patch.object(conductor, "create_client", return_value=mock):
        result: Any = conductor.process_speech(sid, "保存这句话", time.time())
    assert result["action"] == "listen"
    assert mock.responses.create.call_count == 2
    assert store.get_session(sid)["history"][0]["content"] == "保存这句话"
    fake: Any = fake_client("not-json")
    with patch.object(conductor, "create_client", return_value=fake):
        assert conductor.process_speech(sid, "第二句", time.time())["action"] == "listen"
    empty: Any = fake_client("")
    with patch.object(conductor, "create_client", return_value=empty):
        assert conductor.process_speech(sid, "第三句", time.time())["action"] == "listen"
    incomplete: MagicMock = MagicMock(); incomplete.status = "incomplete"; incomplete.output_text = json.dumps(payload())
    mock2: MagicMock = MagicMock(); mock2.responses.create.return_value = incomplete
    with patch.object(conductor, "create_client", return_value=mock2):
        assert conductor.process_speech(sid, "第四句", time.time())["action"] == "listen"


def test_budget_402() -> None:
    sid: str = make()
    mock: MagicMock = MagicMock(); exc: Exception = Exception("no"); setattr(exc, "status_code", 402); mock.responses.create.side_effect = exc
    with patch.object(conductor, "create_client", return_value=mock):
        result: Any = conductor.process_speech(sid, "你好", time.time())
    assert result["budget_exhausted"] is True
    assert store.get_session(sid)["history"][0]["content"] == "你好"


def test_task_ack() -> None:
    sid: str = make()
    fake: Any = fake_client(payload("listen", "", task={"kind": "search", "instruction": "查某事", "under": ""}))
    with patch.object(conductor, "create_client", return_value=fake):
        with patch("app.tasks._executor") as executor:
            executor.submit.return_value = None
            result: Any = conductor.process_speech(sid, "帮我查一下", time.time())
    assert result["task_started"] is True and result["reply"] == "好，我去弄，你继续说。"
    assert len(store.get_session(sid)["tasks"]) == 1


def test_english_task_ack() -> None:
    sid: str = make_en()
    fake: Any = fake_client(payload("listen", "", task={"kind": "search", "instruction": "Look up the price", "under": ""}))
    with patch.object(conductor, "create_client", return_value=fake):
        with patch("app.tasks._executor") as executor:
            executor.submit.return_value = None
            result: Any = conductor.process_speech(sid, "Please look that up", time.time())
    assert result["task_started"] is True and result["reply"] == "OK, I'm on it. Keep going."
    assert len(store.get_session(sid)["tasks"]) == 1


def test_reply_truncation() -> None:
    assert conductor.truncate_reply("短句") == "短句"
    long_reply: str = "这是一句话，" + "很长" * 40 + "。后面"
    out: str = conductor.truncate_reply(long_reply)
    assert len(out) <= 60 and out.endswith(("，", "。"))
    long_en: str = "x" * 100
    assert conductor.truncate_reply(long_en) == long_en
    sid: str = make()
    fake: Any = fake_client(payload("answer", "x" * 100, user_asked_ai=True))
    with patch.object(conductor, "create_client", return_value=fake):
        result: Any = conductor.process_speech(sid, "问", time.time())
    assert result["reply"] == "x" * 100


def test_missing_session_raises() -> None:
    with pytest.raises(KeyError):
        conductor.process_speech("0" * 32, "你好", time.time())


def test_finished_session_gets_end_without_change() -> None:
    sid: str = make()
    record: Any = store.get_session(sid)
    record["status"] = "finished"
    store.save_session(record)
    before: Any = json.dumps(store.get_session(sid), ensure_ascii=False)
    fake: Any = fake_client(payload("answer", "不该说"))
    with patch.object(conductor, "create_client", return_value=fake) as maker:
        result: Any = conductor.process_speech(sid, "还在说", time.time())
    assert result["end"] is True and result["reply"] == "" and not maker.called
    assert json.dumps(store.get_session(sid), ensure_ascii=False) == before


def test_finished_session_returns_end_true_without_changing_record() -> None:
    sid: str = make()
    fake: Any = fake_client(payload("listen", "", add_decisions=["已有"]))
    with patch.object(conductor, "create_client", return_value=fake):
        conductor.process_speech(sid, "先记一句", time.time())
    record: Any = store.get_session(sid)
    record["status"] = "finished"
    store.save_session(record)
    before: Any = json.dumps(store.get_session_copy(sid), ensure_ascii=False, sort_keys=True)
    fake2: Any = fake_client(payload("answer", "不该说", add_decisions=["新决定"]))
    with patch.object(conductor, "create_client", return_value=fake2) as maker:
        result: Any = conductor.process_speech(sid, "结束之后的话", time.time())
    assert result["end"] is True
    assert not maker.called
    after: Any = json.dumps(store.get_session_copy(sid), ensure_ascii=False, sort_keys=True)
    assert after == before


def test_note_spoken_history_stats_and_gap() -> None:
    sid: str = make()
    conductor.note_spoken(sid, "后台做完了", "announcement", 1000.0)
    record: Any = store.get_session(sid)
    assert record["history"][-1]["role"] == "assistant"
    assert record["history"][-1]["content"] == "后台做完了"
    assert record["stats"]["ai_spoke"] == 1
    assert record["stats"]["nudges"] == 0
    conductor.note_spoken(sid, "还在想吗", "nudge", 1001.0)
    record = store.get_session(sid)
    assert record["history"][-1]["content"] == "还在想吗"
    assert record["stats"]["ai_spoke"] == 2
    assert record["stats"]["nudges"] == 1
    fake: Any = fake_client(payload("follow_up", "追问一句"))
    with patch.object(conductor, "create_client", return_value=fake):
        result: Any = conductor.process_speech(sid, "说了一半", 1006.0)
    assert result["action"] == "listen" and result["reply"] == ""
    fake2: Any = fake_client(payload("follow_up", "追问一句"))
    with patch.object(conductor, "create_client", return_value=fake2):
        result2: Any = conductor.process_speech(sid, "又说了一半", 1030.0)
    assert result2["action"] == "follow_up"


def test_note_spoken_ignores_other_kinds_and_empty() -> None:
    sid: str = make()
    before: int = len(store.get_session(sid)["history"])
    conductor.note_spoken(sid, "不该记", "reply", 1000.0)
    conductor.note_spoken(sid, "  ", "nudge", 1000.0)
    record: Any = store.get_session(sid)
    assert len(record["history"]) == before
    assert record["stats"]["ai_spoke"] == 0 and record["stats"]["nudges"] == 0
    with pytest.raises(KeyError):
        conductor.note_spoken("0" * 32, "你好", "nudge", 1000.0)


def test_lock_free_during_model_call() -> None:
    sid: str = make()
    started: threading.Event = threading.Event()
    release: threading.Event = threading.Event()
    def blocking_client() -> Any:
        started.set()
        release.wait(timeout=5)
        return fake_client(payload())
    result_box: Dict[str, Any] = {}
    def run() -> None:
        with patch.object(conductor, "create_client", side_effect=blocking_client):
            result_box["r"] = conductor.process_speech(sid, "你好", time.time())
    thread: threading.Thread = threading.Thread(target=run)
    thread.start()
    assert started.wait(timeout=2)
    lock: Any = store.get_lock(sid)
    assert lock.acquire(timeout=1)
    lock.release()
    release.set()
    thread.join(timeout=5)
    assert result_box["r"]["action"] == "listen"


def test_deleted_during_model_call_raises_and_writes_nothing(tmp_path: Path) -> None:
    sid: str = make()
    def deleting_client() -> Any:
        store.delete_session(sid)
        return fake_client(payload())
    with patch.object(conductor, "create_client", side_effect=deleting_client):
        with pytest.raises(KeyError):
            conductor.process_speech(sid, "你好", time.time())
    assert store.get_session(sid) is None
    assert not (tmp_path / "sessions" / f"{sid}.json").exists()


def test_nudge() -> None:
    record: Any = store.create_session("目标")
    record["state"]["main_points"] = [{"point": "这是一个非常长的未展开要点需要继续说", "status": "未展开"}]
    assert conductor.nudge_text(record, 59, 0) is None
    text: Any = conductor.nudge_text(record, 60, 0)
    assert text is not None and "还没展开" in text
    inner: str = text.split("「", 1)[1].split("」", 1)[0]
    assert len(inner) <= 16
    assert conductor.nudge_text(record, 179, 1) is None
    assert conductor.nudge_text(record, 180, 1) is not None
    assert conductor.nudge_text(record, 500, 2) is None
    record["paused"] = True
    assert conductor.nudge_text(record, 60, 0) is None
    record["paused"] = False; record["tasks"] = [{"status": "running"}]
    assert conductor.nudge_text(record, 60, 0) is None
    record2: Any = store.create_session("目标2")
    assert conductor.nudge_text(record2, 60, 0) == "还在吗？卡住的话，先说一个最小的问题。"
    assert conductor.nudge_text("nope", 60, 0) is None  # type: ignore[arg-type]


def test_nudge_point_cut_at_word_boundary() -> None:
    record: Any = store.create_session("目标")
    record["state"]["main_points"] = [{"point": "state tracking and more things", "status": "未展开"}]
    text: Any = conductor.nudge_text(record, 60, 0)
    assert text is not None
    inner: str = text.split("「", 1)[1].split("」", 1)[0]
    assert inner == "state tracking"
    assert "tracki" not in inner or inner.endswith("tracking")
    record["state"]["main_points"] = [{"point": "方案，第二阶段的排期问题", "status": "未展开"}]
    text2: Any = conductor.nudge_text(record, 60, 0)
    assert text2 is not None
    inner2: str = text2.split("「", 1)[1].split("」", 1)[0]
    assert len(inner2) <= 16
    record["state"]["main_points"] = [{"point": "这是一个非常长的未展开要点需要继续慢慢说下去", "status": "未展开"}]
    text3: Any = conductor.nudge_text(record, 60, 0)
    assert text3 is not None
    inner3: str = text3.split("「", 1)[1].split("」", 1)[0]
    assert len(inner3) == 16


def test_nudge_second_is_always_generic() -> None:
    record: Any = store.create_session("目标")
    record["state"]["main_points"] = [{"point": "未展开要点", "status": "未展开"}]
    first: Any = conductor.nudge_text(record, 60, 0)
    assert first is not None and "未展开要点" in first
    second: Any = conductor.nudge_text(record, 180, 1)
    assert second == "还在吗？卡住的话，先说一个最小的问题。"
    assert "未展开要点" not in str(second)


def test_nudge_english_follows_recent_language_and_keeps_words_whole() -> None:
    record: Any = store.create_session("目标")
    record["history"] = [{"role": "user", "content": "Let me think in English", "at": "x"}]
    record["state"]["main_points"] = [{"point": "implementation planning continues", "status": "未展开"}]
    text: Any = conductor.nudge_text(record, 60, 0)
    assert text == "You haven't finished with implementation. Still thinking?"
    second: Any = conductor.nudge_text(record, 180, 1)
    assert second == "Still there? If you're stuck, try saying the smallest question."


# --- End phrases at the conductor level ---------------------------------

def test_end_filler_prefix_makes_no_model_call() -> None:
    sid: str = make()
    fake: Any = fake_client(payload("continue", "不该调用"))
    with patch.object(conductor, "create_client", return_value=fake) as maker:
        result: Any = conductor.process_speech(sid, "好，结束。", time.time())
    assert result["end"] is True
    assert not maker.called


def test_end_after_content_records_suppressed_turn_then_ends() -> None:
    sid: str = make()
    fake: Any = fake_client(payload("answer", "模型这句不该播", add_decisions=[{"text": "先解决这个问题", "under": ""}]))
    with patch.object(conductor, "create_client", return_value=fake) as maker:
        result: Any = conductor.process_speech(sid, "首先我觉得有个问题，好，结束", time.time())
    assert maker.called
    assert result["end"] is True
    # The model's own reply is suppressed: it is neither returned as the
    # spoken reply nor recorded as an assistant history entry.
    assert result["reply"] != "模型这句不该播"
    record: Any = store.get_session(sid)
    assert record["history"][0]["role"] == "user"
    assert record["history"][0]["content"] == "首先我觉得有个问题"
    assert all(h.get("content") != "模型这句不该播" for h in record["history"])
    assert record["state"]["decisions"] == ["先解决这个问题"]


def test_end_after_english_content_records_suppressed_turn_then_ends() -> None:
    sid: str = make_en()
    fake: Any = fake_client(payload("answer", "a reply that must not be spoken", add_decisions=[{"text": "Solve this first", "under": ""}]))
    with patch.object(conductor, "create_client", return_value=fake) as maker:
        result: Any = conductor.process_speech(sid, "first idea, ok, stop", time.time())
    assert maker.called
    assert result["end"] is True
    assert result["reply"] != "a reply that must not be spoken"
    record: Any = store.get_session(sid)
    assert record["history"][0]["content"] == "first idea"
    assert record["state"]["decisions"] == ["Solve this first"]


def test_summarize_with_end_word_in_speech_ends_straight_away() -> None:
    sid: str = make()
    fake: Any = fake_client(payload("summarize", "总结吧"))
    with patch.object(conductor, "create_client", return_value=fake):
        result: Any = conductor.process_speech(sid, "我已经说结束了你怎么还在", time.time())
    assert result["end"] is True
    assert result["reply"] == "好，我来整理"
    assert sid not in conductor._awaiting_end


def test_summarize_without_end_word_still_asks_for_confirmation() -> None:
    sid: str = make()
    fake: Any = fake_client(payload("summarize", "总结吧"))
    with patch.object(conductor, "create_client", return_value=fake):
        result: Any = conductor.process_speech(sid, "今天差不多了", time.time())
    assert result["end"] is False
    assert result["reply"] == "要结束吗？说结束就行。"
    assert sid in conductor._awaiting_end


# --- Background-task ceiling and de-duplication --------------------------

def test_task_ceiling_refuses_with_reply_and_parks_instruction_as_question(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLACKOUT_MAX_TASKS_PER_SESSION", "2")
    sid: str = make()
    record: Any = store.get_session(sid)
    record["tasks"] = [
        {"id": "t1", "kind": "search", "instruction": "已有的事一", "status": "done", "conclusion": "", "detail": "", "sources": [], "created_at": "x", "under": ""},
        {"id": "t2", "kind": "draft", "instruction": "已有的事二", "status": "running", "conclusion": "", "detail": "", "sources": [], "created_at": "x", "under": ""},
    ]
    store.save_session(record)
    fake: Any = fake_client(payload("listen", "", task={"kind": "search", "instruction": "查一件新的事", "under": ""}))
    with patch.object(conductor, "create_client", return_value=fake):
        result: Any = conductor.process_speech(sid, "帮我查一件新的事", time.time())
    assert result["task_started"] is False
    assert result["reply"] == conductor.CAP_REPLY
    assert result["reply"] == "这次后台的事够多了，我先记下这个问题。"
    loaded: Any = store.get_session(sid)
    assert len(loaded["tasks"]) == 2
    assert loaded["state"]["open_questions"] == ["查一件新的事"]


def test_english_task_ceiling_uses_english_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLACKOUT_MAX_TASKS_PER_SESSION", "2")
    sid: str = make_en()
    record: Any = store.get_session(sid)
    record["tasks"] = [
        {"id": "t1", "kind": "search", "instruction": "first job", "status": "done", "conclusion": "", "detail": "", "sources": [], "created_at": "x", "under": ""},
        {"id": "t2", "kind": "draft", "instruction": "second job", "status": "running", "conclusion": "", "detail": "", "sources": [], "created_at": "x", "under": ""},
    ]
    store.save_session(record)
    fake: Any = fake_client(payload("listen", "", task={"kind": "search", "instruction": "Look up one more thing", "under": ""}))
    with patch.object(conductor, "create_client", return_value=fake):
        result: Any = conductor.process_speech(sid, "Please look up one more thing", time.time())
    assert result["task_started"] is False
    assert result["reply"] == "That's a lot of background work for one session, so I'll note that as a question."
    loaded: Any = store.get_session(sid)
    assert len(loaded["tasks"]) == 2
    assert loaded["state"]["open_questions"] == ["Look up one more thing"]


def test_duplicate_instruction_ignoring_punctuation_and_spaces_starts_no_second_task() -> None:
    sid: str = make()
    first: Any = fake_client(payload("listen", "", task={"kind": "search", "instruction": "查一下 X 的价格！", "under": ""}))
    second: Any = fake_client(payload("listen", "", task={"kind": "search", "instruction": "查一下X的价格", "under": ""}))
    with patch("app.tasks._executor") as executor:
        executor.submit.return_value = None
        with patch.object(conductor, "create_client", return_value=first):
            result1: Any = conductor.process_speech(sid, "帮我查一下 X 的价格", time.time())
        assert result1["task_started"] is True
        with patch.object(conductor, "create_client", return_value=second):
            result2: Any = conductor.process_speech(sid, "再帮我查一下X的价格", time.time())
    assert result2["task_started"] is False
    assert len(store.get_session(sid)["tasks"]) == 1
    assert store.get_session(sid)["tasks"][0]["instruction"] == "查一下 X 的价格！"


# --- Live state and `under` additions ------------------------------------

def test_conductor_never_sets_live_mic_to_ai_speaking() -> None:
    # The conductor only records what was decided; whether the AI is
    # audibly speaking is owned by the realtime bridge / browser, which
    # use the unambiguous live values. The conductor must never claim it.
    source: str = inspect.getsource(conductor)
    assert "ai_speaking" not in source
    sid: str = make()
    fake: Any = fake_client(payload("answer", "可以的", user_asked_ai=True))
    with patch.object(conductor, "create_client", return_value=fake):
        conductor.process_speech(sid, "这样行吗", time.time())
    assert store.get_live(sid)["mic"] != "ai_speaking"


def test_additions_with_under_place_points_and_items_in_state() -> None:
    sid: str = make()
    fake: Any = fake_client(payload(
        "listen", "",
        add_points=[
            {"point": "语音", "status": "未展开", "under": ""},
            {"point": "实时模式能自动判断说完", "status": "已展开", "under": "语音"},
        ],
        add_decisions=[{"text": "决定用实时模式", "under": "语音"}],
        add_todos=[{"text": "录一版备用演示", "under": "语音"}],
        add_questions=[{"text": "断网怎么办", "under": "语音"}],
        add_contradictions=[{"text": "先说要离线又说要联网", "under": "语音"}],
    ))
    with patch.object(conductor, "create_client", return_value=fake):
        conductor.process_speech(sid, "语音这块我决定用实时模式", time.time())
    state: Any = store.get_session(sid)["state"]
    by_point: Dict[str, Any] = {p["point"]: p for p in state["main_points"]}
    assert by_point["语音"]["under"] == ""
    assert by_point["实时模式能自动判断说完"]["under"] == "语音"
    assert state["decisions"] == ["决定用实时模式"]
    assert state["todos"] == ["录一版备用演示"]
    assert state["open_questions"] == ["断网怎么办"]
    assert state["contradictions"] == ["先说要离线又说要联网"]
    for text in ("决定用实时模式", "录一版备用演示", "断网怎么办", "先说要离线又说要联网"):
        assert state["links"][text] == "语音"
    tree: Any = build_map(state, [])
    root_children: Dict[str, Any] = {str(c.get("text", "")): c for c in tree["children"]}
    assert "语音" in root_children
    nested: Dict[str, Any] = {str(c.get("text", "")): c for c in root_children["语音"]["children"]}
    assert nested["实时模式能自动判断说完"]["kind"] == "point"
    assert nested["决定用实时模式"]["kind"] == "decision"
    assert nested["录一版备用演示"]["kind"] == "todo"
    assert nested["断网怎么办"]["kind"] == "question"
    assert nested["先说要离线又说要联网"]["kind"] == "contradiction"
