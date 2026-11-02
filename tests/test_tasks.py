"""Background task tests."""
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

import app.tasks as tasks
import app.summary as summary
from app import store
from app.state import build_map


@pytest.fixture(autouse=True)
def setup_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLACKOUT_DATA_DIR", str(tmp_path))
    store.clear_memory()


def _map_texts(node: Any) -> List[str]:
    out: List[str] = [str(node.get("text", ""))] if isinstance(node, dict) else []
    if isinstance(node, dict):
        for child in node.get("children", []):
            out.extend(_map_texts(child))
    return out


def search_response() -> Any:
    interim: Any = SimpleNamespace(type="message", content=[SimpleNamespace(output_text="正在查……", annotations=[])])
    citation: Any = SimpleNamespace(url="https://a.example/1", title="注释标题")
    bad: Any = SimpleNamespace(url="javascript:alert(1)", title="bad")
    final: Any = SimpleNamespace(type="message", content=[SimpleNamespace(output_text="这是结论。后面是细节。", annotations=[citation, bad])])
    results: List[Any] = [SimpleNamespace(title=f"来源{i}", url=f"https://a.example/{i}") for i in range(10)]
    call: Any = SimpleNamespace(type="web_search_call", results=results)
    return SimpleNamespace(status="completed", output=[interim, call, final], output_text="正在查……这是结论")


def make_task(kind: str = "search") -> Any:
    record: Dict[str, Any] = store.create_session("目标")
    task: Dict[str, Any] = {"id": "t1", "kind": kind, "instruction": "查资料", "status": "running", "conclusion": "", "detail": "", "sources": [], "created_at": "x"}
    record["tasks"] = [task]; store.save_session(record)
    return record["id"]


def test_search_last_message_sources() -> None:
    sid: Any = make_task()
    mock: MagicMock = MagicMock(); mock.responses.create.return_value = search_response()
    with patch.object(tasks, "create_client", return_value=mock):
        tasks.run_task(sid, "t1")
    record: Any = store.get_session(sid)
    task: Any = record["tasks"][0]
    assert task["status"] == "done" and task["conclusion"] == "这是结论。" and task["detail"] == "后面是细节。"
    assert len(task["sources"]) == 3
    assert all(s["url"].startswith("http") for s in task["sources"])
    assert task["sources"][0]["url"] == "https://a.example/1"
    assert store.drain_announcements(sid)[0]["text"] == "查到了：这是结论。"
    assert record["state"]["decisions"] == []
    kwargs: Any = mock.responses.create.call_args.kwargs
    assert kwargs["tools"] == [{"type": "web_search", "search_context_size": "medium"}]
    assert kwargs["include"] == ["web_search_call.results"]
    sent: str = json.dumps(kwargs, ensure_ascii=False)
    assert "查资料" in sent and "目标" in sent


def test_search_input_excludes_state() -> None:
    sid: Any = make_task()
    record: Any = store.get_session(sid)
    record["state"]["decisions"] = ["秘密决定XYZ"]
    store.save_session(record)
    mock: MagicMock = MagicMock(); mock.responses.create.return_value = search_response()
    with patch.object(tasks, "create_client", return_value=mock):
        tasks.run_task(sid, "t1")
    sent: str = json.dumps(mock.responses.create.call_args.kwargs, ensure_ascii=False)
    assert "秘密决定XYZ" not in sent


def test_empty_last_message_is_failure_not_interim() -> None:
    sid: Any = make_task()
    interim: Any = SimpleNamespace(type="message", content=[SimpleNamespace(output_text="正在查……", annotations=[])])
    empty_final: Any = SimpleNamespace(type="message", content=[SimpleNamespace(output_text="", annotations=[])])
    resp: Any = SimpleNamespace(status="completed", output=[interim, empty_final], output_text="正在查……")
    mock: MagicMock = MagicMock(); mock.responses.create.return_value = resp
    with patch.object(tasks, "create_client", return_value=mock):
        tasks.run_task(sid, "t1")
    task: Any = store.get_session(sid)["tasks"][0]
    assert task["status"] == "failed"
    assert "正在查" not in task["conclusion"]


