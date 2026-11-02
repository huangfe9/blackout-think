"""HTTP routes."""
import ipaddress
import logging
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

import budget
from muse_client import delete_saved_key, is_plausible_key, key_source, save_key, transcribe_wav
from app import conductor, keys, poster as poster_mod, sketch as sketch_mod
from app import store, summary
from app.security import origin_allowed, owner_of
from app.state import build_map

logger: logging.Logger = logging.getLogger(__name__)
router: APIRouter = APIRouter()
MAX_WAV_BYTES: int = 32 * 1024 * 1024
_FORWARDED_HEADERS: Tuple[str, ...] = ("x-forwarded-for", "forwarded", "x-real-ip", "via")
_LOOPBACK_HOST_NAMES: frozenset = frozenset({"127.0.0.1", "localhost", "::1"})


def _key_status() -> str: return keys.cached_status()


def err(code: str, message: str, status: int) -> JSONResponse:
    """Unified error envelope."""
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def _setup_response(content: Dict[str, Any], status: int = 200) -> JSONResponse:
    return JSONResponse(status_code=status, content=content, headers={"Cache-Control": "no-store"})


def _setup_error(code: str, message: str, status: int) -> JSONResponse:
    return _setup_response({"error": {"code": code, "message": message}}, status)


def _is_loopback_client(request: Request) -> bool:
    host: str = request.client.host if request.client is not None else ""
    return _is_loopback(host)


def _host_name(host: Optional[str]) -> str:
    value: str = str(host or "").strip().lower()
    if value.startswith("["):
        end: int = value.find("]")
        return value[1:end] if end > 0 else value
    if value.count(":") == 1:
        return value.split(":", 1)[0]
    return value


def _setup_local_and_origin(request: Request) -> Optional[JSONResponse]:
    if any(header in request.headers for header in _FORWARDED_HEADERS):
        return _setup_error("not_local", "请在运行 Blackout 的那台电脑上设置 key。", 403)
    if _host_name(request.headers.get("host")) not in _LOOPBACK_HOST_NAMES:
        return _setup_error("not_local", "请在运行 Blackout 的那台电脑上设置 key。", 403)
    if not _is_loopback_client(request):
        return _setup_error("not_local", "请在运行 Blackout 的那台电脑上设置 key。", 403)
    origin: Optional[str] = request.headers.get("origin")
    if not origin or not origin_allowed(origin, request.headers.get("host")):
        return _setup_error("forbidden_origin", "来源不正确。", 403)
    return None


@router.get("/api/setup")
def api_setup(request: Request) -> JSONResponse:
    """Key presence and whether this client may change it, never the key."""
    source: str = key_source()
    has_key: bool = source != "none"
    loopback: bool = _is_loopback_client(request)
    can_change: bool = loopback and source in ("saved", "none")
    if not loopback:
        return _setup_response({"has_key": has_key, "can_change": False})
    return _setup_response({"has_key": has_key, "source": source, "can_change": can_change})


@router.post("/api/setup/key")
async def api_setup_key(request: Request) -> JSONResponse:
    """Validate and save a key supplied on this computer."""
    denied: Optional[JSONResponse] = _setup_local_and_origin(request)
    if denied is not None:
        return denied
    content_type: str = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        return _setup_error("invalid_input", "输入有误，请检查后重试。", 415)
    if key_source() in ("environment", "env_file"):
        return _setup_error("key_from_env", "正在使用 .env 或环境变量里的 key，要改请直接改那里。", 409)
    payload: Dict[str, Any] = await _json_body(request)
    raw_value: Any = payload.get("key", "")
    value: str = raw_value.strip() if isinstance(raw_value, str) else ""
    if not is_plausible_key(value):
        return _setup_error("invalid_key_format", "这看起来不像 key，请重新复制。", 400)
    keys.remember_secret(value)
    result: str = await run_in_threadpool(keys.check_key, value)
    if result == "invalid_key":
        return _setup_error("invalid_key", "Meta 没有接受这个 key。", 400)
    if result == "missing_models":
        return _setup_error("key_missing_models", "这个 key 不能使用 Blackout 需要的模型。", 400)
    if result != "ok":
        return _setup_error("network", "连不上 Meta，请检查网络后再试。", 502)
    try:
        await run_in_threadpool(save_key, value)
    except Exception:
        logger.warning("key save failed")
        return _setup_error("key_save_failed", "key 没能保存，请再试一次。", 500)
    keys.clear_cache()
    return _setup_response({"ok": True})


