"""Stage 8C: the final page connects findings, repeats nothing, drafts."""
import base64
import copy
import json
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from app import poster, store, summary, tasks
from app.prompts import build_draft_user_content, build_final_user_content


@pytest.fixture(autouse=True)
def data_dir(tmp_path: Any, monkeypatch: Any) -> Any:
    monkeypatch.setenv("BLACKOUT_DATA_DIR", str(tmp_path))
    return tmp_path


def make_session(state: Dict[str, Any] = None, history: List[str] = None, task_list: List[Dict[str, Any]] = None) -> str:
    session_id: str = "a" * 32
    base_state: Dict[str, Any] = {
        "goal": "Plan the launch",
        "main_points": [{"point": "Next time", "status": "未展开"}],
        "parking_lot": [], "decisions": [], "todos": [],
        "open_questions": [], "contradictions": [],
    }
    if state:
        base_state.update(state)
    record: Dict[str, Any] = {
        "id": session_id, "created_at": store.now_iso(), "updated_at": store.now_iso(),
        "status": "active", "state": base_state,
        "history": [{"role": "user", "content": text, "at": store.now_iso()} for text in (history or ["First point."])],
        "tasks": task_list or [], "sketches": [], "result": None,
        "stats": {"user_turns": 0, "ai_spoke": 0, "listened": 0, "pull_backs": 0, "nudges": 0},
        "poster": {"status": "none", "version": 0, "error": "", "attempts": 0},
    }
    store.save_session(record)
    return session_id


def parsed_final(**overrides: Any) -> Dict[str, Any]:
    parsed: Dict[str, Any] = {
        "title": "Launch", "language": "en", "summary": "A summary.",
        "decisions": [], "todos": [], "open_questions": [], "contradictions": [],
        "parking_lot": [], "nodes": [],
        "first_draft": {"instruction": "", "from": []},
        "poster": {"title": "", "blocks": []},
    }
    parsed.update(overrides)
    return parsed


def test_completed_tasks_in_final_input() -> None:
    content: str = build_final_user_content(
        "Goal", ["What does it cost?"], {"goal": "Goal"},
        [
            {"kind": "search", "status": "done", "instruction": "Find the price", "conclusion": "It costs 10."},
            {"kind": "draft", "status": "done", "instruction": "Write", "conclusion": "Draft ready"},
            {"kind": "search", "status": "running", "instruction": "Later", "conclusion": ""},
        ],
    )
    payload: Dict[str, Any] = json.loads(content)
    assert payload["completed_tasks"] == [{"instruction": "Find the price", "conclusion": "It costs 10."}]
    assert "It costs 10." in payload["completed_task_conclusions"]


def test_model_parking_replaces_state_and_unexpanded_cleared(monkeypatch: Any) -> None:
    session_id: str = make_session(
        state={"parking_lot": ["Old parked thing", "Book flight"]},
        history=["Book the flight and renew the passport."],
    )
    fake: Dict[str, Any] = parsed_final(
        todos=[{"text": "Book flight", "from": [1]}],
        parking_lot=[{"text": "Renew passport", "from": [1]}],
    )
    monkeypatch.setattr(summary, "_call_final_once", lambda snapshot: copy.deepcopy(fake))
    result: Dict[str, Any] = summary.finish(session_id)
    assert result["parking_lot"] == ["Renew passport"]
    assert result["unexpanded_points"] == []
    assert result["evidence"]["Renew passport"] == ["Book the flight and renew the passport."]


def test_empty_model_parking_keeps_uncovered_and_drops_covered(monkeypatch: Any) -> None:
    session_id: str = make_session(
        state={"parking_lot": ["Renew passport", "Buy coffee beans"], "todos": []},
        history=["Renew the passport soon."],
    )
    fake: Dict[str, Any] = parsed_final(todos=[{"text": "Renew the passport", "from": [1]}], parking_lot=[])
    monkeypatch.setattr(summary, "_call_final_once", lambda snapshot: copy.deepcopy(fake))
    result: Dict[str, Any] = summary.finish(session_id)
    assert result["parking_lot"] == ["Buy coffee beans"]


