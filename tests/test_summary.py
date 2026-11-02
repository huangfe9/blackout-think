"""Summary tests."""
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List
from unittest.mock import MagicMock, patch

import pytest

import app.poster as poster_mod
import app.summary as summary
import app.tasks as tasks_mod
from app import store


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


def _count_nodes(node: Any) -> int:
    if not isinstance(node, dict):
        return 0
    return 1 + sum(_count_nodes(child) for child in node.get("children", []))


def fake(payload: Any) -> Any:
    mock: MagicMock = MagicMock(); resp: MagicMock = MagicMock(); resp.status = "completed"; resp.output_text = json.dumps(payload, ensure_ascii=False); mock.responses.create.return_value = resp; return mock


def make(with_history: bool = True) -> Any:
    record: Dict[str, Any] = store.create_session("目标原样")
    record["state"].update({"decisions": ["旧决定"], "todos": ["旧待办"], "parking_lot": ["停车原样"], "contradictions": ["矛盾原样"], "open_questions": ["旧问题"], "main_points": [{"point": "没展开点", "status": "未展开"}]})
    if with_history:
        record["history"] = [{"role": "user", "content": "说过话", "at": "x"}]
    store.save_session(record); return record["id"]


class CapturingExecutor:
    """Records poster work submitted in the background without running it."""

    def __init__(self) -> None:
        self.submitted: List[Any] = []

    def submit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        self.submitted.append((fn, args, kwargs))


def test_verbatim_fields() -> None:
    sid: Any = make()
    # Stage 6: flat lists come from the final pass only when each item cites
    # an utterance; parking lot, sketches, tasks and unexpanded points stay
    # verbatim from the record.
    mock: Any = fake({
        "title": "新标题", "summary": "一句话总结", "language": "zh",
        "decisions": [{"text": "模型决定", "from": [1]}],
        "todos": [{"text": "模型待办", "from": [1]}],
        "open_questions": [{"text": "模型问题", "from": [1]}],
        "contradictions": [{"text": "矛盾原样", "from": [1]}],
        "nodes": [], "poster": {"title": "", "blocks": []},
    })
    with patch.object(summary, "create_client", return_value=mock):
        result: Any = summary.finish(sid)
    assert result["parking_lot"] == ["停车原样"] and result["contradictions"] == ["矛盾原样"]
    assert result["unexpanded_points"] == []
    assert result["decisions"] == ["模型决定"]
    for heading in ["决定", "待办", "停车场", "还没想清楚", "前后矛盾"]:
        assert f"## {heading}" in result["markdown"]
    assert "## 没说完的点" not in result["markdown"]


def test_empty_model_lists_keep_state() -> None:
    sid: Any = make()
    mock: Any = fake({"title": "新标题", "decisions": [], "todos": [], "open_questions": []})
    with patch.object(summary, "create_client", return_value=mock):
        result: Any = summary.finish(sid)
    assert result["decisions"] == ["旧决定"]
    assert result["todos"] == ["旧待办"]
    assert result["open_questions"] == ["旧问题"]
    assert result["degraded"] is False


@pytest.mark.parametrize("field,state_key,state_value", [("decisions", "decisions", ["旧决定"]), ("todos", "todos", ["旧待办"]), ("open_questions", "open_questions", ["旧问题"])])
def test_model_list_longer_than_state_falls_back(field: str, state_key: str, state_value: Any) -> None:
    sid: Any = make()
    longer: Dict[str, Any] = {"title": "新标题", "decisions": ["旧决定"], "todos": ["旧待办"], "open_questions": ["旧问题"]}
    longer[field] = list(state_value) + ["模型编的新项甲", "模型编的新项乙"]
    assert len(longer[field]) > len(state_value)
    mock: Any = fake(longer)
    with patch.object(summary, "create_client", return_value=mock):
        result: Any = summary.finish(sid)
    assert result[field] == state_value
    assert "模型编的新项甲" not in result["markdown"]
    assert result["degraded"] is False


def test_model_list_longer_for_all_fields_falls_back() -> None:
    sid: Any = make()
    mock: Any = fake({"title": "新标题", "decisions": ["旧决定", "编的决定"], "todos": ["旧待办", "编的待办"], "open_questions": ["旧问题", "编的问题"]})
    with patch.object(summary, "create_client", return_value=mock):
        result: Any = summary.finish(sid)
    assert result["decisions"] == ["旧决定"]
    assert result["todos"] == ["旧待办"]
    assert result["open_questions"] == ["旧问题"]


