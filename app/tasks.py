"""Background search and drafting tasks."""
import json
import logging
import os
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from muse_client import DEFAULT_MODEL, create_client
from app import store, summary as summary_mod
from app.messages import message
from app.prompts import DRAFT_SYSTEM_PROMPT, SEARCH_SYSTEM_PROMPT, build_draft_user_content, build_search_user_content
from app.state import build_map, clean_text, recent_language, truncate_speech

logger: logging.Logger = logging.getLogger(__name__)
_executor: ThreadPoolExecutor = ThreadPoolExecutor(max_workers=4)
BUDGET_MESSAGE: str = "预算已耗尽，本次无法继续，请稍后再试。"
CAP_MESSAGE: str = "这次后台的事够多了，我先记下这个问题。"
_URL_RE: re.Pattern = re.compile(r"https?://\S+|www\.\S+")
_JUNK_SOURCE_DOMAINS: Tuple[str, ...] = ("brainly.", "chegg.", "quizlet.", "coursehero.")


def is_budget_error(exc: Exception) -> bool:
    """Detect HTTP 402."""
    if getattr(exc, "status_code", None) == 402:
        return True
    return getattr(getattr(exc, "response", None), "status_code", None) == 402


def max_tasks_per_session() -> int:
    """Per-session background-task ceiling."""
    try:
        return max(0, int(os.environ.get("BLACKOUT_MAX_TASKS_PER_SESSION", "12")))
    except ValueError:
        return 12


def normalize_instruction(instruction: Any) -> str:
    """Instruction with punctuation and spaces removed, for dedup."""
    return clean_text(str(instruction or ""))


def task_block_reason(record: Any, instruction: str) -> Optional[str]:
    """Return 'duplicate', 'cap', or None if a new task may start."""
    if not isinstance(record, dict):
        return None
    tasks_list: Any = record.get("tasks", [])
    if not isinstance(tasks_list, list):
        return None
    wanted: str = normalize_instruction(instruction)
    if wanted:
        for task in tasks_list:
            if isinstance(task, dict) and normalize_instruction(task.get("instruction", "")) == wanted:
                return "duplicate"
    if len(tasks_list) >= max_tasks_per_session():
        return "cap"
    return None