def test_covered_by_todo_chinese_and_english() -> None:
    assert summary.covered_by_todo("续签护照", ["办理续签护照手续"]) is True
    assert summary.covered_by_todo("续签护照", ["买咖啡豆"]) is False
    assert summary.covered_by_todo("Renew passport", ["Renew the passport on Monday"]) is True
    assert summary.covered_by_todo("Book flight, renew passport!", ["book FLIGHT"]) is False
    assert summary.covered_by_todo("Renew passport", ["Renew passport"]) is True


def test_degraded_keeps_unexpanded_and_parking(monkeypatch: Any) -> None:
    session_id: str = make_session(state={"parking_lot": ["Parked idea"]})
    def boom(snapshot: Dict[str, Any]) -> Dict[str, Any]:
        raise RuntimeError("model down")
    monkeypatch.setattr(summary, "_call_final_once", boom)
    result: Dict[str, Any] = summary.finish(session_id)
    assert result["degraded"] is True
    assert result["parking_lot"] == ["Parked idea"]
    assert result["unexpanded_points"] == ["Next time"]


def test_save_result_parking_only_overwritten_when_degraded() -> None:
    session_id: str = make_session(state={"parking_lot": ["From state"]})
    good: Dict[str, Any] = {
        "title": "T", "goal": "Plan the launch", "summary": "S", "language": "en",
        "decisions": [], "todos": [], "parking_lot": ["From model"], "open_questions": [],
        "contradictions": [], "unexpanded_points": ["Stale"], "tasks": [], "sketches": [],
        "map": {}, "evidence": {}, "transcript": [], "poster": {}, "markdown": "", "degraded": False,
    }
    saved_good: Dict[str, Any] = summary._save_result(session_id, copy.deepcopy(good), False)
    assert saved_good["parking_lot"] == ["From model"]
    assert saved_good["unexpanded_points"] == []
    saved_bad: Dict[str, Any] = summary._save_result(session_id, copy.deepcopy(good), True)
    assert saved_bad["parking_lot"] == ["From state"]
    assert saved_bad["unexpanded_points"] == ["Next time"]


def test_sources_cited_first_limited_cleaned_and_filtered() -> None:
    annotation: Any = SimpleNamespace(url="https://example.com/cited", title="  Cited\n  Title  ")
    block: Any = SimpleNamespace(output_text="Answer.", annotations=[annotation])
    message_item: Any = SimpleNamespace(type="message", content=[block])
    long_title: str = "Long " + "x" * 100 + "\nnext line"
    search_item: Any = SimpleNamespace(type="web_search_call", results=[
        SimpleNamespace(url="https://brainly.com/q", title="Junk"),
        SimpleNamespace(url="https://chegg.com/q", title="Junk"),
        SimpleNamespace(url="https://good.example/a", title=long_title),
        SimpleNamespace(url="https://good.example/b", title="Second result"),
        SimpleNamespace(url="https://good.example/c", title="Third result"),
    ])
    resp: Any = SimpleNamespace(output=[search_item, message_item], output_text="Answer.")
    text, sources = tasks._message_text_and_sources(resp)
    assert text == "Answer."
    assert len(sources) == 3
    assert sources[0] == {"title": "Cited Title", "url": "https://example.com/cited"}
    assert "\n" not in sources[1]["title"]
    assert len(sources[1]["title"]) == 80
    assert all("brainly" not in s["url"] and "chegg" not in s["url"] for s in sources)


def test_english_draft_task_label(monkeypatch: Any) -> None:
    session_id: str = make_session(
        state={"goal": "Write a scope for the owner"},
        history=["Please write a one-page scope and send it to the owner."],
        task_list=[{"id": "t1", "kind": "draft", "instruction": "Write a one-page scope", "status": "running", "conclusion": "", "detail": "", "sources": [], "created_at": store.now_iso()}],
    )
    fake_resp: Any = SimpleNamespace(status="completed", output=[], output_text="Draft body")
    fake_client: Any = SimpleNamespace(responses=SimpleNamespace(create=lambda **kwargs: fake_resp))
    monkeypatch.setattr(tasks, "create_client", lambda: fake_client)
    tasks.run_task(session_id, "t1")
    record: Any = store.get_session_copy(session_id)
    assert record["tasks"][0]["status"] == "done"
    assert record["tasks"][0]["conclusion"] == "Draft ready"