def test_failure_and_budget_degraded() -> None:
    sid: Any = make()
    mock: MagicMock = MagicMock(); mock.responses.create.side_effect = Exception("boom")
    with patch.object(summary, "create_client", return_value=mock):
        result: Any = summary.finish(sid)
    assert result["degraded"] is True and result["decisions"] == ["旧决定"]
    sid2: Any = make()
    mock2: MagicMock = MagicMock(); exc: Exception = Exception("x"); setattr(exc, "status_code", 402); mock2.responses.create.side_effect = exc
    with patch.object(summary, "create_client", return_value=mock2):
        assert summary.finish(sid2)["degraded"] is True


def test_finished_no_second_model_call() -> None:
    sid: Any = make()
    mock: Any = fake({"title": "标题", "decisions": ["决定"], "todos": [], "open_questions": []})
    with patch.object(summary, "create_client", return_value=mock):
        summary.finish(sid)
        count: int = mock.responses.create.call_count
        summary.finish(sid)
    assert mock.responses.create.call_count == count


def test_empty_session_no_model_call() -> None:
    record: Dict[str, Any] = store.create_session("只有目标")
    mock: MagicMock = MagicMock()
    with patch.object(summary, "create_client", return_value=mock) as maker:
        result: Any = summary.finish(record["id"])
    assert not maker.called
    assert result["degraded"] is False
    assert store.get_session(record["id"])["status"] == "finished"


def test_markdown_omits_empty() -> None:
    record: Dict[str, Any] = store.create_session("只有目标")
    record["history"] = [{"role": "user", "content": "hi", "at": "x"}]
    store.save_session(record)
    mock: MagicMock = MagicMock(); mock.responses.create.side_effect = Exception("x")
    with patch.object(summary, "create_client", return_value=mock):
        result: Any = summary.finish(record["id"])
    assert "## 决定" not in result["markdown"]
    assert result["markdown"].startswith("# ")


def test_lock_free_during_summary_and_deleted_raises() -> None:
    sid: Any = make()
    started: threading.Event = threading.Event()
    release: threading.Event = threading.Event()
    def blocking() -> Any:
        started.set(); release.wait(timeout=5); return fake({"title": "t", "decisions": ["d"], "todos": [], "open_questions": []})
    box: Dict[str, Any] = {}
    def run() -> None:
        with patch.object(summary, "create_client", side_effect=blocking):
            box["r"] = summary.finish(sid)
    thread: threading.Thread = threading.Thread(target=run); thread.start()
    assert started.wait(timeout=2)
    lock: Any = store.get_lock(sid)
    assert lock.acquire(timeout=1); lock.release()
    release.set(); thread.join(timeout=5)
    assert box["r"]["title"] == "t"
    sid2: Any = make()
    def deleting() -> Any:
        store.delete_session(sid2); return fake({"title": "t", "decisions": [], "todos": [], "open_questions": []})
    with patch.object(summary, "create_client", side_effect=deleting):
        with pytest.raises(KeyError):
            summary.finish(sid2)
    assert store.get_session(sid2) is None


def test_finished_refreshes_only_task_changes_without_model() -> None:
    sid: Any = make()
    mock: Any = fake({"title": "标题", "decisions": ["决定"], "todos": [], "open_questions": []})
    with patch.object(summary, "create_client", return_value=mock):
        summary.finish(sid)
    record: Any = store.get_session(sid)
    record["tasks"] = [{"id": "t", "kind": "draft", "instruction": "写", "status": "done", "conclusion": "已写好", "detail": "正文", "sources": [], "created_at": "x"}]
    store.save_session(record)
    with patch.object(summary, "create_client", side_effect=AssertionError("no model")):
        result: Any = summary.finish(sid)
    assert result["tasks"][0]["conclusion"] == "已写好"
    assert "正文" in result["markdown"]


# --- Markdown thought tree and result.map --------------------------------

