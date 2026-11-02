"""Persistent session storage and per-session locks."""
import copy
import hmac
import json
import logging
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.state import new_state

logger: logging.Logger = logging.getLogger(__name__)
_ID_RE: re.Pattern = re.compile(r"[0-9a-f]{32}")
_locks: Dict[str, threading.RLock] = {}
_locks_guard: threading.Lock = threading.Lock()
_cache: Dict[str, Dict[str, Any]] = {}
_outbox: Dict[str, List[Dict[str, str]]] = {}
_live: Dict[str, Dict[str, str]] = {}
LIVE_MIC_VALUES: frozenset = frozenset({"listening", "paused", "user_speaking", "ai_speaking", "offline"})
DEFAULT_LIVE: Dict[str, str] = {"mic": "offline", "partial": "", "last_user": "", "last_reply": "", "last_action": "", "last_reason": ""}
DEFAULT_POSTER: Dict[str, Any] = {"brief": None, "language": "zh", "status": "none", "version": 0, "error": "", "attempts": 0}
_REPLACE_DELAYS: List[float] = [0.05, 0.1, 0.15, 0.2, 0.25, 0.25]


def now_iso() -> str:
    """Current UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


def data_dir() -> Path:
    """Override, else %LOCALAPPDATA%\\Blackout on Windows, else ~/.blackout."""
    override: str = os.environ.get("BLACKOUT_DATA_DIR") or ""
    if override:
        return Path(override)
    if os.name == "nt":
        local: str = os.environ.get("LOCALAPPDATA") or ""
        if local:
            return Path(local) / "Blackout"
        return Path.home() / "Blackout"
    return Path.home() / ".blackout"


def sessions_dir() -> Path:
    """Directory containing session files."""
    return data_dir() / "sessions"


def _chmod_quiet(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except Exception:
        pass


def _ensure_private_dir(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception:
        return
    _chmod_quiet(path, 0o700)


def is_valid_id(session_id: Any) -> bool:
    """Only uuid4 hex ids can become paths."""
    return isinstance(session_id, str) and bool(_ID_RE.fullmatch(session_id))


def session_path(session_id: str) -> Optional[Path]:
    """Path for a valid id, otherwise None."""
    if not is_valid_id(session_id):
        return None
    return sessions_dir() / f"{session_id}.json"


def poster_file_path(session_id: str) -> Optional[Path]:
    """Path of the poster PNG for a valid id, otherwise None."""
    if not is_valid_id(session_id):
        return None
    return sessions_dir() / f"{session_id}.poster.png"


def get_lock(session_id: str) -> threading.RLock:
    """Per-session lock."""
    with _locks_guard:
        return _locks.setdefault(session_id, threading.RLock())


def can_access(record: Optional[Dict[str, Any]], owner: str) -> bool:
    """Ownerless records are reachable by exact id only; owned ones need the owner."""
    if not isinstance(record, dict):
        return False
    stored: Any = record.get("owner", "")
    if not stored:
        return True
    if not owner:
        return False
    return hmac.compare_digest(str(stored).encode("utf-8"), str(owner).encode("utf-8"))


def _fix_loaded(record: Dict[str, Any]) -> Dict[str, Any]:
    changed: bool = False
    for task in record.get("tasks", []):
        if isinstance(task, dict) and task.get("status") == "running":
            task["status"] = "failed"
            task.setdefault("conclusion", "任务未完成")
            changed = True
    poster: Any = record.get("poster")
    if isinstance(poster, dict) and poster.get("status") == "drawing":
        poster["status"] = "failed"
        poster["error"] = "上次画图中断了，可以再画一次。"
        changed = True
        result: Any = record.get("result")
        if isinstance(result, dict) and isinstance(result.get("poster"), dict):
            if result["poster"].get("status") == "drawing":
                result["poster"]["status"] = "failed"
                result["poster"]["error"] = "上次画图中断了，可以再画一次。"
    if changed:
        logger.info("stale running work marked failed on load")
    return record


def save_session(record: Dict[str, Any]) -> Dict[str, Any]:
    """Atomically save; retry replace, otherwise keep cache and do not raise."""
    session_id: str = str(record.get("id", ""))
    path: Optional[Path] = session_path(session_id)
    if path is None:
        raise ValueError("invalid session id")
    record["updated_at"] = now_iso()
    _cache[session_id] = record
    tmp: Path = path.parent / f".{session_id}.{uuid.uuid4().hex}.tmp"
    try:
        _ensure_private_dir(path.parent.parent)
        _ensure_private_dir(path.parent)
        tmp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        _chmod_quiet(tmp, 0o600)
    except Exception:
        logger.exception("session write failed; record kept in cache")
        return record
    for attempt in range(6):
        try:
            os.replace(tmp, path)
            _chmod_quiet(path, 0o600)
            return record
        except PermissionError:
            if attempt < 5:
                time.sleep(_REPLACE_DELAYS[attempt])
        except OSError:
            if attempt < 5:
                time.sleep(_REPLACE_DELAYS[attempt])
    logger.error("session replace failed after retries; record kept in cache")
    try:
        tmp.unlink()
    except Exception:
        pass
    return record


def create_session(goal: str, owner: str = "", language: str = "zh") -> Dict[str, Any]:
    """Create, persist, and return a session record."""
    session_id: str = uuid.uuid4().hex
    stamp: str = now_iso()
    clean_language: str = language if language in ("zh", "en") else "zh"
    record: Dict[str, Any] = {
        "id": session_id, "created_at": stamp, "updated_at": stamp, "status": "active",
        "owner": str(owner or ""), "language": clean_language,
        "state": new_state(goal), "history": [], "tasks": [], "sketches": [], "result": None,
        "poster": copy.deepcopy(DEFAULT_POSTER),
        "stats": {"user_turns": 0, "ai_spoke": 0, "listened": 0, "pull_backs": 0, "nudges": 0},
    }
    save_session(record)
    _live[session_id] = dict(DEFAULT_LIVE)
    return record


def load_session(session_id: str) -> Optional[Dict[str, Any]]:
    """Load from disk, converting stale running tasks and posters."""
    path: Optional[Path] = session_path(session_id)
    if path is None or not path.is_file():
        return None
    try:
        record: Any = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("session load failed")
        return None
    if not isinstance(record, dict):
        return None
    record = _fix_loaded(record)
    _cache[session_id] = record
    return record


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    """Return cached or disk session, or None."""
    if not is_valid_id(session_id):
        return None
    if session_id in _cache:
        return _cache[session_id]
    return load_session(session_id)


def get_session_copy(session_id: str) -> Optional[Dict[str, Any]]:
    """Deep copy made under the session lock, safe to serialize."""
    if not is_valid_id(session_id):
        return None
    with get_lock(session_id):
        record: Optional[Dict[str, Any]] = get_session(session_id)
        return copy.deepcopy(record) if record is not None else None


def snapshot_session(session_id: str) -> Optional[Dict[str, Any]]:
    """Alias used by snapshot/model/apply flows."""
    return get_session_copy(session_id)


def delete_session(session_id: str) -> bool:
    """Delete under the session lock so a concurrent save cannot revive it."""
    path: Optional[Path] = session_path(session_id)
    if path is None:
        return False
    with get_lock(session_id):
        existed: bool = session_id in _cache or path.is_file()
        _cache.pop(session_id, None)
        _outbox.pop(session_id, None)
        _live.pop(session_id, None)
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        poster_path: Optional[Path] = poster_file_path(session_id)
        if poster_path is not None:
            try:
                poster_path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                logger.exception("poster file delete failed")
        return existed


def list_sessions(owner: str = "", limit: int = 50) -> List[Dict[str, Any]]:
    """Recent session summaries for one owner, newest first."""
    if not owner:
        return []
    records: List[Dict[str, Any]] = []
    directory: Path = sessions_dir()
    if directory.is_dir():
        for path in directory.glob("*.json"):
            session_id: str = path.stem
            if not is_valid_id(session_id):
                continue
            record: Optional[Dict[str, Any]] = _cache.get(session_id) or load_session(session_id)
            if record is not None:
                records.append(record)
    for record in _cache.values():
        if all(str(r.get("id")) != str(record.get("id")) for r in records):
            records.append(record)
    records = [record for record in records if str(record.get("owner", "") or "") == str(owner)]
    records.sort(key=lambda r: str(r.get("updated_at", "")), reverse=True)
    out: List[Dict[str, Any]] = []
    for record in records[:limit]:
        state: Any = record.get("state", {})
        goal: str = str(state.get("goal", "")) if isinstance(state, dict) else ""
        out.append({
            "id": str(record.get("id", "")), "goal": goal,
            "status": str(record.get("status", "active")),
            "created_at": str(record.get("created_at", "")), "updated_at": str(record.get("updated_at", "")),
        })
    return out


def add_announcement(session_id: str, text: str, kind: str = "announcement") -> None:
    """Queue an in-memory announcement."""
    if not is_valid_id(session_id):
        return
    _outbox.setdefault(session_id, []).append({"text": text, "kind": kind})


def drain_announcements(session_id: str) -> List[Dict[str, str]]:
    """Return and clear queued announcements."""
    if not is_valid_id(session_id):
        return []
    return _outbox.pop(session_id, [])


def get_live(session_id: str) -> Dict[str, str]:
    """In-memory live observer values."""
    if not is_valid_id(session_id):
        return dict(DEFAULT_LIVE)
    return dict(_live.get(session_id, DEFAULT_LIVE))


def update_live(session_id: str, **values: str) -> None:
    """Update live observer values; mic uses the unambiguous enum."""
    if not is_valid_id(session_id):
        return
    live: Dict[str, str] = _live.setdefault(session_id, dict(DEFAULT_LIVE))
    for key, value in values.items():
        if key not in DEFAULT_LIVE:
            continue
        text: str = str(value)
        if key == "mic":
            if text == "speaking":
                text = "user_speaking"
            if text not in LIVE_MIC_VALUES:
                text = "offline"
        live[key] = text


def clear_memory() -> None:
    """Clear in-memory caches, simulating a restart."""
    _cache.clear()
    _outbox.clear()
    _live.clear()
