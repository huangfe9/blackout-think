"""Checking a user-supplied Meta key without ever exposing it."""
import hashlib
import json
import logging
import time
import traceback
from typing import Any, Callable, Dict, Set, Tuple

import httpx

from muse_client import load_api_key

logger: logging.Logger = logging.getLogger(__name__)

META_MODELS_URL: str = "https://api.meta.ai/v1/models"
REQUIRED_MODELS: Tuple[str, ...] = ("muse-spark-1.3", "muse-image-1.0", "muse-voice-transcribe-1.0")
_cache: Dict[str, Tuple[str, float]] = {}
_secrets: Set[str] = set()


def remember_secret(value: str) -> None:
    """Remember a secret so log redaction can remove it."""
    if isinstance(value, str) and len(value) >= 16:
        _secrets.add(value)
        forms: Tuple[str, ...] = (json.dumps(value), json.dumps(value, ensure_ascii=False), json.dumps(value, ensure_ascii=True), repr(value))
        for form in forms:
            if form:
                _secrets.add(form)
                if len(form) >= 2:
                    inner: str = form[1:-1]
                    if inner and inner != value:
                        _secrets.add(inner)


def redact(text: str) -> str:
    """Replace every remembered secret in text."""
    result: str = text
    for secret in sorted(list(_secrets), key=len, reverse=True):
        result = result.replace(secret, "[key]")
    return result


def refresh_secrets() -> None:
    """Remember the currently configured key, if any."""
    try:
        remember_secret(load_api_key())
    except Exception:
        pass


def install_log_redaction() -> None:
    """Install a log record factory that redacts remembered secrets."""
    previous: Callable[..., logging.LogRecord] = logging.getLogRecordFactory()
    if getattr(previous, "_blackout_redaction", False):
        refresh_secrets()
        return

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record: logging.LogRecord = previous(*args, **kwargs)
        try:
            if _secrets:
                try:
                    message: str = record.getMessage()
                except Exception:
                    message = ""
                if any(secret in message for secret in _secrets):
                    record.msg = redact(message)
                    record.args = ()
                exc_info: Any = record.exc_info
                if isinstance(exc_info, tuple) and len(exc_info) == 3 and exc_info[0] is not None and exc_info[1] is not None:
                    try:
                        formatted: str = "".join(traceback.format_exception(exc_info[0], exc_info[1], exc_info[2]))
                    except Exception:
                        formatted = ""
                    if formatted and any(secret in formatted for secret in _secrets):
                        redacted: str = redact(formatted)
                        record.exc_text = redacted[:-1] if redacted.endswith("\n") else redacted
        except Exception:
            pass
        return record

    factory._blackout_redaction = True  # type: ignore[attr-defined]
    logging.setLogRecordFactory(factory)
    refresh_secrets()


def check_key(key: str) -> str:
    """Check a key against the fixed Meta models endpoint."""
    try:
        response = httpx.get(META_MODELS_URL, headers={"Authorization": f"Bearer {key}"}, timeout=15, follow_redirects=False)
    except Exception as exc:
        logger.warning("key check failed: %s", type(exc).__name__)
        return "network"
    status: int = int(getattr(response, "status_code", 0) or 0)
    if status in (401, 403):
        logger.warning("key check failed with status %s", status)
        return "invalid_key"
    if status != 200:
        logger.warning("key check failed with status %s", status)
        return "network"
    try:
        payload: Any = response.json()
    except Exception as exc:
        logger.warning("key check failed: %s", type(exc).__name__)
        return "network"
    entries: Any = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        logger.warning("key check failed: %s", "ValueError")
        return "network"
    found: set = set()
    for entry in entries:
        if isinstance(entry, dict) and isinstance(entry.get("id"), str):
            found.add(str(entry.get("id")))
    if all(model in found for model in REQUIRED_MODELS):
        return "ok"
    return "missing_models"


def cached_status() -> str:
    """Cached key status; the cache is keyed only by a digest."""
    try:
        key: str = load_api_key()
    except Exception:
        return "no_key"
    remember_secret(key)
    digest: str = hashlib.sha256(key.encode("utf-8")).hexdigest()
    now: float = time.monotonic()
    cached: Tuple[str, float] | None = _cache.get(digest)
    if cached is not None and cached[1] > now:
        return cached[0]
    result: str = check_key(key)
    ttl: float = 60.0 if result == "ok" else 10.0
    _cache[digest] = (result, now + ttl)
    return result


def clear_cache() -> None:
    """Forget all cached key check results."""
    _cache.clear()