def test_annotation_title_used_and_results_preferred() -> None:
    sid: Any = make_task()
    ann: Any = SimpleNamespace(url="https://only.example/x", title="只有注释的标题")
    final: Any = SimpleNamespace(type="message", content=[SimpleNamespace(output_text="结论。细节", annotations=[ann])])
    resp: Any = SimpleNamespace(status="completed", output=[final], output_text="结论")
    mock: MagicMock = MagicMock(); mock.responses.create.return_value = resp
    with patch.object(tasks, "create_client", return_value=mock):
        tasks.run_task(sid, "t1")
    sources: Any = store.get_session(sid)["tasks"][0]["sources"]
    assert sources == [{"title": "只有注释的标题", "url": "https://only.example/x"}]


def test_conclusion_strips_markdown_and_urls() -> None:
    sid: Any = make_task()
    final: Any = SimpleNamespace(type="message", content=[SimpleNamespace(output_text="**重要结论** 见 https://x.example/a #标题。**细节**保留", annotations=[])])
    resp: Any = SimpleNamespace(status="completed", output=[final], output_text="x")
    mock: MagicMock = MagicMock(); mock.responses.create.return_value = resp
    with patch.object(tasks, "create_client", return_value=mock):
        tasks.run_task(sid, "t1")
    task: Any = store.get_session(sid)["tasks"][0]
    assert "*" not in task["conclusion"] and "#" not in task["conclusion"] and "http" not in task["conclusion"]
    assert "**细节**" in task["detail"]
    long_final: Any = SimpleNamespace(type="message", content=[SimpleNamespace(output_text="结" * 100 + "。细节", annotations=[])])
    sid2: Any = make_task()
    mock2: MagicMock = MagicMock(); mock2.responses.create.return_value = SimpleNamespace(status="completed", output=[long_final], output_text="x")
    with patch.object(tasks, "create_client", return_value=mock2):
        tasks.run_task(sid2, "t1")
    assert len(store.get_session(sid2)["tasks"][0]["conclusion"]) <= 60


def test_dict_shaped_response_objects() -> None:
    sid: Any = make_task()
    resp: Dict[str, Any] = {"status": "completed", "output": [{"type": "message", "content": [{"output_text": "字典结论。细节", "annotations": [{"url": "https://d.example", "title": "字典来源"}]}]}], "output_text": "interim"}
    mock: MagicMock = MagicMock(); mock.responses.create.return_value = resp
    with patch.object(tasks, "create_client", return_value=mock):
        tasks.run_task(sid, "t1")
    task: Any = store.get_session(sid)["tasks"][0]
    assert task["conclusion"] == "字典结论。"
    assert task["sources"][0]["title"] == "字典来源"


def test_failed_and_budget_task_announced() -> None:
    sid: Any = make_task()
    mock: MagicMock = MagicMock(); mock.responses.create.side_effect = Exception("boom")
    with patch.object(tasks, "create_client", return_value=mock):
        tasks.run_task(sid, "t1")
    assert store.get_session(sid)["tasks"][0]["status"] == "failed"
    assert "没弄成" in store.drain_announcements(sid)[0]["text"]
    sid2: Any = make_task()
    mock2: MagicMock = MagicMock(); exc: Exception = Exception("x"); setattr(exc, "status_code", 402); mock2.responses.create.side_effect = exc
    with patch.object(tasks, "create_client", return_value=mock2):
        tasks.run_task(sid2, "t1")
    assert "预算" in store.drain_announcements(sid2)[0]["text"]


