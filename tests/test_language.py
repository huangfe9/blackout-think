"""Stage 7 language tests: English, Chinese, and per-session language.

These tests cover the language-dependent behaviour introduced with
English support: end phrases, fixed spoken sentences, silence nudges,
the ASR handshake, Markdown headings, and session creation.
"""
import asyncio
import json
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import app.conductor as conductor
import app.summary as summary_mod
from app import store
from app.asr import AsrStream
from app.main import app
from app.messages import MESSAGES, message
from app.state import new_state, recent_language, speech_language, split_end
from fake_asr import FakeASRServer


@pytest.fixture(autouse=True)
def setup_env(monkeypatch: pytest.MonkeyPatch) -> None:
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
    data: Dict[str, Any] = {"action": action, "reply": reply, "reason": "reason", "user_asked_ai": False, "add_points": [], "expand_points": [], "add_parking": [], "add_decisions": [], "add_todos": [], "add_questions": [], "resolve_questions": [], "add_contradictions": [], "task": {"kind": "none", "instruction": "", "under": ""}}
    data.update(extra)
    return data


def make_session(goal: str, language: str) -> str:
    """Create a session in `language`, however the store exposes it."""
    try:
        record: Any = store.create_session(goal, language=language)  # type: ignore[call-arg]
    except TypeError:
        record = store.create_session(goal)
        record["language"] = language
        store.save_session(record)
    return str(record["id"])


# --- split_end: English end phrases -------------------------------------

def test_split_end_english_ok_stop_no_content() -> None:
    assert split_end("OK, stop.") == ("", True)


def test_split_end_english_stop_no_content() -> None:
    assert split_end("Stop.") == ("", True)


def test_split_end_english_im_done_no_content() -> None:
    assert split_end("I'm done.") == ("", True)


def test_split_end_english_content_before_end_is_kept() -> None:
    assert split_end("first idea, ok, stop") == ("first idea", True)


def test_split_end_english_done_as_topic_does_not_end() -> None:
    assert split_end("That part is done.") == ("That part is done.", False)


def test_split_end_english_stop_as_topic_does_not_end() -> None:
    text: str = "I want to stop using the old design."
    assert split_end(text) == (text, False)


def test_split_end_chinese_cases_still_hold() -> None:
    assert split_end("好，结束。") == ("", True)
    assert split_end("首先我觉得有个问题，好，结束") == ("首先我觉得有个问题", True)
    assert split_end("我想讨论怎么结束这个项目") == ("我想讨论怎么结束这个项目", False)
    assert split_end("那就到这里吧") == ("那就到这里吧", False)


# --- speech_language / recent_language -----------------------------------

def test_speech_language_detects_cjk_and_latin() -> None:
    assert speech_language("想清楚比赛方案") == "zh"
    assert speech_language("Plan the demo") == "en"
    assert speech_language("demo 的技术方案") == "zh"
    assert speech_language("OK") == "en"
    assert speech_language("") == "en"


def test_recent_language_uses_latest_user_utterance() -> None:
    record: Dict[str, Any] = {
        "language": "zh",
        "history": [
            {"role": "user", "content": "先说中文", "at": "x"},
            {"role": "assistant", "content": "好的", "at": "x"},
            {"role": "user", "content": "Now in English", "at": "x"},
        ],
    }
    assert recent_language(record) == "en"


def test_recent_language_ignores_assistant_and_empty_user_entries() -> None:
    record: Dict[str, Any] = {
        "language": "en",
        "history": [
            {"role": "user", "content": "中文的一句", "at": "x"},
            {"role": "user", "content": "   ", "at": "x"},
            {"role": "assistant", "content": "An English reply", "at": "x"},
        ],
    }
    assert recent_language(record) == "zh"


def test_recent_language_falls_back_to_record_language_then_zh() -> None:
    assert recent_language({"language": "en", "history": []}) == "en"
    assert recent_language({"language": "zh", "history": []}) == "zh"
    assert recent_language({"language": "fr", "history": []}) == "zh"
    assert recent_language({"history": []}) == "zh"
    assert recent_language({}) == "zh"
    assert recent_language("not a record") == "zh"
    assert recent_language(None) == "zh"


# --- message() -------------------------------------------------------------

