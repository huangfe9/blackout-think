"""Paper sketch understanding."""
import base64
import copy
import json
import logging
from typing import Any, Dict, Optional

from muse_client import DEFAULT_MODEL, create_client
from app import store, summary
from app.prompts import SKETCH_SCHEMA, SKETCH_SYSTEM_PROMPT, build_sketch_user_content
from app.state import apply_additions

logger: logging.Logger = logging.getLogger(__name__)
MAX_BYTES: int = 8 * 1024 * 1024


def detect_image(data: bytes) -> Optional[str]:
    """Mime type from magic bytes."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def validate_image(data: bytes) -> str:
    """Return mime or raise ValueError with a friendly message."""
    if len(data) > MAX_BYTES:
        raise ValueError("图片太大，请控制在8MB以内。")
    mime: Optional[str] = detect_image(data)
    if mime is None:
        raise ValueError("只支持 JPEG、PNG 或 WebP 图片。")
    return mime


def _call_sketch(snapshot: Dict[str, Any], data: bytes, mime: str) -> Dict[str, Any]:
    state: Dict[str, Any] = snapshot.get("state", {})
    encoded: str = base64.b64encode(data).decode("ascii")
    client: Any = create_client()
    resp: Any = client.responses.create(
        model=DEFAULT_MODEL,
        input=[
            {"role": "system", "content": SKETCH_SYSTEM_PROMPT},
            {"role": "user", "content": [{"type": "input_text", "text": build_sketch_user_content(str(state.get("goal", "")), state)}, {"type": "input_image", "image_url": f"data:{mime};base64,{encoded}"}]},
        ],
        max_output_tokens=4000, reasoning={"effort": "low"},
        text={"format": {"type": "json_schema", "name": "blackout_sketch", "schema": SKETCH_SCHEMA, "strict": True}},
    )
    status: Any = getattr(resp, "status", None)
    if isinstance(status, str) and status != "completed":
        raise RuntimeError("incomplete sketch response")
    raw: Any = getattr(resp, "output_text", "")
    parsed: Any = json.loads(raw) if isinstance(raw, str) else {}
    if not isinstance(parsed, dict):
        raise RuntimeError("bad sketch response")
    return parsed


def _apply_sketch(session_id: str, parsed: Dict[str, Any]) -> None:
    with store.get_lock(session_id):
        record: Optional[Dict[str, Any]] = store.get_session(session_id)
        if record is None:
            raise KeyError(session_id)
        additions: Dict[str, Any] = {
            "add_points": parsed.get("add_points", []), "add_decisions": parsed.get("add_decisions", []),
            "add_todos": parsed.get("add_todos", []), "add_questions": parsed.get("add_questions", []),
        }
        record["state"] = apply_additions(record.get("state", {}), additions)
        description: str = str(parsed.get("description", "")) if isinstance(parsed.get("description", ""), str) else ""
        record.setdefault("sketches", []).append({"description": description, "added_at": store.now_iso()})
        store.save_session(record)


def process_sketch(session_id: str, data: bytes) -> Dict[str, Any]:
    """Snapshot, call model unlocked, re-lock/apply, regenerate result."""
    mime: str = validate_image(data)
    snapshot: Optional[Dict[str, Any]] = store.get_session_copy(session_id)
    if snapshot is None:
        raise KeyError(session_id)
    parsed: Dict[str, Any] = _call_sketch(copy.deepcopy(snapshot), data, mime)
    _apply_sketch(session_id, parsed)
    return summary.finish(session_id)