def saved_for_draft() -> Dict[str, Any]:
    return {
        "title": "T", "goal": "Goal", "summary": "S", "language": "en", "degraded": False,
        "decisions": [], "todos": [], "parking_lot": [], "open_questions": [], "contradictions": [],
        "unexpanded_points": [], "tasks": [], "sketches": [], "map": {}, "evidence": {},
        "transcript": ["Write a scope."], "poster": {"status": "none", "version": 0, "error": ""}, "markdown": "",
    }


def test_maybe_start_draft_starts_auto_task(monkeypatch: Any) -> None:
    session_id: str = make_session(history=["Write a scope."])
    calls: List[Any] = []
    def fake_start(sid: str, kind: str, instruction: str, under: str = "", auto: bool = False) -> Dict[str, Any]:
        calls.append((sid, kind, instruction, under, auto))
        task: Dict[str, Any] = {"id": "d1", "kind": kind, "instruction": instruction, "status": "running", "conclusion": "", "detail": "", "sources": [], "created_at": store.now_iso(), "under": under, "auto": auto}
        with store.get_lock(sid):
            record: Any = store.get_session(sid)
            record["tasks"].append(task)
            store.save_session(record)
        return task
    monkeypatch.setattr(tasks, "start_task", fake_start)
    saved: Dict[str, Any] = saved_for_draft()
    parsed: Dict[str, Any] = parsed_final(first_draft={"instruction": "Write a one-page scope for the owner.", "from": [1]})
    summary._maybe_start_draft(session_id, saved, parsed)
    assert calls == [(session_id, "draft", "Write a one-page scope for the owner.", "", True)]
    assert saved["tasks"][0]["auto"] is True
    assert "Write a one-page scope" in saved["markdown"]


@pytest.mark.parametrize("parsed,saved", [
    ({"first_draft": {"instruction": "", "from": [1]}}, {"degraded": False, "transcript": ["x"]}),
    ({"first_draft": {"instruction": "Write it.", "from": [1]}}, {"degraded": True, "transcript": ["x"]}),
    ({"first_draft": {"instruction": "Write it.", "from": [99]}}, {"degraded": False, "transcript": ["x"]}),
    ({"first_draft": {"instruction": "Write it.", "from": []}}, {"degraded": False, "transcript": ["x"]}),
])
def test_maybe_start_draft_not_started(monkeypatch: Any, parsed: Dict[str, Any], saved: Dict[str, Any]) -> None:
    session_id: str = make_session()
    calls: List[Any] = []
    monkeypatch.setattr(tasks, "start_task", lambda *a, **k: calls.append((a, k)))
    full_saved: Dict[str, Any] = saved_for_draft()
    full_saved.update(saved)
    summary._maybe_start_draft(session_id, full_saved, parsed)
    assert calls == []


def test_maybe_start_draft_failure_keeps_result(monkeypatch: Any) -> None:
    session_id: str = make_session(history=["Write a scope."])
    def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("no")
    monkeypatch.setattr(tasks, "start_task", boom)
    saved: Dict[str, Any] = saved_for_draft()
    before: Dict[str, Any] = copy.deepcopy(saved)
    parsed: Dict[str, Any] = parsed_final(first_draft={"instruction": "Write it.", "from": [1]})
    summary._maybe_start_draft(session_id, saved, parsed)
    assert saved == before


def test_build_draft_user_content_includes_utterances() -> None:
    payload: Dict[str, Any] = json.loads(build_draft_user_content("Write it", "Goal", {}, ["First said.", "Second said."]))
    assert payload["utterances"] == [{"n": 1, "text": "First said."}, {"n": 2, "text": "Second said."}]
    assert json.loads(build_draft_user_content("Write it", "Goal", {}))["utterances"] == []


BRIEF: Dict[str, Any] = {"title": "My Title", "blocks": [{"type": "list", "heading": "Steps", "items": ["Do the thing"]}]}
PNG_ONE: bytes = poster.PNG_SIGNATURE + b"first"
PNG_TWO: bytes = poster.PNG_SIGNATURE + b"second"