@router.delete("/api/setup/key")
async def api_delete_setup_key(request: Request) -> JSONResponse:
    """Delete the saved key from this computer."""
    denied: Optional[JSONResponse] = _setup_local_and_origin(request)
    if denied is not None:
        return denied
    await run_in_threadpool(delete_saved_key)
    keys.clear_cache()
    return _setup_response({"ok": True})


def _not_found() -> JSONResponse:
    return err("not_found", "会话不存在，请重新开始。", 404)


def _session_or_error(session_id: str, owner: str) -> Tuple[Optional[Dict[str, Any]], Optional[JSONResponse]]:
    """One access helper: missing and foreign sessions look identical."""
    record: Optional[Dict[str, Any]] = store.get_session(session_id)
    if record is None or not store.can_access(record, owner):
        return None, _not_found()
    return record, None


def _is_loopback(host: Optional[str]) -> bool:
    value: str = str(host or "").strip().lower()
    if value == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def is_budget_error(exc: Exception) -> bool:
    """Detect HTTP 402."""
    if getattr(exc, "status_code", None) == 402:
        return True
    return getattr(getattr(exc, "response", None), "status_code", None) == 402


def _check_length(request: Request, limit: int) -> Optional[JSONResponse]:
    raw: Optional[str] = request.headers.get("content-length")
    if raw is not None:
        try:
            if int(raw) > limit:
                return err("invalid_input", "内容太大，请缩小后再试。", 400)
        except ValueError:
            return err("invalid_input", "输入有误，请检查后重试。", 400)
    return None


async def _json_body(request: Request) -> Dict[str, Any]:
    try:
        value: Any = await request.json()
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _validate_wav(data: bytes) -> str:
    if len(data) > MAX_WAV_BYTES:
        return "音频太大，请说短一点再试。"
    if len(data) < 12 or data[0:4] != b"RIFF" or data[8:12] != b"WAVE":
        return "音频格式不对，请用WAV上传。"
    return ""


def _language_bias(language: Any) -> List[str]:
    if language == "en":
        return ["English", "Mandarin Chinese"]
    return ["Mandarin Chinese", "English"]


def _record_language(record: Optional[Dict[str, Any]]) -> str:
    if isinstance(record, dict) and record.get("language") in ("zh", "en"):
        return str(record.get("language"))
    return "zh"


async def _turn_response(session_id: str, text: str) -> JSONResponse:
    try:
        result: Dict[str, Any] = await run_in_threadpool(conductor.process_speech, session_id, text)
    except KeyError:
        return _not_found()
    return JSONResponse(content=dict(result))


async def _transcribe(data: bytes, language: str = "zh") -> JSONResponse:
    try:
        transcript: str = await run_in_threadpool(transcribe_wav, data, _language_bias(language))
    except Exception as exc:
        if is_budget_error(exc):
            return err("budget_exhausted", "预算已耗尽，本次无法继续，请稍后再试。", 402)
        logger.exception("transcribe failed")
        return err("transcribe_error", "没听清，请再说一次。", 502)
    if not transcript.strip():
        return err("invalid_input", "没听清，请再说一次。", 400)
    return JSONResponse(content={"transcript": transcript.strip()})


@router.post("/api/sessions")
async def api_create_session(request: Request) -> JSONResponse:
    """Create a session."""
    too_big: Optional[JSONResponse] = _check_length(request, 65536)
    if too_big is not None:
        return too_big
    payload: Dict[str, Any] = await _json_body(request)
    goal: Any = payload.get("goal", "")
    if not isinstance(goal, str) or not goal.strip():
        return err("invalid_input", "请先说一下本次目标。", 400)
    if len(goal.strip()) > 2000:
        return err("invalid_input", "目标太长，请控制在2000字以内。", 400)
    raw_language: Any = payload.get("language", "zh")
    language: str = raw_language if raw_language in ("zh", "en") else "zh"
    status: str = await run_in_threadpool(_key_status)
    if status == "no_key":
        return err("no_key", "请先设置 API key。", 409)
    if status == "invalid_key":
        return err("key_rejected", "Meta 不接受现在的 key，请点右上角换一个。", 401)
    if status == "missing_models":
        return err("key_missing_models", "这个 key 不能使用 Blackout 需要的模型。", 403)
    if status != "ok":
        return err("network", "连不上 Meta，请检查网络后再试。", 503)
    record: Dict[str, Any] = store.create_session(goal.strip(), owner=owner_of(request), language=language)
    return JSONResponse(content={"session_id": record["id"]})


@router.get("/api/sessions")
def api_list_sessions(request: Request) -> JSONResponse:
    """Recent sessions for the requester only."""
    return JSONResponse(content={"sessions": store.list_sessions(owner_of(request), 50)})


