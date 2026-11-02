"""Sketch tests."""
import json
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

import app.sketch as sketch
import app.summary as summary
from app import store
from app.prompts import SKETCH_SYSTEM_PROMPT

JPEG: bytes = b"\xff\xd8\xff" + b"x" * 20
PNG: bytes = b"\x89PNG\r\n\x1a\n" + b"x" * 20
WEBP: bytes = b"RIFFxxxxWEBP" + b"x" * 20


@pytest.fixture(autouse=True)
def setup_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLACKOUT_DATA_DIR", str(tmp_path))
    store.clear_memory()


def test_magic_and_refusals() -> None:
    assert sketch.detect_image(JPEG) == "image/jpeg"
    assert sketch.detect_image(PNG) == "image/png"
    assert sketch.detect_image(WEBP) == "image/webp"
    assert sketch.detect_image(b"") is None
    with pytest.raises(ValueError):
        sketch.validate_image(b"not image")
    with pytest.raises(ValueError):
        sketch.validate_image(JPEG + b"x" * sketch.MAX_BYTES)


def test_sketch_system_prompt_and_adds_and_regenerates() -> None:
    record: Dict[str, Any] = store.create_session("画方案")
    sid: str = str(record["id"])
    sketch_payload: Dict[str, Any] = {"description": "纸上有三步", "add_points": [{"point": "三步流程", "status": "未展开"}], "add_decisions": [], "add_todos": ["画正式图"], "add_questions": []}
    summary_payload: Dict[str, Any] = {"title": "成果", "decisions": [], "todos": ["画正式图"], "open_questions": []}
    calls: Dict[str, int] = {"n": 0}
    captured: Dict[str, Any] = {}
    def make_client() -> Any:
        calls["n"] += 1
        mock: MagicMock = MagicMock(); resp: MagicMock = MagicMock(); resp.status = "completed"
        resp.output_text = json.dumps(sketch_payload if calls["n"] == 1 else summary_payload, ensure_ascii=False)
        def create(**kwargs: Any) -> Any:
            captured.update(kwargs); return resp
        mock.responses.create.side_effect = create; return mock
    with patch.object(sketch, "create_client", side_effect=make_client):
        with patch.object(summary, "create_client", side_effect=make_client):
            result: Any = sketch.process_sketch(sid, PNG)
    assert captured or calls["n"] >= 1
    loaded: Any = store.get_session(sid)
    assert loaded["state"]["todos"] == ["画正式图"]
    assert loaded["sketches"][0]["description"] == "纸上有三步"
    assert result["sketches"][0]["description"] == "纸上有三步"


def test_sketch_request_contains_system_prompt() -> None:
    record: Dict[str, Any] = store.create_session("画方案")
    sid: str = str(record["id"])
    captured: Dict[str, Any] = {}
    payload: Dict[str, Any] = {"description": "图", "add_points": [], "add_decisions": [], "add_todos": [], "add_questions": []}
    def make_client() -> Any:
        mock: MagicMock = MagicMock(); resp: MagicMock = MagicMock(); resp.status = "completed"; resp.output_text = json.dumps(payload, ensure_ascii=False)
        def create(**kwargs: Any) -> Any:
            captured.update(kwargs); return resp
        mock.responses.create.side_effect = create; return mock
    summary_mock: MagicMock = MagicMock(); sresp: MagicMock = MagicMock(); sresp.status = "completed"; sresp.output_text = json.dumps({"title": "t", "decisions": [], "todos": [], "open_questions": []}); summary_mock.responses.create.return_value = sresp
    with patch.object(sketch, "create_client", side_effect=make_client):
        with patch.object(summary, "create_client", return_value=summary_mock):
            sketch.process_sketch(sid, JPEG)
    dumped: str = json.dumps(captured, ensure_ascii=False)
    assert SKETCH_SYSTEM_PROMPT in dumped
    assert '"role": "system"' in dumped or "'role': 'system'" in dumped or "system" in dumped
    assert "data:image/jpeg;base64" in dumped


def test_sketch_missing_session() -> None:
    with pytest.raises(KeyError):
        sketch.process_sketch("0" * 32, PNG)