def _attr(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _text_blocks(message_value: Any) -> Tuple[str, List[Tuple[str, str]]]:
    texts: List[str] = []
    titled_urls: List[Tuple[str, str]] = []
    content: Any = _attr(message_value, "content")
    if isinstance(content, str):
        return content, titled_urls
    if isinstance(content, list):
        for block in content:
            text: Any = _attr(block, "output_text")
            if not isinstance(text, str):
                text = _attr(block, "text")
            if isinstance(text, str):
                texts.append(text)
            annotations: Any = _attr(block, "annotations") or []
            if isinstance(annotations, list):
                for ann in annotations:
                    url: Any = _attr(ann, "url")
                    title: Any = _attr(ann, "title")
                    if isinstance(url, str):
                        titled_urls.append((title if isinstance(title, str) else "", url))
    return "".join(texts), titled_urls


def _message_text_and_sources(resp: Any) -> Tuple[str, List[Dict[str, str]]]:
    output: Any = _attr(resp, "output")
    if not isinstance(output, list):
        text: Any = _attr(resp, "output_text")
        return (text if isinstance(text, str) else ""), []
    messages: List[Any] = [item for item in output if _attr(item, "type") == "message"]
    text: str = ""
    annotation_sources: List[Tuple[str, str]] = []
    if messages:
        text, annotation_sources = _text_blocks(messages[-1])
    sources: List[Dict[str, str]] = []
    seen: set = set()
    def add_source(title: str, url: str) -> None:
        parsed: Any = urlparse(url)
        if parsed.scheme not in ("http", "https") or url in seen or len(sources) >= 3:
            return
        host: str = str(parsed.hostname or "").lower()
        if any(domain in host for domain in _JUNK_SOURCE_DOMAINS):
            return
        seen.add(url)
        clean_title: str = " ".join(str(title or "").split())[:80]
        sources.append({"title": clean_title or url, "url": url})
    for title, url in annotation_sources:
        add_source(title, url)
    for item in output:
        if _attr(item, "type") != "web_search_call":
            continue
        results: Any = _attr(item, "results") or []
        if isinstance(results, list):
            for result in results:
                url: Any = _attr(result, "url")
                title: Any = _attr(result, "title")
                if isinstance(url, str):
                    add_source(title if isinstance(title, str) else url, url)
    return text, sources


def _split_conclusion(text: str) -> Tuple[str, str]:
    clean: str = text.strip()
    for index, char in enumerate(clean):
        if char in "。！？\n" or (char == "." and index + 1 < len(clean) and clean[index + 1] in " \n"):
            return clean[: index + 1].strip(), clean[index + 1 :].strip()
    return clean, ""


def _truncate_spoken(text: str) -> str:
    return truncate_speech(text)


def _clean_conclusion(text: str) -> str:
    clean: str = _URL_RE.sub("", text)
    for char in ("*", "#", "`"):
        clean = clean.replace(char, "")
    return _truncate_spoken(clean.strip())


def _finish_task(session_id: str, task_id: str, status: str, conclusion: str, detail: str, sources: List[Dict[str, str]], announcement: str) -> None:
    with store.get_lock(session_id):
        record: Any = store.get_session(session_id)
        if record is None:
            return
        for task in record.get("tasks", []):
            if isinstance(task, dict) and task.get("id") == task_id:
                task.update({"status": status, "conclusion": conclusion, "detail": detail, "sources": sources})
        if record.get("status") == "finished" and isinstance(record.get("result"), dict):
            result: Dict[str, Any] = dict(record["result"])
            result["tasks"] = json.loads(json.dumps(record.get("tasks", []), ensure_ascii=False))
            summary_value: Any = result.get("summary")
            has_final_pass: bool = not result.get("degraded") and isinstance(summary_value, str) and bool(summary_value.strip())
            if not has_final_pass:
                result["map"] = build_map(record.get("state", {}), record.get("tasks", []))
            result["markdown"] = summary_mod.build_markdown(result)
            record["result"] = result
        store.save_session(record)
    store.add_announcement(session_id, announcement)


def _run_search(goal: str, instruction: str) -> Tuple[str, str, List[Dict[str, str]]]:
    client: Any = create_client()
    resp: Any = client.responses.create(
        model=DEFAULT_MODEL,
        input=[{"role": "system", "content": SEARCH_SYSTEM_PROMPT}, {"role": "user", "content": build_search_user_content(instruction, goal)}],
        max_output_tokens=4000, reasoning={"effort": "low"},
        tools=[{"type": "web_search", "search_context_size": "medium"}], include=["web_search_call.results"],
    )
    status: Any = _attr(resp, "status")
    if isinstance(status, str) and status != "completed":
        raise RuntimeError("search incomplete")
    text, sources = _message_text_and_sources(resp)
    if not text.strip():
        raise RuntimeError("empty search result")
    conclusion, detail = _split_conclusion(text)
    return _clean_conclusion(conclusion), detail, sources


def _run_draft(goal: str, state: Dict[str, Any], instruction: str, utterances: Optional[List[str]] = None) -> str:
    client: Any = create_client()
    resp: Any = client.responses.create(
        model=DEFAULT_MODEL,
        input=[{"role": "system", "content": DRAFT_SYSTEM_PROMPT}, {"role": "user", "content": build_draft_user_content(instruction, goal, state, utterances or [])}],
        max_output_tokens=6000, reasoning={"effort": "medium"},
    )
    status: Any = _attr(resp, "status")
    if isinstance(status, str) and status != "completed":
        raise RuntimeError("draft incomplete")
    text, _sources = _message_text_and_sources(resp)
    if not text.strip():
        text_value: Any = _attr(resp, "output_text")
        text = text_value if isinstance(text_value, str) else ""
    if not text.strip():
        raise RuntimeError("empty draft")
    return text.strip()


def run_task(session_id: str, task_id: str) -> None:
    """Run one task synchronously; used by the executor and tests."""
    snapshot: Any = store.get_session_copy(session_id)
    if snapshot is None:
        return
    task: Any = next((t for t in snapshot.get("tasks", []) if isinstance(t, dict) and t.get("id") == task_id), None)
    if task is None:
        return
    kind: str = str(task.get("kind", "search"))
    instruction: str = str(task.get("instruction", ""))
    state_copy: Dict[str, Any] = snapshot.get("state", {})
    goal: str = str(state_copy.get("goal", ""))
    language: str = recent_language(snapshot)
    utterances: List[str] = []
    for entry in snapshot.get("history", []):
        if isinstance(entry, dict) and entry.get("role") == "user" and isinstance(entry.get("content"), str):
            utterances.append(entry["content"])
    try:
        if kind == "search":
            conclusion, detail, sources = _run_search(goal, instruction)
            announcement: str = message(language, "found", conclusion=conclusion)
            _finish_task(session_id, task_id, "done", conclusion, detail, sources, announcement)
        else:
            draft: str = _run_draft(goal, state_copy, instruction, utterances)
            _finish_task(session_id, task_id, "done", message(language, "draft_label"), draft, [], message(language, "draft_done"))
    except Exception as exc:
        logger.exception("background task failed")
        budget_hit: bool = is_budget_error(exc)
        announcement = message(language, "budget") if budget_hit else message(language, "task_failed")
        conclusion: str = message(language, "budget_label") if budget_hit else message(language, "task_failed_label")
        _finish_task(session_id, task_id, "failed", conclusion, "", [], announcement)


def start_task(session_id: str, kind: str, instruction: str, under: str = "", auto: bool = False) -> Optional[Dict[str, Any]]:
    """Create a task and submit it without blocking; None if refused.

    Refused when this session already started a task with the same
    instruction (ignoring punctuation and spaces), or when the session
    has reached BLACKOUT_MAX_TASKS_PER_SESSION (default 12).
    """
    task: Dict[str, Any] = {"id": uuid.uuid4().hex, "kind": kind, "instruction": instruction, "status": "running", "conclusion": "", "detail": "", "sources": [], "created_at": store.now_iso(), "under": under or "", "auto": bool(auto)}
    with store.get_lock(session_id):
        record: Any = store.get_session(session_id)
        if record is None:
            raise KeyError(session_id)
        if task_block_reason(record, instruction) is not None:
            return None
        record.setdefault("tasks", []).append(task)
        store.save_session(record)
    _executor.submit(run_task, session_id, task["id"])
    return task
