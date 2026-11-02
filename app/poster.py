"""Hand-drawn one-page poster drawn by Muse Image in the background."""
import base64
import binascii
import copy
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional

from budget import IMAGE_MODEL
from muse_client import DEFAULT_MODEL, create_client
from app import store
from app.messages import message
from app.state import recent_language

logger: logging.Logger = logging.getLogger(__name__)
_executor: ThreadPoolExecutor = ThreadPoolExecutor(max_workers=2)
PNG_SIGNATURE: bytes = b"\x89PNG\r\n\x1a\n"
BUDGET_ERROR: str = "预算已耗尽，本次无法继续，请稍后再试。"
FAILED_ERROR: str = "画图失败，请再试一次。"
_ZH_STYLE: str = "一张手绘风格的单页总结图（sketchnote），米白色纸张背景，黑色墨线，少量琥珀色强调，配简单贴切的小图标。"
_EN_STYLE: str = (
    "A hand-drawn one-page sketchnote on off-white paper, black ink lines "
    "with small amber accents and simple fitting icons."
)
_ZH_END: str = "所有文字必须准确无误、清晰可读，不要添加其他文字。"
_EN_END: str = "All text must be spelled exactly and be legible. Add no other text."
_CHECK_SCHEMA: Dict[str, Any] = {
    "type": "object", "additionalProperties": False,
    "properties": {"missing_or_wrong": {"type": "array", "items": {"type": "string"}}},
    "required": ["missing_or_wrong"],
}


def max_poster_attempts() -> int:
    """Per-session poster attempt ceiling."""
    try:
        return max(0, int(os.environ.get("BLACKOUT_MAX_POSTERS_PER_SESSION", "5")))
    except ValueError:
        return 5


def poster_path(session_id: str) -> Optional[Path]:
    """Path of the poster PNG for a valid session id, else None."""
    if not store.is_valid_id(session_id):
        return None
    return store.sessions_dir() / f"{session_id}.poster.png"


def _clean_text(value: Any) -> str:
    text: str = str(value) if value is not None else ""
    return " ".join(text.replace("\r", " ").replace("\n", " ").split())


def _block_sentence(block_type: str, heading: str, items: List[str], language: str) -> str:
    joined_zh: str = "、".join(items)
    joined_en: str = ", ".join(items)
    if language == "en":
        prefix: Dict[str, str] = {
            "timeline": "Draw a left-to-right timeline with these labelled stops",
            "flow": "Draw boxes joined by arrows in this flow",
            "list": "Draw a short list with these items",
            "compare": "Draw two columns comparing these items",
            "note": "Draw a small sticky note with these items",
        }
        sentence: str = f"{prefix.get(block_type, prefix['list'])}: {joined_en}."
        if heading:
            sentence += f" Heading: {heading}."
        return sentence
    prefix_zh: Dict[str, str] = {
        "timeline": "画一条从左到右的时间线，标注这些站点",
        "flow": "用方框和箭头依次连接这些步骤",
        "list": "画一个短列表，列出这些条目",
        "compare": "画成两列对比，列出这些条目",
        "note": "画一张小便利贴，写上这些内容",
    }
    sentence = f"{prefix_zh.get(block_type, prefix_zh['list'])}：{joined_zh}。"
    if heading:
        sentence += f"这一块的小标题是：{heading}。"
    return sentence


def build_poster_prompt(brief: Dict[str, Any], language: str) -> str:
    """Pure prompt builder: fixed style, title, one sentence per block, exact-text rule."""
    is_english: bool = language == "en"
    lines: List[str] = [_EN_STYLE if is_english else _ZH_STYLE]
    title: str = ""
    blocks: List[Any] = []
    if isinstance(brief, dict):
        title = _clean_text(brief.get("title", ""))
        raw_blocks: Any = brief.get("blocks")
        if isinstance(raw_blocks, list):
            blocks = raw_blocks
    if is_english:
        lines.append(f"Title: {title}." if title else "Title.")
    else:
        lines.append(f"标题：{title}。" if title else "标题。")
    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_type: str = _clean_text(block.get("type", "list")) or "list"
        heading: str = _clean_text(block.get("heading", ""))
        raw_items: Any = block.get("items")
        items: List[str] = []
        if isinstance(raw_items, list):
            for item in raw_items:
                cleaned: str = _clean_text(item)
                if cleaned:
                    items.append(cleaned)
        lines.append(_block_sentence(block_type, heading, items, "en" if is_english else "zh"))
    lines.append(_EN_END if is_english else _ZH_END)
    return " ".join(lines)


