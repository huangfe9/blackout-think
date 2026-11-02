"""One conductor turn and silence nudges."""
import copy
import json
import logging
import os
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from muse_client import DEFAULT_MODEL, create_client
from app import state as state_mod
from app import store, tasks as tasks_mod
from app.messages import message
from app.prompts import TURN_SCHEMA, TURN_SYSTEM_PROMPT, build_turn_user_content

logger: logging.Logger = logging.getLogger(__name__)
_last_spoke: Dict[str, float] = {}
_awaiting_end: set = set()
_pending_conflicts: Dict[str, Tuple[str, float]] = {}
_first_turn: Dict[str, float] = {}
_consecutive_failures: Dict[str, int] = {}
_last_failure_note: Dict[str, float] = {}
_awaiting_recovery: set = set()
_NUDGE_POINT_LIMIT: int = 16
_NUDGE_CUT_CHARS: str = " ，。！？；：、,.!?;:·…—–- \t"
CAP_REPLY: str = "这次后台的事够多了，我先记下这个问题。"
_END_WORD_RE: re.Pattern = re.compile(r"\b(stop|finish)\b", re.IGNORECASE)
_PENDING_TTL: float = 45.0
_FAILURE_NOTE_GAP: float = 120.0


class TurnResult(dict):
    """Dict result with attribute access."""
    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


def clear_memory() -> None:
    """Clear in-memory conductor state."""
    _last_spoke.clear()
    _awaiting_end.clear()
    _pending_conflicts.clear()
    _first_turn.clear()
    _consecutive_failures.clear()
    _last_failure_note.clear()
    _awaiting_recovery.clear()


def is_awaiting_end(session_id: str) -> bool:
    """Whether the session is waiting for an end confirmation."""
    return session_id in _awaiting_end


def _end_reply(session_id: str) -> str:
    record: Optional[Dict[str, Any]] = store.get_session_copy(session_id)
    language: str = state_mod.recent_language(record) if isinstance(record, dict) else "zh"
    return message(language, "end_reply")


def note_spoken(session_id: str, text: str, kind: str, now: Any = None) -> None:
    """Record speech actually delivered outside a turn (announcement/nudge)."""
    if kind not in ("announcement", "nudge") or not str(text).strip():
        return
    ts: float = _now_ts(now)
    with store.get_lock(session_id):
        record: Optional[Dict[str, Any]] = store.get_session(session_id)
        if record is None:
            raise KeyError(session_id)
        record.setdefault("history", []).append({"role": "assistant", "content": str(text), "at": store.now_iso()})
        stats: Dict[str, Any] = record.setdefault("stats", {"user_turns": 0, "ai_spoke": 0, "listened": 0, "pull_backs": 0, "nudges": 0})
        stats["ai_spoke"] = int(stats.get("ai_spoke", 0)) + 1
        if kind == "nudge":
            stats["nudges"] = int(stats.get("nudges", 0)) + 1
        _last_spoke[session_id] = ts
        store.save_session(record)