def test_draft_not_spoken() -> None:
    sid: Any = make_task("draft")
    mock: MagicMock = MagicMock(); mock.responses.create.return_value = SimpleNamespace(status="completed", output=[SimpleNamespace(type="message", content=[SimpleNamespace(output_text="草稿全文秘密", annotations=[])])], output_text="草稿全文秘密")
    with patch.object(tasks, "create_client", return_value=mock):
        tasks.run_task(sid, "t1")
    announcements: Any = store.drain_announcements(sid)
    assert announcements[0]["text"] == "写好了，放在成果页里。"
    assert "秘密" not in announcements[0]["text"]
    assert store.get_session(sid)["tasks"][0]["detail"] == "草稿全文秘密"
    kwargs: Any = mock.responses.create.call_args.kwargs
    assert kwargs["reasoning"] == {"effort": "medium"} and kwargs["max_output_tokens"] == 6000


def test_late_task_updates_finished_result() -> None:
    sid: Any = make_task()
    record: Any = store.get_session(sid)
    record["history"] = [{"role": "user", "content": "hi", "at": "x"}]
    store.save_session(record)
    mock_summary: MagicMock = MagicMock(); resp: MagicMock = MagicMock(); resp.status = "completed"; resp.output_text = json.dumps({"title": "成果", "decisions": [], "todos": [], "open_questions": []}, ensure_ascii=False); mock_summary.responses.create.return_value = resp
    with patch.object(summary, "create_client", return_value=mock_summary):
        summary.finish(sid)
    mock: MagicMock = MagicMock(); mock.responses.create.return_value = search_response()
    with patch.object(tasks, "create_client", return_value=mock):
        tasks.run_task(sid, "t1")
    loaded: Any = store.get_session(sid)
    assert loaded["result"]["tasks"][0]["status"] == "done"
    assert "这是结论" in loaded["result"]["markdown"]
    # A late result refreshes the star map too, not just the task list
    # and the Markdown: the finished task node appears in result.map.
    assert "这是结论。" in _map_texts(loaded["result"]["map"])
    with patch.object(summary, "create_client", side_effect=AssertionError("no model")):
        again: Any = summary.finish(sid)
    assert again["tasks"][0]["status"] == "done"
    assert "这是结论。" in _map_texts(again["map"])
    assert "这是结论" in again["markdown"]


def test_deleted_session_task_writes_nothing() -> None:
    sid: Any = make_task()
    store.delete_session(sid)
    tasks.run_task(sid, "t1")
    assert store.get_session(sid) is None
    assert store.drain_announcements(sid) == []


# --- `under` is recorded and mapped --------------------------------------

def test_task_records_under_and_build_map_nests_it_under_that_point() -> None:
    record: Dict[str, Any] = store.create_session("想清楚方案")
    sid: str = str(record["id"])
    record["state"]["main_points"] = [{"point": "语音", "status": "未展开", "under": ""}]
    store.save_session(record)
    with patch.object(tasks, "_executor") as executor:
        executor.submit.return_value = None
        started: Any = tasks.start_task(sid, "search", "查实时转写的价格", "语音")
    assert started is not None
    loaded: Any = store.get_session(sid)
    assert loaded["tasks"][0]["under"] == "语音"
    assert loaded["tasks"][0]["instruction"] == "查实时转写的价格"
    tree: Any = build_map(loaded["state"], loaded["tasks"])
    root_children: Dict[str, Any] = {str(c.get("text", "")): c for c in tree["children"]}
    assert "语音" in root_children
    # The running task shows its instruction, nested under its point,
    # and does not also leak to the root.
    nested_tasks: List[Any] = [c for c in root_children["语音"]["children"] if c.get("kind") == "task"]
    assert len(nested_tasks) == 1
    assert nested_tasks[0]["text"] == "查实时转写的价格"
    assert nested_tasks[0]["status"] == "running"
    assert all(c.get("kind") != "task" for c in tree["children"])


# --- Late task and the clean map ------------------------------------------