def _expected_texts(brief: Dict[str, Any]) -> List[str]:
    texts: List[str] = []
    if not isinstance(brief, dict):
        return texts
    title: str = _clean_text(brief.get("title", ""))
    if title:
        texts.append(title)
    blocks: Any = brief.get("blocks")
    if isinstance(blocks, list):
        for block in blocks:
            if not isinstance(block, dict):
                continue
            heading: str = _clean_text(block.get("heading", ""))
            if heading:
                texts.append(heading)
            items: Any = block.get("items")
            if isinstance(items, list):
                for item in items:
                    cleaned: str = _clean_text(item)
                    if cleaned:
                        texts.append(cleaned)
    return texts


def check_picture_text(png_bytes: bytes, brief: Dict[str, Any], language: str) -> List[str]:
    """Read the picture back and list expected texts that are missing or wrong."""
    expected: List[str] = _expected_texts(brief)
    prompt: str = json.dumps({
        "language": language,
        "expected_texts": expected,
        "instruction": (
            "Look at this picture. Which of the expected texts (the title, headings and items) "
            "are missing from the picture or spelled differently in the picture, including repeated characters? "
            "Return exactly those expected texts in missing_or_wrong. If all are present and spelled exactly, return an empty list."
        ),
    }, ensure_ascii=False)
    encoded: str = base64.b64encode(png_bytes).decode("ascii")
    client: Any = create_client()
    resp: Any = client.responses.create(
        model=DEFAULT_MODEL,
        input=[{"role": "user", "content": [
            {"type": "input_text", "text": prompt},
            {"type": "input_image", "image_url": f"data:image/png;base64,{encoded}"},
        ]}],
        max_output_tokens=2000, reasoning={"effort": "low"},
        text={"format": {"type": "json_schema", "name": "blackout_poster_check", "schema": _CHECK_SCHEMA, "strict": True}},
    )
    status: Any = getattr(resp, "status", None)
    if isinstance(status, str) and status != "completed":
        raise RuntimeError("incomplete poster check")
    raw: Any = getattr(resp, "output_text", "")
    if not isinstance(raw, str) or not raw.strip():
        raise RuntimeError("empty poster check")
    parsed: Any = json.loads(raw)
    if not isinstance(parsed, dict):
        raise RuntimeError("bad poster check")
    missing: Any = parsed.get("missing_or_wrong")
    out: List[str] = []
    if isinstance(missing, list):
        for item in missing:
            if isinstance(item, str) and item.strip() and item.strip() not in out:
                out.append(item.strip())
    return out