def _env_seconds(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def is_budget_error(exc: Exception) -> bool:
    """Detect HTTP 402."""
    if getattr(exc, "status_code", None) == 402:
        return True
    return getattr(getattr(exc, "response", None), "status_code", None) == 402


def _status_of(exc: Exception) -> Optional[int]:
    status: Any = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(exc, "status", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):
        return None


def _failure_text(exc: Exception) -> str:
    parts: List[str] = [str(exc)]
    for attr in ("body", "message", "code"):
        value: Any = getattr(exc, attr, None)
        if value is not None:
            parts.append(str(value))
    response: Any = getattr(exc, "response", None)
    if response is not None:
        for attr in ("text", "content", "body"):
            value = getattr(response, attr, None)
            if value is not None:
                parts.append(str(value))
    return " ".join(parts).lower()


def _failure_kind(exc: Exception) -> str:
    """Classify a model failure without keeping its text."""
    if is_budget_error(exc):
        return "budget"
    status: Optional[int] = _status_of(exc)
    if status in (401, 403):
        return "key"
    if status == 429:
        text: str = _failure_text(exc)
        if any(word in text for word in ("quota", "credit", "billing", "insufficient")):
            return "credits"
    return "network"


def truncate_reply(reply: str) -> str:
    """Truncate spoken reply at a real boundary (shared speech rule)."""
    return state_mod.truncate_speech(reply.strip())


def _short_point(point: str) -> str:
    """At most 16 chars, cut at a space or punctuation inside the limit if any."""
    text: str = str(point)
    if len(text) <= _NUDGE_POINT_LIMIT:
        return text
    cut: str = text[:_NUDGE_POINT_LIMIT]
    if " " in cut:
        trimmed_space: str = cut[: cut.rfind(" ")].rstrip(_NUDGE_CUT_CHARS)
        if trimmed_space:
            return trimmed_space
    pos: int = max(cut.rfind(mark) for mark in _NUDGE_CUT_CHARS)
    if pos >= 1:
        trimmed: str = cut[:pos].rstrip(_NUDGE_CUT_CHARS)
        if trimmed:
            return trimmed
    return cut


def _now_ts(now: Any) -> float:
    if now is None:
        return time.time()
    if isinstance(now, datetime):
        return now.timestamp()
    return float(now)


def turns_since_ai_spoke(history: List[Dict[str, str]]) -> int:
    """User turns since the last assistant message in history."""
    count: int = 0
    for entry in reversed(history):
        role: str = str(entry.get("role", ""))
        if role == "assistant":
            break
        if role == "user":
            count += 1
    return count


def _reflect_due(session_id: str, record: Dict[str, Any], ts: float) -> bool:
    """Whether a status reflection is due for this turn."""
    if session_id not in _first_turn:
        _first_turn[session_id] = ts
    history: List[Dict[str, str]] = []
    for item in record.get("history", []):
        if isinstance(item, dict):
            history.append({"role": str(item.get("role", "user")), "content": str(item.get("content", ""))})
    if turns_since_ai_spoke(history) < _env_int("BLACKOUT_REFLECT_TURNS", 10):
        return False
    baseline: float = _first_turn[session_id]
    last: Optional[float] = _last_spoke.get(session_id)
    if last is not None:
        baseline = max(baseline, last)
    return ts - baseline >= _env_seconds("BLACKOUT_REFLECT_SECONDS", 150.0)


def _call_model_once(record: Dict[str, Any], text: str, seconds_since: Optional[float]) -> Dict[str, Any]:
    state: Dict[str, Any] = record.get("state", {})
    history: List[Dict[str, str]] = []
    for item in record.get("history", [])[-12:]:
        if isinstance(item, dict):
            history.append({"role": str(item.get("role", "user")), "content": str(item.get("content", ""))})
    full_history: List[Dict[str, str]] = []
    for item in record.get("history", []):
        if isinstance(item, dict):
            full_history.append({"role": str(item.get("role", "user")), "content": str(item.get("content", ""))})
    running: List[str] = []
    for task in record.get("tasks", []):
        if isinstance(task, dict) and task.get("status") == "running":
            running.append(str(task.get("instruction", "")))
    turns_since: int = turns_since_ai_spoke(full_history)
    session_id: str = str(record.get("id", ""))
    reflect_due: bool = _reflect_due(session_id, record, time.time()) if session_id else False
    pending_conflict: Optional[str] = None
    if session_id:
        pending_entry: Optional[Tuple[str, float]] = _pending_conflicts.get(session_id)
        if pending_entry is not None and pending_entry[0]:
            pending_conflict = pending_entry[0]
    content: str = build_turn_user_content(str(state.get("goal", "")), state, history, text, running, seconds_since, turns_since, reflect_due, pending_conflict_question=pending_conflict)
    client: Any = create_client()
    resp: Any = client.responses.create(
        model=DEFAULT_MODEL,
        input=[{"role": "system", "content": TURN_SYSTEM_PROMPT}, {"role": "user", "content": content}],
        max_output_tokens=4000, reasoning={"effort": "low"},
        text={"format": {"type": "json_schema", "name": "blackout_turn", "schema": TURN_SCHEMA, "strict": True}},
    )
    status: Any = getattr(resp, "status", None)
    if isinstance(status, str) and status != "completed":
        raise RuntimeError("incomplete response")
    raw: Any = getattr(resp, "output_text", "")
    if not isinstance(raw, str) or not raw.strip():
        raise RuntimeError("empty response")
    parsed: Any = json.loads(raw)
    if not isinstance(parsed, dict) or "action" not in parsed:
        raise RuntimeError("bad turn")
    return parsed


def _call_model_with_retry(record: Dict[str, Any], text: str, seconds_since: Optional[float]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    for attempt in range(2):
        try:
            return _call_model_once(record, text, seconds_since), None
        except Exception as exc:
            kind: str = _failure_kind(exc)
            logger.warning("conductor model failed: %s status=%s", type(exc).__name__, _status_of(exc))
            if kind in ("budget", "key", "credits"):
                return None, kind
            if attempt == 1:
                return None, kind
    return None, "network"


def _save_turn(record: Dict[str, Any], text: str, reply: str, action: str) -> None:
    record.setdefault("history", []).append({"role": "user", "content": text, "at": store.now_iso()})
    if reply:
        record["history"].append({"role": "assistant", "content": reply, "at": store.now_iso()})
    stats: Dict[str, Any] = record.setdefault("stats", {"user_turns": 0, "ai_spoke": 0, "listened": 0, "pull_backs": 0, "nudges": 0})
    stats["user_turns"] = int(stats.get("user_turns", 0)) + 1
    if action == "listen":
        stats["listened"] = int(stats.get("listened", 0)) + 1
    if reply:
        stats["ai_spoke"] = int(stats.get("ai_spoke", 0)) + 1
    if action == "pull_back":
        stats["pull_backs"] = int(stats.get("pull_backs", 0)) + 1
    store.save_session(record)


def _result(text: str, action: str, reply: str, reason: str = "", end: bool = False, task_started: bool = False, budget: bool = False, ai_failed: str = "") -> TurnResult:
    data: Dict[str, Any] = {"transcript": text, "action": action, "reply": reply, "reason": reason, "end": end, "task_started": task_started, "budget_exhausted": budget, "ai_failed": ai_failed}
    return TurnResult(data)


def _end_locked(session_id: str, record: Dict[str, Any], text: str) -> TurnResult:
    _awaiting_end.discard(session_id)
    reply: str = message(state_mod.recent_language(record), "end_reply")
    _save_turn(record, text, "", "summarize")
    store.update_live(session_id, last_user=text, last_reply=reply, last_action="summarize", last_reason="")
    return _result(text, "summarize", reply, "", True)


def _pre_model(session_id: str, text: str) -> Tuple[Optional[Dict[str, Any]], Optional[TurnResult]]:
    """Under lock: finished/end/confirm handling; else a deep snapshot."""
    with store.get_lock(session_id):
        record: Optional[Dict[str, Any]] = store.get_session(session_id)
        if record is None:
            raise KeyError(session_id)
        if record.get("status") == "finished":
            return None, _result(text, "summarize", "", "", True)
        if state_mod.is_explicit_end(text):
            return None, _end_locked(session_id, record, text)
        if session_id in _awaiting_end:
            if state_mod.is_confirm(text):
                return None, _end_locked(session_id, record, text)
            _awaiting_end.discard(session_id)
        return copy.deepcopy(record), None


def _resolve_reply(parsed: Dict[str, Any], seconds_since: Optional[float]) -> Tuple[str, str, str, bool]:
    action: str = str(parsed.get("action", "listen"))
    if action not in ("listen", "follow_up", "pull_back", "continue", "answer", "summarize"):
        action = "listen"
    reply_value: Any = parsed.get("reply", "")
    reply: str = truncate_reply(str(reply_value)) if isinstance(reply_value, str) else ""
    reason_value: Any = parsed.get("reason", "")
    reason: str = str(reason_value)[:20] if isinstance(reason_value, str) else ""
    user_asked: bool = bool(parsed.get("user_asked_ai", False))
    gap: float = _env_seconds("BLACKOUT_MIN_SPEAK_GAP", 20.0)
    if action in ("follow_up", "continue") and not user_asked and seconds_since is not None and seconds_since < gap:
        action = "listen"
    return action, reply, reason, user_asked


def _task_request(parsed: Dict[str, Any]) -> Tuple[str, str, str]:
    task_obj: Any = parsed.get("task", {})
    if isinstance(task_obj, dict) and task_obj.get("kind") in ("search", "draft"):
        instruction: Any = task_obj.get("instruction")
        if isinstance(instruction, str) and instruction.strip():
            under: Any = task_obj.get("under", "")
            return str(task_obj["kind"]), instruction.strip(), under if isinstance(under, str) else ""
    return "none", "", ""


def _wants_direct_end(heard: str) -> bool:
    if "结束" in heard or "停止" in heard:
        return True
    return _END_WORD_RE.search(heard) is not None


def _conflict_reason(question: str) -> str:
    return "Changed fact" if state_mod.speech_language(question) == "en" else "前后不一致"


def _ask_conflict(record: Dict[str, Any], question: str) -> Optional[str]:
    """Record an asked conflict question; return the spoken form or None."""
    asked: List[Any] = record.setdefault("asked_conflicts", [])
    if not isinstance(asked, list):
        record["asked_conflicts"] = []
        asked = record["asked_conflicts"]
    stats: Dict[str, Any] = record.setdefault("stats", {"user_turns": 0, "ai_spoke": 0, "listened": 0, "pull_backs": 0, "nudges": 0})
    try:
        count: int = int(stats.get("conflicts_asked", len(asked)))
    except (TypeError, ValueError):
        count = len(asked)
    if count >= _env_int("BLACKOUT_MAX_CONFLICT_QUESTIONS", 3):
        return None
    cleaned: str = state_mod.clean_text(question)
    for previous in asked:
        if isinstance(previous, str) and state_mod.clean_text(previous) == cleaned:
            return None
    spoken: str = truncate_reply(question)
    asked.append(spoken)
    stats["conflicts_asked"] = count + 1
    return spoken


def _build_reflection(record: Dict[str, Any], language: str) -> str:
    state: Any = record.get("state", {})
    if not isinstance(state, dict):
        return ""
    decisions: List[str] = [str(item.get("text", item)) if isinstance(item, dict) else str(item) for item in state.get("decisions", []) if str(item.get("text", item) if isinstance(item, dict) else item).strip()]
    questions: List[str] = [str(item.get("text", item)) if isinstance(item, dict) else str(item) for item in state.get("open_questions", []) if str(item.get("text", item) if isinstance(item, dict) else item).strip()]
    decision: str = decisions[-1] if decisions else ""
    open_item: str = questions[0] if questions else ""
    if not open_item:
        points: List[str] = state_mod.unexpanded_points(state)
        open_item = points[0] if points else ""
    if decision and open_item:
        return truncate_reply(message(language, "reflect_both", decision=decision, open=open_item))
    if decision:
        return truncate_reply(message(language, "reflect_decision", decision=decision))
    if open_item:
        return truncate_reply(message(language, "reflect_open", open=open_item))
    return ""


def _apply_parsed(session_id: str, text: str, parsed: Dict[str, Any], ts: float, seconds_since: Optional[float], suppress_reply: bool = False, original_text: str = "", reflect_due: bool = False) -> TurnResult:
    parsed_action: str = str(parsed.get("action", "listen"))
    action, reply, reason, _asked = _resolve_reply(parsed, seconds_since)
    kind, instruction, under = _task_request(parsed)
    heard: str = original_text or text
    conflict_value: Any = parsed.get("conflict_question", "")
    conflict_question: str = conflict_value.strip() if isinstance(conflict_value, str) else ""
    with store.get_lock(session_id):
        record: Optional[Dict[str, Any]] = store.get_session(session_id)
        if record is None:
            raise KeyError(session_id)
        if record.get("status") == "finished":
            return _result(text, "summarize", "", "", True)
        _consecutive_failures[session_id] = 0
        language: str = state_mod.recent_language(record)
        record["state"] = state_mod.apply_additions(record.get("state", {}), parsed)
        task_started: bool = False
        cap_refused: bool = False
        if kind != "none":
            block: Optional[str] = tasks_mod.task_block_reason(record, instruction)
            if block == "cap":
                cap_refused = True
                additions: Dict[str, Any] = {"add_questions": [{"text": instruction, "under": under}]}
                record["state"] = state_mod.apply_additions(record.get("state", {}), additions)
            elif block is None:
                started: Any = tasks_mod.start_task(session_id, kind, instruction, under)
                record = store.get_session(session_id) or record
                task_started = started is not None
                if not task_started and tasks_mod.task_block_reason(record, instruction) == "cap":
                    cap_refused = True
                    additions = {"add_questions": [{"text": instruction, "under": under}]}
                    record["state"] = state_mod.apply_additions(record.get("state", {}), additions)
        if action == "summarize" and _wants_direct_end(heard):
            _awaiting_end.discard(session_id)
            end_reply: str = message(state_mod.recent_language(record), "end_reply")
            _save_turn(record, text, "", "summarize")
            store.update_live(session_id, last_user=text, last_reply=end_reply, last_action="summarize", last_reason=reason)
            return _result(heard, "summarize", end_reply, reason, True, task_started)
        if suppress_reply:
            reply = ""
        if action == "summarize" and not suppress_reply:
            reply = message(language, "confirm_end")
            _awaiting_end.add(session_id)
        if action == "listen":
            reply = ""
        if task_started and not reply and not suppress_reply:
            reply = message(language, "task_ack")
            if action == "listen":
                action = "answer"
        if cap_refused and not suppress_reply:
            reply = message(language, "task_limit")
            if action == "listen":
                action = "answer"
        gap: float = _env_seconds("BLACKOUT_MIN_SPEAK_GAP", 20.0)
        gap_passed: bool = seconds_since is None or seconds_since >= gap
        conflict_gap: float = _env_seconds("BLACKOUT_MIN_CONFLICT_GAP", 6.0)
        conflict_gap_passed: bool = seconds_since is None or seconds_since >= conflict_gap
        asked_conflict: bool = False
        pending_before: Optional[Tuple[str, float]] = _pending_conflicts.get(session_id)
        if pending_before is not None and ts - pending_before[1] > _PENDING_TTL:
            _pending_conflicts.pop(session_id, None)
            if conflict_question and state_mod.clean_text(conflict_question) == state_mod.clean_text(pending_before[0]):
                conflict_question = ""
            pending_before = None
        elif pending_before is not None and not suppress_reply and not conflict_question:
            _pending_conflicts.pop(session_id, None)
        if not suppress_reply and conflict_question and parsed_action in ("listen", "follow_up", "continue"):
            if conflict_gap_passed:
                spoken: Optional[str] = _ask_conflict(record, conflict_question)
                if spoken is not None:
                    action = "follow_up"
                    reply = spoken
                    reason = _conflict_reason(conflict_question)
                    asked_conflict = True
                    _pending_conflicts.pop(session_id, None)
            else:
                asked_list: Any = record.get("asked_conflicts", [])
                cleaned: str = state_mod.clean_text(conflict_question)
                already: bool = isinstance(asked_list, list) and any(isinstance(item, str) and state_mod.clean_text(item) == cleaned for item in asked_list)
                stats_now: Any = record.get("stats", {})
                asked_count: int = int(stats_now.get("conflicts_asked", len(asked_list) if isinstance(asked_list, list) else 0)) if isinstance(stats_now, dict) else 0
                if not already and asked_count < _env_int("BLACKOUT_MAX_CONFLICT_QUESTIONS", 3):
                    if pending_before is not None and state_mod.clean_text(pending_before[0]) == cleaned:
                        _pending_conflicts[session_id] = pending_before
                    else:
                        _pending_conflicts[session_id] = (conflict_question, ts)
        reflected: bool = False
        if reflect_due and not suppress_reply and not asked_conflict:
            if parsed_action == "continue" and action == "continue" and reply and not task_started:
                stats_ref: Dict[str, Any] = record.setdefault("stats", {"user_turns": 0, "ai_spoke": 0, "listened": 0, "pull_backs": 0, "nudges": 0})
                stats_ref["reflections"] = int(stats_ref.get("reflections", 0)) + 1
                reflected = True
            elif action == "listen" and not reply and not conflict_question and kind == "none" and not task_started and not cap_refused:
                built: str = _build_reflection(record, language)
                if built:
                    action = "continue"
                    reply = built
                    stats_ref = record.setdefault("stats", {"user_turns": 0, "ai_spoke": 0, "listened": 0, "pull_backs": 0, "nudges": 0})
                    stats_ref["reflections"] = int(stats_ref.get("reflections", 0)) + 1
                    reflected = True
        _ = reflected
        if session_id in _awaiting_recovery:
            _awaiting_recovery.discard(session_id)
            if not reply and not suppress_reply:
                reply = message(language, "ai_back")
        if reply:
            _last_spoke[session_id] = ts
        _save_turn(record, text, reply, action)
        store.update_live(session_id, last_user=text, last_reply=reply, last_action=action, last_reason=reason)
        return _result(text, action, reply, reason, False, task_started)


def _apply_listen(session_id: str, text: str, budget: bool) -> TurnResult:
    with store.get_lock(session_id):
        record: Optional[Dict[str, Any]] = store.get_session(session_id)
        if record is None:
            raise KeyError(session_id)
        if record.get("status") == "finished":
            return _result(text, "summarize", "", "", True)
        _save_turn(record, text, "", "listen")
        return _result(text, "listen", "", "", False, False, budget, "budget" if budget else "")


def _apply_failure(session_id: str, text: str, kind: str, ts: float) -> TurnResult:
    with store.get_lock(session_id):
        record: Optional[Dict[str, Any]] = store.get_session(session_id)
        if record is None:
            raise KeyError(session_id)
        if record.get("status") == "finished":
            return _result(text, "summarize", "", "", True, ai_failed=kind)
        language: str = state_mod.speech_language(text) if text.strip() else state_mod.recent_language(record)
        count: int = _consecutive_failures.get(session_id, 0) + 1
        _consecutive_failures[session_id] = count
        last_note: float = _last_failure_note.get(session_id, float("-inf"))
        speak: bool = False
        if kind in ("key", "credits"):
            speak = ts - last_note >= _FAILURE_NOTE_GAP
        elif kind == "network":
            speak = count >= 2 and ts - last_note >= _FAILURE_NOTE_GAP
        reply: str = ""
        if speak:
            key_name: str = {"key": "key_rejected", "credits": "credits_out", "network": "ai_unreachable"}[kind]
            reply = message(language, key_name)
            _last_failure_note[session_id] = ts
            _awaiting_recovery.add(session_id)
            _last_spoke[session_id] = ts
        _save_turn(record, text, reply, "listen")
        store.update_live(session_id, last_user=text, last_reply=reply, last_action="listen", last_reason="")
        return _result(text, "listen", reply, "", False, False, False, kind)


def _end_without_model(session_id: str, clean: str) -> TurnResult:
    with store.get_lock(session_id):
        record: Optional[Dict[str, Any]] = store.get_session(session_id)
        if record is None:
            raise KeyError(session_id)
        if record.get("status") == "finished":
            return _result(clean, "summarize", "", "", True)
        return _end_locked(session_id, record, clean)


def _model_turn(session_id: str, clean: str, ts: float, suppress_reply: bool = False, end_after: bool = False) -> TurnResult:
    if session_id not in _first_turn:
        _first_turn[session_id] = ts
    snapshot, early = _pre_model(session_id, clean)
    if early is not None:
        return early
    assert snapshot is not None
    reflect_due: bool = False if (suppress_reply or end_after) else _reflect_due(session_id, snapshot, ts)
    last: Optional[float] = _last_spoke.get(session_id)
    seconds_since: Optional[float] = max(0.0, ts - last) if last is not None else None
    parsed, failure_kind = _call_model_with_retry(snapshot, clean, seconds_since)
    if failure_kind == "budget":
        result: TurnResult = _apply_listen(session_id, clean, True)
        if end_after:
            result["end"] = True
            result["reply"] = _end_reply(session_id)
        return result
    if parsed is None:
        kind_name: str = failure_kind or "network"
        failed: TurnResult = _apply_failure(session_id, clean, kind_name, ts)
        if end_after:
            failed["end"] = True
            failed["reply"] = _end_reply(session_id)
        return failed
    result = _apply_parsed(session_id, clean, parsed, ts, seconds_since, suppress_reply=suppress_reply, original_text=clean, reflect_due=reflect_due)
    if end_after and not result.get("end"):
        result["end"] = True
        result["action"] = "summarize"
        result["reply"] = _end_reply(session_id)
    return result


def process_speech(session_id: str, text: str, now: Any = None) -> TurnResult:
    """End phrases first; content before them gets one suppressed turn."""
    ts: float = _now_ts(now)
    clean: str = text.strip()
    content, should_end = state_mod.split_end(clean)
    if should_end:
        if not content:
            return _end_without_model(session_id, clean)
        result: TurnResult = _model_turn(session_id, content, ts, suppress_reply=True, end_after=True)
        result["transcript"] = clean
        result["end"] = True
        if not result.get("budget_exhausted"):
            result["reply"] = _end_reply(session_id)
        return result
    return _model_turn(session_id, clean, ts)


def nudge_text(session: Any, seconds_since_speech: float, nudge_count: int) -> Optional[str]:
    """Deterministic silence nudge."""
    if not isinstance(session, dict):
        return None
    if session.get("paused"):
        return None
    tasks_list: Any = session.get("tasks", [])
    if isinstance(tasks_list, list):
        for task in tasks_list:
            if isinstance(task, dict) and task.get("status") == "running":
                return None
    first: float = _env_seconds("BLACKOUT_NUDGE_SECONDS", 60.0)
    if nudge_count == 0 and seconds_since_speech < first:
        return None
    if nudge_count == 1 and seconds_since_speech < first + 120.0:
        return None
    if nudge_count not in (0, 1):
        return None
    language: str = state_mod.recent_language(session)
    if nudge_count == 1:
        return message(language, "nudge_generic")
    state: Any = session.get("state", session)
    points: List[str] = state_mod.unexpanded_points(state) if isinstance(state, dict) else []
    if points:
        return message(language, "nudge_point", point=_short_point(points[0]))
    return message(language, "nudge_generic")
