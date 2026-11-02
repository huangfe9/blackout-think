"""Poster tests for stage 6."""
import base64
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional

import pytest

import app.poster as poster
from app import store


PNG_BYTES: bytes = poster.PNG_SIGNATURE + b"fake-png-content"
BUDGET_MESSAGE: str = "预算已耗尽，本次无法继续，请稍后再试。"
FAILED_MESSAGE: str = "画图失败，请再试一次。"


class CapturingExecutor:
    """Executor fake that records work without running it."""

    def __init__(self) -> None:
        self.submitted: List[Any] = []

    def submit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        self.submitted.append((fn, args, kwargs))


class FakeImageClient:
    """Fake Muse client for poster drawing; never touches the network."""

    def __init__(
        self,
        encoded: str = "",
        error: Optional[Exception] = None,
        side_effect: Optional[Callable[[], None]] = None,
    ) -> None:
        self.encoded: str = encoded
        self.error: Optional[Exception] = error
        self.side_effect: Optional[Callable[[], None]] = side_effect
        self.generate_calls: List[Dict[str, Any]] = []
        self.with_options_calls: List[Dict[str, Any]] = []
        self.images: Any = self

    def with_options(self, **kwargs: Any) -> Any:
        self.with_options_calls.append(kwargs)
        return self

    def generate(self, **kwargs: Any) -> Any:
        self.generate_calls.append(kwargs)
        if self.side_effect is not None:
            self.side_effect()
        if self.error is not None:
            raise self.error
        return SimpleNamespace(data=[SimpleNamespace(b64_json=self.encoded)])


def _brief() -> Dict[str, Any]:
    return {
        "title": "我的思考总结",
        "blocks": [
            {"type": "timeline", "heading": "过程", "items": ["先想清楚", "再做决定"]},
            {"type": "list", "heading": "要点", "items": ["要点一"]},
        ],
    }


def _make_session() -> str:
    record: Dict[str, Any] = store.create_session("想清楚海报")
    return str(record["id"])


def _set_poster(session_id: str, **values: Any) -> None:
    record: Optional[Dict[str, Any]] = store.get_session(session_id)
    assert record is not None
    current: Dict[str, Any] = record.get("poster") if isinstance(record.get("poster"), dict) else {}
    current.update(values)
    record["poster"] = current
    store.save_session(record)


# --- build_poster_prompt -------------------------------------------------

def test_build_poster_prompt_chinese() -> None:
    brief: Dict[str, Any] = {
        "title": "比赛方案总结",
        "blocks": [
            {"type": "timeline", "heading": "步骤", "items": ["先调研", "再原型", "最后演示"]},
            {"type": "flow", "heading": "流程", "items": ["输入想法", "整理决定"]},
        ],
    }
    prompt: str = poster.build_poster_prompt(brief, "zh")
    assert "一张手绘风格的单页总结图（sketchnote），米白色纸张背景，黑色墨线，少量琥珀色强调，配简单贴切的小图标。" in prompt
    assert "标题：比赛方案总结。" in prompt
    for item in ("先调研", "再原型", "最后演示", "输入想法", "整理决定"):
        assert item in prompt
    assert "步骤" in prompt and "流程" in prompt
    assert prompt.endswith("所有文字必须准确无误、清晰可读，不要添加其他文字。")
    assert "\n" not in prompt and "\r" not in prompt


def test_build_poster_prompt_english() -> None:
    brief: Dict[str, Any] = {
        "title": "Demo plan",
        "blocks": [
            {"type": "compare", "heading": "Options", "items": ["fast prototype", "full build"]},
        ],
    }
    prompt: str = poster.build_poster_prompt(brief, "en")
    assert "A hand-drawn one-page sketchnote on off-white paper, black ink lines with small amber accents and simple fitting icons." in prompt
    assert "Title: Demo plan." in prompt
    assert "fast prototype" in prompt and "full build" in prompt
    assert "Options" in prompt
    assert prompt.endswith("All text must be spelled exactly and be legible. Add no other text.")
    assert "\n" not in prompt and "\r" not in prompt