def test_message_every_key_in_both_languages() -> None:
    assert set(MESSAGES.keys()) == {"zh", "en"}
    assert set(MESSAGES["zh"].keys()) == set(MESSAGES["en"].keys())
    for language in ("zh", "en"):
        for key in MESSAGES[language]:
            text: str = message(language, key, point="some point", conclusion="some conclusion")
            assert isinstance(text, str)
            assert text.strip() != ""
            # Placeholders, when present, must have been filled in.
            assert "{point}" not in text
            assert "{conclusion}" not in text


def test_message_languages_actually_differ() -> None:
    for key in MESSAGES["zh"]:
        zh_text: str = message("zh", key, point="要点", conclusion="结论")
        en_text: str = message("en", key, point="point", conclusion="conclusion")
        assert zh_text != en_text


def test_message_falls_back_to_zh() -> None:
    for key in MESSAGES["zh"]:
        expected: str = message("zh", key, point="要点", conclusion="结论")
        assert message("fr", key, point="要点", conclusion="结论") == expected
        assert message("", key, point="要点", conclusion="结论") == expected
        assert message("EN", key, point="要点", conclusion="结论") == expected


def test_message_formats_placeholders() -> None:
    assert message("zh", "nudge_point", point="方案") == "「方案」还没展开，还在想吗？"
    assert message("en", "nudge_point", point="the plan") == "You haven't finished with the plan. Still thinking?"
    assert message("zh", "found", conclusion="价格是十元") == "查到了：价格是十元"
    assert message("en", "found", conclusion="it costs ten") == "Found it: it costs ten"


# --- Conductor fixed sentences follow the session language -----------------

def test_english_task_acknowledgement() -> None:
    sid: str = make_session("Plan the demo", "en")
    fake: Any = fake_client(payload("listen", "", task={"kind": "search", "instruction": "Look up the price", "under": ""}))
    with patch.object(conductor, "create_client", return_value=fake):
        with patch("app.tasks._executor") as executor:
            executor.submit.return_value = None
            result: Any = conductor.process_speech(sid, "Please look that up", 1000.0)
    assert result["task_started"] is True
    assert result["reply"] == "OK, I'm on it. Keep going."
    assert result["reply"] == message("en", "task_ack")


def test_chinese_task_acknowledgement() -> None:
    sid: str = make_session("写计划", "zh")
    fake: Any = fake_client(payload("listen", "", task={"kind": "search", "instruction": "查某事", "under": ""}))
    with patch.object(conductor, "create_client", return_value=fake):
        with patch("app.tasks._executor") as executor:
            executor.submit.return_value = None
            result: Any = conductor.process_speech(sid, "帮我查一下", 1000.0)
    assert result["task_started"] is True
    assert result["reply"] == "好，我去弄，你继续说。"
    assert result["reply"] == message("zh", "task_ack")


def test_english_end_confirmation() -> None:
    sid: str = make_session("Plan the demo", "en")
    fake: Any = fake_client(payload("summarize", "wrap up"))
    with patch.object(conductor, "create_client", return_value=fake):
        result: Any = conductor.process_speech(sid, "That is about it for today", 1000.0)
    assert result["end"] is False
    assert result["reply"] == "Want to finish? Just say stop."
    assert result["reply"] == message("en", "confirm_end")


def test_chinese_end_confirmation() -> None:
    sid: str = make_session("写计划", "zh")
    fake: Any = fake_client(payload("summarize", "总结吧"))
    with patch.object(conductor, "create_client", return_value=fake):
        result: Any = conductor.process_speech(sid, "今天差不多了", 1000.0)
    assert result["end"] is False
    assert result["reply"] == "要结束吗？说结束就行。"
    assert result["reply"] == message("zh", "confirm_end")


def _fill_task_ceiling(sid: str) -> None:
    record: Any = store.get_session(sid)
    record["tasks"] = [
        {"id": "t1", "kind": "search", "instruction": "first job", "status": "done", "conclusion": "", "detail": "", "sources": [], "created_at": "x", "under": ""},
        {"id": "t2", "kind": "draft", "instruction": "second job", "status": "running", "conclusion": "", "detail": "", "sources": [], "created_at": "x", "under": ""},
    ]
    store.save_session(record)