def test_markdown_includes_thought_tree_as_nested_list() -> None:
    sid: Any = make()
    mock: Any = fake({"title": "新标题", "decisions": ["旧决定"], "todos": ["旧待办"], "open_questions": ["旧问题"]})
    with patch.object(summary, "create_client", return_value=mock):
        result: Any = summary.finish(sid)
    markdown: str = result["markdown"]
    assert "## 思路" in markdown
    lines: List[str] = markdown.splitlines()
    heading_index: int = lines.index("## 思路")
    section: List[str] = lines[heading_index + 1:]
    # The goal is the root line and recorded nodes nest beneath it with
    # deeper indentation, in list form.
    assert section[0] == "- 目标原样"
    assert "  - 没展开点（未展开）" in section
    assert "  - 旧决定" in section
    assert "  - 旧待办" in section
    assert "  - 旧问题" in section
    # The tree section comes before the flat category sections.
    assert markdown.index("## 思路") < markdown.index("## 决定")


def test_result_map_present_and_built_from_state_not_model_wording() -> None:
    sid: Any = make()
    # With no clean nodes supplied by the final pass, the map falls back to
    # the stored state, so its nodes keep the state's own wording.
    mock: Any = fake({"title": "模型标题", "decisions": ["模型改写的决定"], "todos": ["模型改写的待办"], "open_questions": ["模型改写的问题"]})
    with patch.object(summary, "create_client", return_value=mock):
        result: Any = summary.finish(sid)
    assert isinstance(result.get("map"), dict)
    assert result["map"]["kind"] == "goal"
    assert result["map"]["text"] == "目标原样"
    texts: List[str] = _map_texts(result["map"])
    assert "没展开点" in texts
    assert "旧决定" in texts
    assert "旧待办" in texts
    assert "旧问题" in texts
    assert "模型改写的决定" not in texts
    assert "模型改写的待办" not in texts
    assert "模型改写的问题" not in texts
    # The persisted record carries the same state-derived map.
    loaded: Any = store.get_session(sid)
    assert loaded["result"]["map"]["text"] == "目标原样"
    assert "旧决定" in _map_texts(loaded["result"]["map"])


# --- Citation cleaning ----------------------------------------------------

def test_valid_from_numbers_ignores_out_of_range_and_non_integers() -> None:
    assert summary.valid_from_numbers([1, 2, 0, 3, 99, -1, "1", 1.5, True, False, None, 2], 2) == [1, 2]
    assert summary.valid_from_numbers("not-a-list", 3) == []
    assert summary.valid_from_numbers([], 3) == []
    assert summary.valid_from_numbers([3, 1, 3], 3) == [3, 1]


def test_clean_items_drops_items_without_valid_citation() -> None:
    cleaned: Any = summary.clean_items([
        {"text": " 有依据 ", "from": [1, 99, "2"]},
        {"text": "超出范围", "from": [99]},
        {"text": "没有引用", "from": []},
        {"text": "引用不是整数", "from": ["1", True]},
        {"text": "", "from": [1]},
        "not-an-item",
    ], 1)
    assert cleaned == [{"text": "有依据", "from": [1]}]


def test_clean_nodes_group_without_citation_stays_only_with_children() -> None:
    cleaned: Any = summary.clean_nodes([
        {"id": 1, "parent": -1, "label": "分组", "kind": "point", "from": []},
        {"id": 2, "parent": 1, "label": "叶子", "kind": "decision", "from": [1]},
        {"id": 3, "parent": -1, "label": "无依据叶子", "kind": "point", "from": []},
        {"id": 4, "parent": -1, "label": "空分组", "kind": "point", "from": []},
        {"id": 2, "parent": -1, "label": "重复编号", "kind": "point", "from": [1]},
        {"id": "5", "parent": -1, "label": "编号不是整数", "kind": "point", "from": [1]},
    ], 1)
    assert [node["id"] for node in cleaned] == [1, 2]
    assert cleaned[1]["label"] == "叶子"


# --- build_clean_map -------------------------------------------------------