def _attr(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def is_budget_error(exc: Exception) -> bool:
    """Detect HTTP 402."""
    if getattr(exc, "status_code", None) == 402:
        return True
    return getattr(getattr(exc, "response", None), "status_code", None) == 402


def _poster_slim(poster: Dict[str, Any]) -> Dict[str, Any]:
    version: Any = poster.get("version", 0)
    error: Any = poster.get("error", "")
    return {
        "status": str(poster.get("status", "none")),
        "version": version if isinstance(version, int) and not isinstance(version, bool) else 0,
        "error": error if isinstance(error, str) else "",
    }


def _sync_result(record: Dict[str, Any], poster: Dict[str, Any]) -> None:
    result: Any = record.get("result")
    if isinstance(result, dict):
        result["poster"] = _poster_slim(poster)


def _failure_text(record: Dict[str, Any], poster: Dict[str, Any], error: str) -> str:
    stored_language: Any = poster.get("language")
    language: str = stored_language if stored_language in ("zh", "en") else recent_language(record)
    if error == BUDGET_ERROR:
        return message(language, "poster_budget")
    if error == FAILED_ERROR:
        return message(language, "poster_failed")
    return error


def _save_png(session_id: str, data: bytes) -> None:
    path: Optional[Path] = poster_path(session_id)
    if path is None:
        raise ValueError("invalid session id")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path = path.parent / f".{session_id}.poster.tmp"
    tmp_path.write_bytes(data)
    try:
        os.chmod(tmp_path, 0o600)
    except Exception:
        pass
    os.replace(tmp_path, path)
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass


def _mark_failed(session_id: str, error: str) -> None:
    with store.get_lock(session_id):
        record: Optional[Dict[str, Any]] = store.get_session(session_id)
        if record is None:
            return
        poster: Dict[str, Any] = record.get("poster") if isinstance(record.get("poster"), dict) else {}
        poster["status"] = "failed"
        poster["error"] = _failure_text(record, poster, error)
        poster.setdefault("version", 0)
        poster.setdefault("attempts", 0)
        record["poster"] = poster
        _sync_result(record, poster)
        store.save_session(record)


def _poster_attempts(record: Optional[Dict[str, Any]]) -> int:
    if not isinstance(record, dict):
        return 0
    poster: Any = record.get("poster")
    if not isinstance(poster, dict):
        return 0
    attempts: Any = poster.get("attempts", 0)
    return attempts if isinstance(attempts, int) and not isinstance(attempts, bool) else 0


def _draw_poster(session_id: str, brief: Dict[str, Any], language: str) -> None:
    """Worker: generate, validate PNG, check its text, then save and mark done."""
    checked: bool = False
    redrawn: bool = False
    try:
        prompt: str = build_poster_prompt(brief, language)
        client: Any = create_client().with_options(timeout=180, max_retries=1)
        def generate(prompt_text: str) -> bytes:
            resp: Any = client.images.generate(
                model=IMAGE_MODEL, prompt=prompt_text, n=1, size="1536x1024", output_format="png",
                extra_body={"tool_enablement": {"enable_image_search": False, "enable_web_search": False, "enable_shell": False}},
            )
            data_list: Any = _attr(resp, "data")
            if not isinstance(data_list, list) or not data_list:
                raise RuntimeError("empty image response")
            encoded: Any = _attr(data_list[0], "b64_json")
            if not isinstance(encoded, str) or not encoded:
                raise RuntimeError("missing image data")
            try:
                image_data: bytes = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise RuntimeError("invalid image data") from exc
            if not image_data.startswith(PNG_SIGNATURE):
                raise RuntimeError("image is not a PNG")
            return image_data
        image_bytes: bytes = generate(prompt)
        missing: List[str] = []
        try:
            missing = check_picture_text(image_bytes, brief, language)
            checked = True
        except Exception:
            logger.exception("poster text check failed; using picture as it is")
            missing = []
        if missing:
            attempts: int = _poster_attempts(store.get_session_copy(session_id))
            if attempts < max_poster_attempts():
                second_prompt: str = prompt + " Earlier attempt got these wrong, write them exactly: " + ", ".join(missing)
                image_bytes = generate(second_prompt)
                redrawn = True
    except Exception as exc:
        logger.exception("poster drawing failed")
        _mark_failed(session_id, BUDGET_ERROR if is_budget_error(exc) else FAILED_ERROR)
        return
    with store.get_lock(session_id):
        record: Optional[Dict[str, Any]] = store.get_session(session_id)
        if record is None:
            return
        try:
            _save_png(session_id, image_bytes)
        except Exception as exc:
            logger.exception("poster saving failed")
            poster: Dict[str, Any] = record.get("poster") if isinstance(record.get("poster"), dict) else {}
            poster["status"] = "failed"
            poster["error"] = _failure_text(record, poster, BUDGET_ERROR if is_budget_error(exc) else FAILED_ERROR)
            poster.setdefault("version", 0)
            poster.setdefault("attempts", 0)
            record["poster"] = poster
            _sync_result(record, poster)
            store.save_session(record)
            return
        poster = record.get("poster") if isinstance(record.get("poster"), dict) else {}
        version: Any = poster.get("version", 0)
        poster["version"] = (version if isinstance(version, int) and not isinstance(version, bool) else 0) + 1
        poster["status"] = "done"
        poster["error"] = ""
        poster.setdefault("attempts", 0)
        if redrawn:
            poster["attempts"] = _poster_attempts(record) + 1
        poster["checked"] = checked
        poster["redrawn_for_text"] = redrawn
        record["poster"] = poster
        _sync_result(record, poster)
        store.save_session(record)


def start_poster(session_id: str, brief: Dict[str, Any], language: str) -> bool:
    """Mark drawing under the lock, then submit; False at the attempt limit or if drawing."""
    with store.get_lock(session_id):
        record: Optional[Dict[str, Any]] = store.get_session(session_id)
        if record is None:
            raise KeyError(session_id)
        existing: Dict[str, Any] = record.get("poster") if isinstance(record.get("poster"), dict) else {}
        attempts_value: Any = existing.get("attempts", 0)
        attempts: int = attempts_value if isinstance(attempts_value, int) and not isinstance(attempts_value, bool) else 0
        if str(existing.get("status", "none")) == "drawing":
            return False
        if attempts >= max_poster_attempts():
            return False
        version_value: Any = existing.get("version", 0)
        poster: Dict[str, Any] = {
            "brief": copy.deepcopy(brief),
            "language": language if language in ("zh", "en") else "zh",
            "status": "drawing",
            "version": version_value if isinstance(version_value, int) and not isinstance(version_value, bool) else 0,
            "error": "",
            "attempts": attempts + 1,
        }
        record["poster"] = poster
        _sync_result(record, poster)
        store.save_session(record)
    _executor.submit(_draw_poster, session_id, copy.deepcopy(brief), language)
    return True