def test_english_task_limit_sentence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLACKOUT_MAX_TASKS_PER_SESSION", "2")
    sid: str = make_session("Plan the demo", "en")
    _fill_task_ceiling(sid)
    fake: Any = fake_client(payload("listen", "", task={"kind": "search", "instruction": "Look up one more thing", "under": ""}))
    with patch.object(conductor, "create_client", return_value=fake):
        result: Any = conductor.process_speech(sid, "Please look up one more thing", 1000.0)
    assert result["task_started"] is False
    assert result["reply"] == "That's a lot of background work for one session, so I'll note that as a question."
    assert result["reply"] == message("en", "task_limit")
    assert store.get_session(sid)["state"]["open_questions"] == ["Look up one more thing"]


def test_chinese_task_limit_sentence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLACKOUT_MAX_TASKS_PER_SESSION", "2")
    sid: str = make_session("写计划", "zh")
    _fill_task_ceiling(sid)
    fake: Any = fake_client(payload("listen", "", task={"kind": "search", "instruction": "再查一件新的事", "under": ""}))
    with patch.object(conductor, "create_client", return_value=fake):
        result: Any = conductor.process_speech(sid, "再帮我查一件新的事", 1000.0)
    assert result["task_started"] is False
    assert result["reply"] == "这次后台的事够多了，我先记下这个问题。"
    assert result["reply"] == message("zh", "task_limit")
    assert store.get_session(sid)["state"]["open_questions"] == ["再查一件新的事"]


# --- Nudges follow the most recent language --------------------------------

def _nudge_record(language: str, latest_user_text: str, point: str) -> Dict[str, Any]:
    record: Dict[str, Any] = {
        "language": language,
        "history": [{"role": "user", "content": latest_user_text, "at": "x"}],
        "tasks": [],
        "state": new_state("goal"),
    }
    record["state"]["main_points"] = [{"point": point, "status": "未展开", "under": ""}]
    return record


def test_nudge_follows_most_recent_language_english() -> None:
    record: Dict[str, Any] = _nudge_record("zh", "Let me think in English now", "the pricing plan")
    text: Optional[str] = conductor.nudge_text(record, 60, 0)
    assert text == "You haven't finished with the pricing plan. Still thinking?"


def test_nudge_follows_most_recent_language_chinese() -> None:
    record: Dict[str, Any] = _nudge_record("en", "还是用中文想吧", "定价方案")
    text: Optional[str] = conductor.nudge_text(record, 60, 0)
    assert text == "「定价方案」还没展开，还在想吗？"


def test_nudge_generic_follows_language() -> None:
    record: Dict[str, Any] = _nudge_record("en", "thinking quietly", "")
    record["state"]["main_points"] = []
    assert conductor.nudge_text(record, 60, 0) == "Still there? If you're stuck, try saying the smallest question."
    record["history"] = [{"role": "user", "content": "安静地想", "at": "x"}]
    assert conductor.nudge_text(record, 60, 0) == "还在吗？卡住的话，先说一个最小的问题。"


def test_nudge_does_not_split_a_latin_word_when_shortening() -> None:
    record: Dict[str, Any] = _nudge_record("en", "still thinking", "implementation planning continues")
    text: Optional[str] = conductor.nudge_text(record, 60, 0)
    assert text is not None
    # The point is shortened at a word boundary, never mid-word.
    assert text == "You haven't finished with implementation. Still thinking?"
    assert "implementatio" not in text.replace("implementation", "")
    record2: Dict[str, Any] = _nudge_record("en", "still thinking", "state tracking and more things")
    text2: Optional[str] = conductor.nudge_text(record2, 60, 0)
    assert text2 == "You haven't finished with state tracking. Still thinking?"


# --- AsrStream handshake languageBias order --------------------------------

async def _handshake_for(language: str) -> Dict[str, Any]:
    server: FakeASRServer = await FakeASRServer().start()
    stream: AsrStream = AsrStream(server.url, "test-key", language=language)
    try:
        assert await stream.connect() is True
        handshake: Any = server.handshake
        assert isinstance(handshake, dict)
        return dict(handshake)
    finally:
        await stream.close()
        await server.stop()


def test_asr_handshake_language_bias_chinese_first_for_zh() -> None:
    handshake: Dict[str, Any] = asyncio.run(_handshake_for("zh"))
    assert handshake["languageBias"] == ["Mandarin Chinese", "English"]


def test_asr_handshake_language_bias_english_first_for_en() -> None:
    handshake: Dict[str, Any] = asyncio.run(_handshake_for("en"))
    assert handshake["languageBias"] == ["English", "Mandarin Chinese"]