def test_build_clean_map_nesting_and_unknown_parent_to_root() -> None:
    tree: Any = summary.build_clean_map([
        {"id": 1, "parent": -1, "label": "主点", "kind": "point", "from": [1]},
        {"id": 2, "parent": 1, "label": "子决定", "kind": "decision", "from": [1]},
        {"id": 3, "parent": 999, "label": "孤儿待办", "kind": "todo", "from": [1]},
    ], "总目标")
    assert tree["id"] == "goal" and tree["text"] == "总目标" and tree["kind"] == "goal"
    assert [child["text"] for child in tree["children"]] == ["主点", "孤儿待办"]
    assert tree["children"][0]["id"] == "1"
    assert [child["text"] for child in tree["children"][0]["children"]] == ["子决定"]
    assert tree["children"][0]["children"][0]["kind"] == "decision"


def test_build_clean_map_cycle_neither_hangs_nor_loses_node() -> None:
    tree: Any = summary.build_clean_map([
        {"id": 1, "parent": 2, "label": "甲", "kind": "point", "from": [1]},
        {"id": 2, "parent": 1, "label": "乙", "kind": "point", "from": [1]},
        {"id": 3, "parent": 3, "label": "自引用", "kind": "point", "from": [1]},
    ], "目标")
    assert sorted(_map_texts(tree)) == sorted(["目标", "甲", "乙", "自引用"])
    assert _count_nodes(tree) == 4


def test_build_clean_map_caps_at_60_nodes() -> None:
    nodes: List[Dict[str, Any]] = [
        {"id": index, "parent": -1, "label": f"节点{index}", "kind": "point", "from": [1]}
        for index in range(1, 80)
    ]
    tree: Any = summary.build_clean_map(nodes, "目标")
    # Root plus at most 60 model nodes.
    assert _count_nodes(tree) == 61
    assert len(tree["children"]) == 60


# --- Stage 6 final pass -----------------------------------------------------

def _make_two_utterances() -> Any:
    record: Dict[str, Any] = store.create_session("想清楚比赛方案")
    record["state"].update({
        "decisions": ["状态里的旧决定"], "todos": ["状态里的旧待办"],
        "parking_lot": ["停车场原样"], "contradictions": [],
        "open_questions": ["状态里的旧问题"],
        "main_points": [{"point": "未展开的点", "status": "未展开"}],
    })
    record["history"] = [
        {"role": "user", "content": "我们决定用甲方案", "at": "x"},
        {"role": "assistant", "content": "好的", "at": "x"},
        {"role": "user", "content": "还要写测试并想发布日期", "at": "x"},
    ]
    record["tasks"] = [{
        "id": "t1", "kind": "search", "instruction": "查资料", "status": "done",
        "conclusion": "查到的结论", "detail": "详情", "sources": [], "created_at": "x",
    }]
    store.save_session(record)
    return record["id"]


def _final_payload() -> Dict[str, Any]:
    return {
        "title": "最终标题", "summary": "这是最终总结。", "language": "en",
        "decisions": [{"text": "决定甲", "from": [1]}],
        "todos": [{"text": "写测试", "from": [2]}],
        "open_questions": [{"text": "何时发布", "from": [2]}],
        "contradictions": [{"text": "先快后慢有矛盾", "from": [1, 2]}],
        "nodes": [
            {"id": 1, "parent": -1, "label": "方案", "kind": "point", "from": [1]},
            {"id": 2, "parent": 1, "label": "决定甲", "kind": "decision", "from": [1]},
            {"id": 3, "parent": 1, "label": "写测试", "kind": "todo", "from": [2]},
        ],
        "poster": {"title": "最终标题", "blocks": [{"type": "list", "heading": "要点", "items": ["决定甲", "写测试"]}]},
    }


def test_finish_returns_summary_language_map_evidence_and_transcript() -> None:
    sid: Any = _make_two_utterances()
    mock: Any = fake(_final_payload())
    with patch.object(summary, "create_client", return_value=mock):
        with patch.object(poster_mod, "start_poster", return_value=True) as starter:
            result: Any = summary.finish(sid)
    assert starter.call_count == 1
    assert result["title"] == "最终标题"
    assert result["summary"] == "这是最终总结。"
    assert result["language"] == "en"
    assert result["decisions"] == ["决定甲"]
    assert result["todos"] == ["写测试"]
    assert result["open_questions"] == ["何时发布"]
    assert result["evidence"] == {
        "决定甲": ["我们决定用甲方案"],
        "写测试": ["还要写测试并想发布日期"],
        "何时发布": ["还要写测试并想发布日期"],
        "先快后慢有矛盾": ["我们决定用甲方案", "还要写测试并想发布日期"],
    }
    assert result["transcript"] == ["我们决定用甲方案", "还要写测试并想发布日期"]
    # The clean map, not the state map, is used when cited nodes exist.
    assert result["map"]["text"] == "想清楚比赛方案"
    assert [child["text"] for child in result["map"]["children"]] == ["方案"]
    assert [child["text"] for child in result["map"]["children"][0]["children"]] == ["决定甲", "写测试"]
    # Verbatim fields stay exactly as recorded.
    assert result["parking_lot"] == ["停车场原样"]
    assert result["tasks"][0]["conclusion"] == "查到的结论"
    assert result["tasks"][0]["detail"] == "详情"
    assert result["unexpanded_points"] == []
    assert result["degraded"] is False