@router.get("/api/sessions/{session_id}")
def api_get_session(session_id: str, request: Request) -> JSONResponse:
    """Full record plus a map computed on the fly."""
    _record, denied = _session_or_error(session_id, owner_of(request))
    if denied is not None:
        return denied
    record: Optional[Dict[str, Any]] = store.get_session_copy(session_id)
    if record is None:
        return _not_found()
    record.pop("owner", None)
    record["map"] = build_map(record.get("state", {}), record.get("tasks", []))
    if not isinstance(record.get("poster"), dict):
        record["poster"] = {"status": "none", "version": 0, "error": ""}
    return JSONResponse(content=record)


@router.delete("/api/sessions/{session_id}")
def api_delete_session(session_id: str, request: Request) -> JSONResponse:
    """Delete a session."""
    _record, denied = _session_or_error(session_id, owner_of(request))
    if denied is not None:
        return denied
    if not store.delete_session(session_id):
        return _not_found()
    return JSONResponse(content={"deleted": True})


@router.post("/api/sessions/{session_id}/text-turns")
async def api_text_turn(session_id: str, request: Request) -> JSONResponse:
    """Text turn, with blocking conductor work off the event loop."""
    too_big: Optional[JSONResponse] = _check_length(request, 65536)
    if too_big is not None:
        return too_big
    _record, denied = _session_or_error(session_id, owner_of(request))
    if denied is not None:
        return denied
    payload: Dict[str, Any] = await _json_body(request)
    text: Any = payload.get("text", "")
    if not isinstance(text, str) or not text.strip():
        return err("invalid_input", "内容为空，请再说一次。", 400)
    if len(text) > 2000:
        return err("invalid_input", "内容太长，请控制在2000字以内。", 400)
    return await _turn_response(session_id, text.strip())


@router.post("/api/sessions/{session_id}/turns")
async def api_audio_turn(session_id: str, request: Request, audio: UploadFile = File(...)) -> JSONResponse:
    """Audio turn via file transcription, read with a hard size cap."""
    too_big: Optional[JSONResponse] = _check_length(request, MAX_WAV_BYTES + 1024 * 1024)
    if too_big is not None:
        return too_big
    record, denied = _session_or_error(session_id, owner_of(request))
    if denied is not None:
        return denied
    data: bytes = await audio.read(MAX_WAV_BYTES + 1)
    if len(data) > MAX_WAV_BYTES:
        return err("invalid_input", "音频太大，请说短一点再试。", 400)
    message_text: str = _validate_wav(data)
    if message_text:
        return err("invalid_input", message_text, 400)
    transcribed: JSONResponse = await _transcribe(data, _record_language(record))
    if transcribed.status_code != 200:
        return transcribed
    import json as _json
    text: str = str(_json.loads(bytes(transcribed.body))["transcript"])
    return await _turn_response(session_id, text)


@router.post("/api/transcribe")
async def api_transcribe(request: Request, audio: UploadFile = File(...)) -> JSONResponse:
    """Standalone transcription, read with a hard size cap."""
    too_big: Optional[JSONResponse] = _check_length(request, MAX_WAV_BYTES + 1024 * 1024)
    if too_big is not None:
        return too_big
    data: bytes = await audio.read(MAX_WAV_BYTES + 1)
    if len(data) > MAX_WAV_BYTES:
        return err("invalid_input", "音频太大，请说短一点再试。", 400)
    message_text: str = _validate_wav(data)
    if message_text:
        return err("invalid_input", message_text, 400)
    language: str = request.query_params.get("language", "zh")
    return await _transcribe(data, language if language in ("zh", "en") else "zh")


@router.post("/api/sessions/{session_id}/announcements")
def api_announcements(session_id: str, request: Request) -> JSONResponse:
    """Drain the announcement outbox. State-changing, so POST not GET."""
    _record, denied = _session_or_error(session_id, owner_of(request))
    if denied is not None:
        return denied
    return JSONResponse(content={"announcements": store.drain_announcements(session_id)})


@router.get("/api/sessions/{session_id}/live")
def api_live(session_id: str, request: Request) -> JSONResponse:
    """In-memory live values for the observer."""
    _record, denied = _session_or_error(session_id, owner_of(request))
    if denied is not None:
        return denied
    return JSONResponse(content=store.get_live(session_id))


@router.post("/api/sessions/{session_id}/finish")
def api_finish(session_id: str, request: Request) -> JSONResponse:
    """Finish and return the result (sync def runs in a threadpool)."""
    _record, denied = _session_or_error(session_id, owner_of(request))
    if denied is not None:
        return denied
    result: Dict[str, Any] = summary.finish(session_id)
    if isinstance(result, dict):
        result.pop("owner", None)
    return JSONResponse(content=result)