class FakeImages:
    def __init__(self) -> None:
        self.prompts: List[str] = []
    def generate(self, **kwargs: Any) -> Any:
        self.prompts.append(str(kwargs.get("prompt", "")))
        data: bytes = PNG_ONE if len(self.prompts) == 1 else PNG_TWO
        return SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(data).decode("ascii"))])


class FakeImageClient:
    def __init__(self) -> None:
        self.images: FakeImages = FakeImages()
    def with_options(self, **kwargs: Any) -> Any:
        return self


def make_poster_session(attempts: int = 1) -> str:
    session_id: str = make_session()
    with store.get_lock(session_id):
        record: Any = store.get_session(session_id)
        record["poster"] = {"status": "drawing", "version": 0, "error": "", "attempts": attempts, "brief": copy.deepcopy(BRIEF), "language": "en"}
        store.save_session(record)
    return session_id


def test_check_picture_text_returns_missing(monkeypatch: Any) -> None:
    seen: Dict[str, Any] = {}
    def create(**kwargs: Any) -> Any:
        seen.update(kwargs)
        return SimpleNamespace(status="completed", output_text=json.dumps({"missing_or_wrong": ["My Title"]}))
    fake_client: Any = SimpleNamespace(responses=SimpleNamespace(create=create))
    monkeypatch.setattr(poster, "create_client", lambda: fake_client)
    assert poster.check_picture_text(PNG_ONE, BRIEF, "en") == ["My Title"]
    content: Any = seen["input"][0]["content"]
    assert content[1]["type"] == "input_image"
    assert "My Title" in content[0]["text"] and "Do the thing" in content[0]["text"]


def test_poster_check_empty_keeps_first(monkeypatch: Any) -> None:
    session_id: str = make_poster_session()
    client: FakeImageClient = FakeImageClient()
    monkeypatch.setattr(poster, "create_client", lambda: client)
    monkeypatch.setattr(poster, "check_picture_text", lambda data, brief, language: [])
    poster._draw_poster(session_id, copy.deepcopy(BRIEF), "en")
    path: Any = poster.poster_path(session_id)
    assert path.read_bytes() == PNG_ONE
    assert len(client.images.prompts) == 1


def test_poster_check_missing_redraws_once(monkeypatch: Any) -> None:
    session_id: str = make_poster_session()
    client: FakeImageClient = FakeImageClient()
    monkeypatch.setattr(poster, "create_client", lambda: client)
    monkeypatch.setattr(poster, "check_picture_text", lambda data, brief, language: ["My Title"])
    poster._draw_poster(session_id, copy.deepcopy(BRIEF), "en")
    path: Any = poster.poster_path(session_id)
    assert path.read_bytes() == PNG_TWO
    assert len(client.images.prompts) == 2
    assert "Earlier attempt got these wrong, write them exactly: My Title" in client.images.prompts[1]
    record: Any = store.get_session_copy(session_id)
    assert record["poster"]["checked"] is True
    assert record["poster"]["redrawn_for_text"] is True


def test_poster_check_exception_keeps_first(monkeypatch: Any) -> None:
    session_id: str = make_poster_session()
    client: FakeImageClient = FakeImageClient()
    monkeypatch.setattr(poster, "create_client", lambda: client)
    def boom(data: bytes, brief: Dict[str, Any], language: str) -> List[str]:
        raise RuntimeError("check failed")
    monkeypatch.setattr(poster, "check_picture_text", boom)
    poster._draw_poster(session_id, copy.deepcopy(BRIEF), "en")
    path: Any = poster.poster_path(session_id)
    assert path.read_bytes() == PNG_ONE
    assert len(client.images.prompts) == 1


def test_poster_no_attempts_left_no_redraw(monkeypatch: Any) -> None:
    session_id: str = make_poster_session(attempts=poster.max_poster_attempts())
    client: FakeImageClient = FakeImageClient()
    monkeypatch.setattr(poster, "create_client", lambda: client)
    monkeypatch.setattr(poster, "check_picture_text", lambda data, brief, language: ["My Title"])
    poster._draw_poster(session_id, copy.deepcopy(BRIEF), "en")
    path: Any = poster.poster_path(session_id)
    assert path.read_bytes() == PNG_ONE
    assert len(client.images.prompts) == 1