def test_finish_list_emptied_by_citation_cleaning_falls_back_to_state() -> None:
    sid: Any = _make_two_utterances()
    payload: Dict[str, Any] = _final_payload()
    payload["decisions"] = [{"text": "没有有效引用的决定", "from": [99]}]
    payload["todos"] = []
    payload["open_questions"] = [{"text": "引用不是整数", "from": ["2"]}]
    payload["poster"] = {"title": "", "blocks": []}
    mock: Any = fake(payload)
    with patch.object(summary, "create_client", return_value=mock):
        result: Any = summary.finish(sid)
    assert result["decisions"] == ["状态里的旧决定"]
    assert result["todos"] == ["状态里的旧待办"]
    assert result["open_questions"] == ["状态里的旧问题"]
    assert "没有有效引用的决定" not in result["markdown"]


def test_finish_invented_item_without_citation_does_not_appear() -> None:
    sid: Any = _make_two_utterances()
    payload: Dict[str, Any] = _final_payload()
    payload["decisions"] = [
        {"text": "编造的决定", "from": []},
        {"text": "引用越界的决定", "from": [42]},
        {"text": "决定甲", "from": [1]},
    ]
    payload["poster"] = {"title": "", "blocks": []}
    mock: Any = fake(payload)
    with patch.object(summary, "create_client", return_value=mock):
        result: Any = summary.finish(sid)
    assert result["decisions"] == ["决定甲"]
    assert "编造的决定" not in result["markdown"]
    assert "引用越界的决定" not in result["markdown"]
    assert "编造的决定" not in result["evidence"]


def test_finish_starts_poster_once_and_does_not_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    sid: Any = _make_two_utterances()
    executor: CapturingExecutor = CapturingExecutor()
    monkeypatch.setattr(poster_mod, "_executor", executor)
    mock: Any = fake(_final_payload())
    with patch.object(summary, "create_client", return_value=mock):
        result: Any = summary.finish(sid)
    # The background job was submitted but never ran, yet finish returned
    # with the poster still drawing: finish does not wait for the drawing.
    assert len(executor.submitted) == 1
    assert result["poster"]["status"] == "drawing"
    record: Any = store.get_session(sid)
    assert record["poster"]["status"] == "drawing"
    assert record["poster"]["attempts"] == 1
    # A second finish with no changes uses the saved result and starts
    # nothing new, with no further model call.
    with patch.object(summary, "create_client", side_effect=AssertionError("no model")):
        again: Any = summary.finish(sid)
    assert again["title"] == "最终标题"
    assert len(executor.submitted) == 1


def test_finish_degraded_starts_no_poster() -> None:
    sid: Any = _make_two_utterances()
    mock: MagicMock = MagicMock(); mock.responses.create.side_effect = Exception("boom")
    with patch.object(summary, "create_client", return_value=mock):
        with patch.object(poster_mod, "start_poster") as starter:
            result: Any = summary.finish(sid)
    assert result["degraded"] is True
    assert starter.call_count == 0


def test_finish_no_poster_when_brief_has_no_items() -> None:
    sid: Any = _make_two_utterances()
    payload: Dict[str, Any] = _final_payload()
    payload["poster"] = {"title": "只有标题", "blocks": [{"type": "list", "heading": "空", "items": []}]}
    mock: Any = fake(payload)
    with patch.object(summary, "create_client", return_value=mock):
        with patch.object(poster_mod, "start_poster") as starter:
            result: Any = summary.finish(sid)
    assert result["degraded"] is False
    assert starter.call_count == 0