@router.get("/api/sessions/{session_id}/poster")
def api_get_poster(session_id: str, request: Request) -> Response:
    """Serve the poster PNG, if any."""
    if not store.is_valid_id(session_id):
        return _not_found()
    _record, denied = _session_or_error(session_id, owner_of(request))
    if denied is not None:
        return denied
    path = poster_mod.poster_path(session_id)
    if path is None or not path.is_file():
        return err("not_found", "还没有图片。", 404)
    return Response(content=path.read_bytes(), media_type="image/png", headers={"Cache-Control": "no-store"})


@router.post("/api/sessions/{session_id}/poster")
def api_redraw_poster(session_id: str, request: Request) -> JSONResponse:
    """Draw again from the saved brief."""
    if not store.is_valid_id(session_id):
        return _not_found()
    _checked, denied = _session_or_error(session_id, owner_of(request))
    if denied is not None:
        return denied
    record: Optional[Dict[str, Any]] = store.get_session_copy(session_id)
    if record is None:
        return _not_found()
    record.pop("owner", None)
    poster: Any = record.get("poster")
    poster_dict: Dict[str, Any] = poster if isinstance(poster, dict) else {}
    if str(poster_dict.get("status", "")) == "drawing":
        return err("poster_drawing", "正在画图，请稍等。", 409)
    brief: Any = poster_dict.get("brief")
    if not summary.poster_brief_has_items(brief):
        return err("no_poster_brief", "还没有可画的内容。", 409)
    attempts: Any = poster_dict.get("attempts", 0)
    attempts_count: int = attempts if isinstance(attempts, int) and not isinstance(attempts, bool) else 0
    if attempts_count >= poster_mod.max_poster_attempts():
        return err("poster_limit", "画图次数已达上限。", 429)
    language: str = str(poster_dict.get("language", "zh"))
    started: bool = poster_mod.start_poster(session_id, brief, language)
    if not started:
        return err("poster_limit", "画图次数已达上限。", 429)
    refreshed: Optional[Dict[str, Any]] = store.get_session_copy(session_id)
    new_poster: Any = refreshed.get("poster") if isinstance(refreshed, dict) else {}
    slim: Dict[str, Any] = {"status": "drawing", "version": 0, "error": ""}
    if isinstance(new_poster, dict):
        slim = {
            "status": str(new_poster.get("status", "drawing")),
            "version": new_poster.get("version", 0) if isinstance(new_poster.get("version", 0), int) else 0,
            "error": str(new_poster.get("error", "")),
        }
    return JSONResponse(content={"poster": slim})


@router.post("/api/sessions/{session_id}/sketches")
async def api_sketch(session_id: str, request: Request, image: UploadFile = File(...)) -> JSONResponse:
    """Upload a paper sketch, read with a hard cap, model off the loop."""
    too_big: Optional[JSONResponse] = _check_length(request, sketch_mod.MAX_BYTES + 1024 * 1024)
    if too_big is not None:
        return too_big
    _record, denied = _session_or_error(session_id, owner_of(request))
    if denied is not None:
        return denied
    data: bytes = await image.read(sketch_mod.MAX_BYTES + 1)
    if len(data) > sketch_mod.MAX_BYTES:
        return err("invalid_input", "图片太大，请控制在8MB以内。", 400)
    try:
        result: Dict[str, Any] = await run_in_threadpool(sketch_mod.process_sketch, session_id, data)
    except ValueError:
        return err("invalid_input", "图片格式不对，请换一张再试。", 400)
    except KeyError:
        return _not_found()
    except Exception as exc:
        if is_budget_error(exc):
            return err("budget_exhausted", "预算已耗尽，本次无法继续，请稍后再试。", 402)
        logger.exception("sketch failed")
        return err("model_error", "草稿识别失败，请再试一次。", 502)
    if isinstance(result, dict):
        result.pop("owner", None)
    return JSONResponse(content=result)


@router.get("/api/status")
def api_status(request: Request) -> JSONResponse:
    """Spend status; amounts only for loopback clients."""
    try:
        spent: float = budget.spent_usd()
        ledger_ok: bool = True
    except Exception:
        spent = 0.0
        ledger_ok = False
    can: bool = budget.can_spend() if ledger_ok else False
    content: Dict[str, Any] = {"ledger_ok": ledger_ok, "can_spend": can}
    client_host: str = request.client.host if request.client is not None else ""
    if _is_loopback(client_host):
        content = {"spent_usd": spent, "limit_usd": budget.STOP_AT_USD, "ledger_ok": ledger_ok, "can_spend": can}
    return JSONResponse(content=content)