def _finish_with_clean_map(sid: Any) -> Any:
    record: Any = store.get_session(sid)
    record["history"] = [{"role": "user", "content": "我们决定用甲方案", "at": "x"}]
    store.save_session(record)
    payload: Dict[str, Any] = {
        "title": "最终标题", "summary": "这是最终总结。", "language": "zh",
        "decisions": [{"text": "决定甲", "from": [1]}], "todos": [], "open_questions": [], "contradictions": [],
        "nodes": [
            {"id": 1, "parent": -1, "label": "方案", "kind": "point", "from": [1]},
            {"id": 2, "parent": 1, "label": "决定甲", "kind": "decision", "from": [1]},
        ],
        "poster": {"title": "", "blocks": []},
    }
    mock: MagicMock = MagicMock(); resp: MagicMock = MagicMock(); resp.status = "completed"; resp.output_text = json.dumps(payload, ensure_ascii=False); mock.responses.create.return_value = resp
    with patch.object(summary, "create_client", return_value=mock):
        return summary.finish(sid)


def test_late_task_preserves_clean_map_when_final_pass_present() -> None:
    sid: Any = make_task()
    result: Any = _finish_with_clean_map(sid)
    assert result["degraded"] is False and result["summary"] == "这是最终总结。"
    clean_map: Any = result["map"]
    assert [child["text"] for child in clean_map["children"]] == ["方案"]
    mock: MagicMock = MagicMock(); mock.responses.create.return_value = search_response()
    with patch.object(tasks, "create_client", return_value=mock):
        tasks.run_task(sid, "t1")
    loaded: Any = store.get_session(sid)
    # The clean map is kept as it was; only tasks and Markdown refresh.
    assert loaded["result"]["map"] == clean_map
    assert "方案" in _map_texts(loaded["result"]["map"])
    assert loaded["result"]["tasks"][0]["status"] == "done"
    assert "这是结论" in loaded["result"]["markdown"]


def test_late_task_rebuilds_map_when_result_is_degraded() -> None:
    sid: Any = make_task()
    record: Any = store.get_session(sid)
    record["history"] = [{"role": "user", "content": "hi", "at": "x"}]
    store.save_session(record)
    mock_summary: MagicMock = MagicMock(); mock_summary.responses.create.side_effect = Exception("boom")
    with patch.object(summary, "create_client", return_value=mock_summary):
        result: Any = summary.finish(sid)
    assert result["degraded"] is True
    mock: MagicMock = MagicMock(); mock.responses.create.return_value = search_response()
    with patch.object(tasks, "create_client", return_value=mock):
        tasks.run_task(sid, "t1")
    loaded: Any = store.get_session(sid)
    assert loaded["result"]["tasks"][0]["status"] == "done"
    assert "这是结论。" in _map_texts(loaded["result"]["map"])
    assert "这是结论" in loaded["result"]["markdown"]


def test_late_task_rebuilds_map_when_summary_empty() -> None:
    # The pre-existing empty-summary result (no final pass content) is
    # covered by test_late_task_updates_finished_result; here a degraded
    # empty summary is rebuilt as well via the degraded case, and a
    # result whose summary is blank but not degraded also rebuilds.
    sid: Any = make_task()
    record: Any = store.get_session(sid)
    record["history"] = [{"role": "user", "content": "hi", "at": "x"}]
    store.save_session(record)
    mock_summary: MagicMock = MagicMock(); resp: MagicMock = MagicMock(); resp.status = "completed"; resp.output_text = json.dumps({"title": "成果", "decisions": [], "todos": [], "open_questions": []}, ensure_ascii=False); mock_summary.responses.create.return_value = resp
    with patch.object(summary, "create_client", return_value=mock_summary):
        summary.finish(sid)
    loaded_before: Any = store.get_session(sid)
    assert not str(loaded_before["result"].get("summary") or "").strip()
    mock: MagicMock = MagicMock(); mock.responses.create.return_value = search_response()
    with patch.object(tasks, "create_client", return_value=mock):
        tasks.run_task(sid, "t1")
    loaded: Any = store.get_session(sid)
    assert "这是结论。" in _map_texts(loaded["result"]["map"])