def test_finish_session_with_no_utterances_makes_no_model_call_or_poster() -> None:
    record: Dict[str, Any] = store.create_session("只有目标没有说话")
    mock: MagicMock = MagicMock()
    with patch.object(summary, "create_client", return_value=mock) as maker:
        with patch.object(poster_mod, "start_poster") as starter:
            result: Any = summary.finish(record["id"])
    assert not maker.called
    assert starter.call_count == 0
    assert result["degraded"] is False
    assert result["transcript"] == []


def test_finish_markdown_begins_with_title_and_summary_and_has_map_section() -> None:
    sid: Any = _make_two_utterances()
    payload: Dict[str, Any] = _final_payload()
    payload["language"] = "zh"
    mock: Any = fake(payload)
    with patch.object(summary, "create_client", return_value=mock):
        with patch.object(poster_mod, "start_poster", return_value=True):
            result: Any = summary.finish(sid)
    assert result["markdown"].startswith("# 最终标题\n\n这是最终总结。")
    assert "## 思路" in result["markdown"]
    assert "- 想清楚比赛方案" in result["markdown"]
    assert "  - 方案" in result["markdown"]


def test_finish_markdown_en_begins_with_title_and_summary_and_has_outline_section() -> None:
    sid: Any = _make_two_utterances()
    payload: Dict[str, Any] = _final_payload()
    payload["language"] = "en"
    mock: Any = fake(payload)
    with patch.object(summary, "create_client", return_value=mock):
        with patch.object(poster_mod, "start_poster", return_value=True):
            result: Any = summary.finish(sid)
    assert result["markdown"].startswith("# 最终标题\n\n这是最终总结。")
    assert "## Outline" in result["markdown"]
    assert "## 思路" not in result["markdown"]
    assert "- 想清楚比赛方案" in result["markdown"]
    assert "  - 方案" in result["markdown"]


def test_finish_model_failure_degraded_empty_summary_and_state_map() -> None:
    sid: Any = _make_two_utterances()
    mock: MagicMock = MagicMock(); mock.responses.create.side_effect = Exception("boom")
    with patch.object(summary, "create_client", return_value=mock):
        result: Any = summary.finish(sid)
    assert result["degraded"] is True
    assert result["summary"] == ""
    assert result["decisions"] == ["状态里的旧决定"]
    assert result["todos"] == ["状态里的旧待办"]
    texts: List[str] = _map_texts(result["map"])
    assert "未展开的点" in texts
    assert "状态里的旧决定" in texts
    assert result["transcript"] == ["我们决定用甲方案", "还要写测试并想发布日期"]


def test_build_markdown_keeps_clean_outline_after_late_task() -> None:
    sid: Any = _make_two_utterances()
    payload: Dict[str, Any] = _final_payload()
    payload["language"] = "zh"
    mock: Any = fake(payload)
    with patch.object(summary, "create_client", return_value=mock):
        with patch.object(poster_mod, "start_poster", return_value=True):
            result: Any = summary.finish(sid)
    clean_map: Any = result["map"]
    record: Any = store.get_session(sid)
    record["tasks"].append({"id": "late1", "kind": "search", "instruction": "查晚到的资料", "status": "running", "conclusion": "", "detail": "", "sources": [], "created_at": "x"})
    store.save_session(record)
    final: Any = SimpleNamespace(type="message", content=[SimpleNamespace(output_text="晚到结论。晚到细节", annotations=[])])
    resp: Any = SimpleNamespace(status="completed", output=[final], output_text="晚到结论。晚到细节")
    mock_task: MagicMock = MagicMock(); mock_task.responses.create.return_value = resp
    with patch.object(tasks_mod, "create_client", return_value=mock_task):
        tasks_mod.run_task(sid, "late1")
    loaded: Any = store.get_session(sid)
    assert loaded["result"]["map"] == clean_map
    markdown: str = summary.build_markdown(loaded["result"])
    assert markdown == loaded["result"]["markdown"]
    assert "## 思路" in markdown
    assert "- 想清楚比赛方案" in markdown
    assert "  - 方案" in markdown
    assert "    - 决定甲" in markdown or "  - 决定甲" in markdown
    assert "晚到结论" in markdown
    assert "方案" in _map_texts(loaded["result"]["map"])