def test_asr_handshake_language_bias_default_is_chinese_first() -> None:
    async def run() -> Dict[str, Any]:
        server: FakeASRServer = await FakeASRServer().start()
        stream: AsrStream = AsrStream(server.url, "test-key")
        try:
            assert await stream.connect() is True
            handshake: Any = server.handshake
            assert isinstance(handshake, dict)
            return dict(handshake)
        finally:
            await stream.close()
            await server.stop()

    handshake: Dict[str, Any] = asyncio.run(run())
    assert handshake["languageBias"] == ["Mandarin Chinese", "English"]


# --- Markdown headings follow result["language"] ---------------------------

def _finish_with_failing_model(sid: str) -> Dict[str, Any]:
    mock: MagicMock = MagicMock()
    mock.responses.create.side_effect = Exception("model unavailable")
    with patch.object(summary_mod, "create_client", return_value=mock):
        result: Any = summary_mod.finish(sid)
    assert isinstance(result, dict)
    return result


def _seed_result_lists(sid: str, decision: str, todo: str) -> None:
    record: Any = store.get_session(sid)
    record["state"]["decisions"] = [decision]
    record["state"]["todos"] = [todo]
    record["state"]["open_questions"] = ["An open point" if decision.startswith("Use") else "没想清楚的问题"]
    store.save_session(record)


def test_markdown_headings_follow_result_language_en() -> None:
    sid: str = make_session("Plan the demo", "en")
    _seed_result_lists(sid, "Use the realtime mode", "Record a backup demo")
    result: Dict[str, Any] = _finish_with_failing_model(sid)
    assert result["language"] == "en"
    markdown: str = str(result["markdown"])
    assert "Use the realtime mode" in markdown
    assert "Record a backup demo" in markdown
    # No Chinese section headings in an English result.
    for heading in ("决定", "待办", "停车场", "还没想清楚", "前后矛盾", "没说完的点"):
        assert heading not in markdown
    headings: List[str] = [line for line in markdown.splitlines() if line.startswith("## ")]
    assert headings != []
    assert all(line.isascii() for line in headings)


def test_markdown_headings_follow_result_language_zh() -> None:
    sid: str = make_session("想清楚比赛方案", "zh")
    _seed_result_lists(sid, "用实时模式", "录一版备用演示")
    result: Dict[str, Any] = _finish_with_failing_model(sid)
    assert result["language"] == "zh"
    markdown: str = str(result["markdown"])
    assert "用实时模式" in markdown
    assert "录一版备用演示" in markdown
    assert "决定" in markdown
    assert "待办" in markdown


# --- POST /api/sessions stores language --------------------------------------

def test_create_session_stores_language() -> None:
    with TestClient(app) as client:
        created: Any = client.post("/api/sessions", json={"goal": "Plan the demo", "language": "en"})
        assert created.status_code == 200
        session_id: str = str(created.json()["session_id"])
        fetched: Any = client.get(f"/api/sessions/{session_id}")
        assert fetched.status_code == 200
        record: Dict[str, Any] = fetched.json()
        assert record["language"] == "en"
        assert record["state"]["goal"] == "Plan the demo"


def test_create_session_stores_chinese_language() -> None:
    with TestClient(app) as client:
        created: Any = client.post("/api/sessions", json={"goal": "写计划", "language": "zh"})
        assert created.status_code == 200
        session_id: str = str(created.json()["session_id"])
        fetched: Any = client.get(f"/api/sessions/{session_id}")
        assert fetched.status_code == 200
        assert fetched.json()["language"] == "zh"


def test_create_session_invalid_language_becomes_zh() -> None:
    with TestClient(app) as client:
        for bad in ("fr", "EN", "english", "", "zh-CN"):
            created: Any = client.post("/api/sessions", json={"goal": "Plan", "language": bad})
            assert created.status_code == 200
            session_id: str = str(created.json()["session_id"])
            fetched: Any = client.get(f"/api/sessions/{session_id}")
            assert fetched.status_code == 200
            assert fetched.json()["language"] == "zh"


def test_create_session_missing_language_defaults_to_zh() -> None:
    with TestClient(app) as client:
        created: Any = client.post("/api/sessions", json={"goal": "写计划"})
        assert created.status_code == 200
        session_id: str = str(created.json()["session_id"])
        fetched: Any = client.get(f"/api/sessions/{session_id}")
        assert fetched.status_code == 200
        assert fetched.json()["language"] == "zh"