def test_build_poster_prompt_flattens_newlines_from_user_text() -> None:
    brief: Dict[str, Any] = {
        "title": "第一行\n第二行",
        "blocks": [
            {"type": "note", "heading": "标题\r\n注入", "items": ["甲\n乙", "丙\r丁"]},
        ],
    }
    prompt: str = poster.build_poster_prompt(brief, "zh")
    assert "\n" not in prompt and "\r" not in prompt
    assert "第一行 第二行" in prompt
    assert "甲 乙" in prompt and "丙 丁" in prompt


def test_build_poster_prompt_unknown_block_type_falls_back_to_list() -> None:
    brief: Dict[str, Any] = {
        "title": "T",
        "blocks": [{"type": "mystery", "heading": "", "items": ["only item"]}],
    }
    zh_prompt: str = poster.build_poster_prompt(brief, "zh")
    assert "画一个短列表，列出这些条目" in zh_prompt
    assert "only item" in zh_prompt
    en_prompt: str = poster.build_poster_prompt(brief, "en")
    assert "Draw a short list with these items" in en_prompt
    assert "only item" in en_prompt


# --- start_poster --------------------------------------------------------

def test_start_poster_sets_drawing_and_saves(monkeypatch: pytest.MonkeyPatch) -> None:
    executor: CapturingExecutor = CapturingExecutor()
    monkeypatch.setattr(poster, "_executor", executor)
    session_id: str = _make_session()
    assert poster.start_poster(session_id, _brief(), "zh") is True
    assert len(executor.submitted) == 1
    record: Optional[Dict[str, Any]] = store.get_session(session_id)
    assert record is not None
    assert record["poster"]["status"] == "drawing"
    assert record["poster"]["attempts"] == 1
    assert record["poster"]["brief"] == _brief()
    # It is persisted, not merely held in memory.
    store.clear_memory()
    loaded: Optional[Dict[str, Any]] = store.load_session(session_id)
    assert loaded is not None
    # A poster left drawing by the (simulated) restart is marked failed on
    # load, but the drawing state was saved before the restart.
    assert loaded["poster"]["attempts"] == 1


def test_start_poster_second_call_while_drawing_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    executor: CapturingExecutor = CapturingExecutor()
    monkeypatch.setattr(poster, "_executor", executor)
    session_id: str = _make_session()
    assert poster.start_poster(session_id, _brief(), "zh") is True
    assert poster.start_poster(session_id, _brief(), "zh") is False
    assert len(executor.submitted) == 1
    record: Optional[Dict[str, Any]] = store.get_session(session_id)
    assert record is not None and record["poster"]["attempts"] == 1


def test_start_poster_attempt_limit_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    executor: CapturingExecutor = CapturingExecutor()
    monkeypatch.setattr(poster, "_executor", executor)
    monkeypatch.setenv("BLACKOUT_MAX_POSTERS_PER_SESSION", "2")
    assert poster.max_poster_attempts() == 2
    session_id: str = _make_session()
    assert poster.start_poster(session_id, _brief(), "zh") is True
    _set_poster(session_id, status="failed")
    assert poster.start_poster(session_id, _brief(), "zh") is True
    _set_poster(session_id, status="failed")
    assert poster.start_poster(session_id, _brief(), "zh") is False
    assert len(executor.submitted) == 2
    record: Optional[Dict[str, Any]] = store.get_session(session_id)
    assert record is not None and record["poster"]["attempts"] == 2


# --- worker --------------------------------------------------------------

def test_worker_saves_valid_png_and_marks_done(monkeypatch: pytest.MonkeyPatch) -> None:
    session_id: str = _make_session()
    encoded: str = base64.b64encode(PNG_BYTES).decode("ascii")
    client: FakeImageClient = FakeImageClient(encoded=encoded)
    monkeypatch.setattr(poster, "create_client", lambda: client)
    poster._draw_poster(session_id, _brief(), "zh")
    path: Optional[Path] = poster.poster_path(session_id)
    assert path is not None and path.is_file()
    assert path.read_bytes() == PNG_BYTES
    record: Optional[Dict[str, Any]] = store.get_session(session_id)
    assert record is not None
    assert record["poster"]["status"] == "done"
    assert record["poster"]["version"] == 1
    assert record["poster"]["error"] == ""
    # The image request itself: one landscape PNG, search tools off.
    assert len(client.generate_calls) == 1
    call: Dict[str, Any] = client.generate_calls[0]
    assert call["model"] == "muse-image-1.0"
    assert call["n"] == 1
    assert call["size"] == "1536x1024"
    assert call["output_format"] == "png"
    assert call["extra_body"] == {
        "tool_enablement": {
            "enable_image_search": False,
            "enable_web_search": False,
            "enable_shell": False,
        }
    }
    assert "我的思考总结" in call["prompt"]


def test_worker_refuses_non_png_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    session_id: str = _make_session()
    encoded: str = base64.b64encode(b"this is not a png").decode("ascii")
    client: FakeImageClient = FakeImageClient(encoded=encoded)
    monkeypatch.setattr(poster, "create_client", lambda: client)
    poster._draw_poster(session_id, _brief(), "zh")
    path: Optional[Path] = poster.poster_path(session_id)
    assert path is not None and not path.exists()
    record: Optional[Dict[str, Any]] = store.get_session(session_id)
    assert record is not None
    assert record["poster"]["status"] == "failed"
    assert record["poster"]["error"] == FAILED_MESSAGE


def test_worker_invalid_base64_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    session_id: str = _make_session()
    client: FakeImageClient = FakeImageClient(encoded="%%%not-base64%%%")
    monkeypatch.setattr(poster, "create_client", lambda: client)
    poster._draw_poster(session_id, _brief(), "zh")
    record: Optional[Dict[str, Any]] = store.get_session(session_id)
    assert record is not None
    assert record["poster"]["status"] == "failed"
    assert record["poster"]["error"] == FAILED_MESSAGE
    path: Optional[Path] = poster.poster_path(session_id)
    assert path is not None and not path.exists()


def test_worker_budget_error_gives_budget_message(monkeypatch: pytest.MonkeyPatch) -> None:
    session_id: str = _make_session()
    error: Exception = Exception("budget")
    setattr(error, "status_code", 402)
    client: FakeImageClient = FakeImageClient(error=error)
    monkeypatch.setattr(poster, "create_client", lambda: client)
    poster._draw_poster(session_id, _brief(), "zh")
    record: Optional[Dict[str, Any]] = store.get_session(session_id)
    assert record is not None
    assert record["poster"]["status"] == "failed"
    assert record["poster"]["error"] == BUDGET_MESSAGE


def test_worker_generic_failure_gives_short_message(monkeypatch: pytest.MonkeyPatch) -> None:
    session_id: str = _make_session()
    client: FakeImageClient = FakeImageClient(error=RuntimeError("boom"))
    monkeypatch.setattr(poster, "create_client", lambda: client)
    poster._draw_poster(session_id, _brief(), "en")
    record: Optional[Dict[str, Any]] = store.get_session(session_id)
    assert record is not None
    assert record["poster"]["status"] == "failed"
    assert record["poster"]["error"] == FAILED_MESSAGE


def test_session_deleted_during_drawing_leaves_no_file(monkeypatch: pytest.MonkeyPatch) -> None:
    session_id: str = _make_session()
    encoded: str = base64.b64encode(PNG_BYTES).decode("ascii")
    client: FakeImageClient = FakeImageClient(
        encoded=encoded,
        side_effect=lambda: store.delete_session(session_id),
    )
    monkeypatch.setattr(poster, "create_client", lambda: client)
    poster._draw_poster(session_id, _brief(), "zh")
    assert store.get_session(session_id) is None
    path: Optional[Path] = poster.poster_path(session_id)
    assert path is not None and not path.exists()


# --- deletion and stale state -------------------------------------------

def test_delete_session_removes_poster_file() -> None:
    session_id: str = _make_session()
    path: Optional[Path] = poster.poster_path(session_id)
    assert path is not None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(PNG_BYTES)
    assert path.is_file()
    assert store.delete_session(session_id) is True
    assert not path.exists()
    assert store.get_session(session_id) is None


def test_poster_still_drawing_on_load_becomes_failed() -> None:
    session_id: str = _make_session()
    _set_poster(session_id, status="drawing", attempts=1, version=0, error="")
    store.clear_memory()
    loaded: Optional[Dict[str, Any]] = store.load_session(session_id)
    assert loaded is not None
    assert loaded["poster"]["status"] == "failed"
    assert loaded["poster"]["error"]
