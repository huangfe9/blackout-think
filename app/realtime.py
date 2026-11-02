"""Realtime bridge between the browser and the realtime speech API."""
import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

from fastapi import WebSocket, WebSocketDisconnect

import budget
from muse_client import load_api_key
from app import conductor, store
from app.asr import AsrStream
from app.messages import message
from app.security import owner_of
from app.state import clean_text, is_confirm, is_echo, is_explicit_end, recent_language, split_end

logger: logging.Logger = logging.getLogger(__name__)
DEFAULT_ASR_URL: str = "wss://api.meta.ai/v1/asr/realtime"
BYTES_PER_SECOND: int = 48000
MAX_FRAME_BYTES: int = 64 * 1024
TTS_TIMEOUT: float = 20.0
TTS_STUCK_SECONDS: float = 30.0
_bridges: Dict[str, "Bridge"] = {}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _tts_timeout() -> float:
    if "BLACKOUT_TTS_TIMEOUT" in os.environ or "BLACKOUT_TTS_TIMEOUT_SECONDS" in os.environ:
        return _env_float("BLACKOUT_TTS_TIMEOUT", _env_float("BLACKOUT_TTS_TIMEOUT_SECONDS", TTS_TIMEOUT))
    return float(TTS_TIMEOUT)


def _upstream_url() -> str:
    return os.environ.get("BLACKOUT_ASR_URL", DEFAULT_ASR_URL)


def _key_allowed(url: str) -> bool:
    if url == DEFAULT_ASR_URL:
        return True
    host: str = (urlparse(url).hostname or "").lower()
    return host in ("127.0.0.1", "localhost")


def _backoff(attempt: int) -> float:
    if os.environ.get("BLACKOUT_RECONNECT_FAST"):
        return 0.05
    return float(2 ** max(0, attempt - 1))


class Bridge:
    """One browser/upstream pair for one session. All state lives on the loop."""

    def __init__(self, websocket: WebSocket, session_id: str) -> None:
        self.ws: WebSocket = websocket
        self.session_id: str = session_id
        self.language: str = "zh"
        self.stream: Optional[AsrStream] = None
        self.upstream: Optional[AsrStream] = None
        self.connected_at: float = 0.0
        self.forwarded_bytes: int = 0
        self._base_bytes: int = 0
        self.recorded_bytes: int = 0
        self.user_speaking: bool = False
        self.speaking_since: float = 0.0
        self.speaking_turns: Set[Any] = set()
        self.turn_started_playback: Dict[Any, bool] = {}
        self.suspect_turns: Dict[Any, Dict[str, bool]] = {}
        self.latest_turn_id: Any = None
        self.last_speech_end: float = time.monotonic()
        self.paused: bool = False
        self.pause_started: Optional[float] = None
        self.tts_playing: bool = False
        self.tts_started_at: float = 0.0
        self.tts_event: asyncio.Event = asyncio.Event()
        self.tts_event.set()
        self.last_spoken: str = ""
        self.tts_finished_at: float = 0.0
        self.speech_start_counter: int = 0
        self.queue: asyncio.Queue = asyncio.Queue()
        self.say_queue: asyncio.Queue = asyncio.Queue()
        self.tasks: List[asyncio.Task] = []
        self.ended: bool = False
        self.end_sent: bool = False
        self.fallback_sent: bool = False
        self.replaced: bool = False
        self.nudge_count: int = 0
        self.oversize_frames: int = 0
        self.browser_open: bool = True
        self._auth_failed: bool = False
        self._audio_flowed: bool = False
        self._send_lock: asyncio.Lock = asyncio.Lock()

    async def _live(self, **values: str) -> None:
        await asyncio.to_thread(store.update_live, self.session_id, **values)

    async def _send(self, payload: Dict[str, Any]) -> bool:
        if self.replaced or not self.browser_open:
            return False
        try:
            async with self._send_lock:
                await self.ws.send_json(payload)
            return True
        except Exception:
            self.browser_open = False
            return False

    async def _close_browser(self) -> None:
        self.browser_open = False
        try:
            await self.ws.close(code=1000)
        except Exception:
            pass

    async def _send_end(self, reason: str) -> None:
        if self.end_sent:
            return
        self.end_sent = True
        self.ended = True
        await self._send({"type": "end", "reason": reason})
        await self._close_browser()

    def _fixed_language(self) -> str:
        try:
            record: Optional[Dict[str, Any]] = store.get_session_copy(self.session_id)
        except Exception:
            record = None
        if isinstance(record, dict):
            return recent_language(record)
        return self.language if self.language in ("zh", "en") else "zh"

    async def _send_fallback(self, text: Optional[str] = None) -> None:
        if self.fallback_sent or self.end_sent:
            return
        self.fallback_sent = True
        self.ended = True
        fallback_text: str = text if isinstance(text, str) and text else message(self._fixed_language(), "fallback")
        await self._send({"type": "fallback", "message": fallback_text})
        await self._close_browser()

    async def _send_auth_fallback(self) -> None:
        await self._send_fallback(message(self._fixed_language(), "asr_key_rejected"))

    async def force_close(self, code: int = 4000) -> None:
        self.replaced = True
        self.browser_open = False
        try:
            await self.ws.close(code=code)
        except Exception:
            pass
        for task in list(self.tasks):
            task.cancel()

    def _sync_bytes(self) -> None:
        if self.stream is not None:
            self.forwarded_bytes = self._base_bytes + self.stream.bytes_sent
            if self.stream.bytes_sent > 0:
                self._audio_flowed = True

    def _fold_stream(self) -> None:
        if self.stream is not None and getattr(self.stream, "auth_failed", False):
            self._auth_failed = True
        self._sync_bytes()
        self._base_bytes = self.forwarded_bytes
        self.stream = None
        self.upstream = None

    def _clear_stuck_tts(self) -> None:
        if self.tts_playing and self.tts_started_at and time.monotonic() - self.tts_started_at > TTS_STUCK_SECONDS:
            self.tts_playing = False
            self.tts_finished_at = time.monotonic()
            self.tts_event.set()

    def _clear_stuck_speaking(self) -> None:
        if self.user_speaking and self.speaking_since and time.monotonic() - self.speaking_since > 30:
            self.user_speaking = False
            self.speaking_turns.clear()

    def _is_suspect_start(self, now: float) -> bool:
        if self.tts_playing:
            return True
        return bool(self.tts_finished_at) and (now - self.tts_finished_at) <= 1.0

    async def _confirm_suspect(self, turn_id: Any, send_stop: bool) -> bool:
        """Confirm a suspect turn as real user speech. Returns True if newly confirmed."""
        info: Optional[Dict[str, bool]] = self.suspect_turns.get(turn_id)
        if info is None or info.get("confirmed"):
            return False
        info["confirmed"] = True
        self.speaking_turns.add(turn_id)
        self.user_speaking = True
        self.speaking_since = time.monotonic()
        self.speech_start_counter += 1
        self.nudge_count = 0
        if send_stop and self.tts_playing and not info.get("stop_sent"):
            info["stop_sent"] = True
            await self._send({"type": "stop_speech"})
        return True

    async def run(self) -> None:
        old: Optional[Bridge] = _bridges.get(self.session_id)
        _bridges[self.session_id] = self
        if old is not None and old is not self:
            await old.force_close(4000)
        try:
            await self.ws.accept()
        except Exception:
            return
        try:
            record: Optional[Dict[str, Any]] = await asyncio.to_thread(store.get_session, self.session_id)
            if record is None:
                await self.ws.close(code=1008)
                return
            stored_language: Any = record.get("language", "zh")
            self.language = stored_language if stored_language in ("zh", "en") else "zh"
            if record.get("status") == "finished":
                await self._send_end("phrase")
                return
            can: bool = await asyncio.to_thread(budget.can_spend)
            if not can:
                await self._send_end("budget")
                return
            if not await self._connect_upstream():
                if not self.fallback_sent:
                    if self._auth_failed:
                        await self._send_auth_fallback()
                    else:
                        await self._send_fallback()
                return
            await self._send({"type": "ready"})
            await self._live(mic="listening")
            self.tasks = [
                asyncio.create_task(self._browser_loop()),
                asyncio.create_task(self._worker_loop()),
                asyncio.create_task(self._delivery_loop()),
                asyncio.create_task(self._announcement_loop()),
                asyncio.create_task(self._nudge_loop()),
                asyncio.create_task(self._record_loop()),
                asyncio.create_task(self._upstream_supervisor()),
            ]
            done, pending = await asyncio.wait(self.tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
        except WebSocketDisconnect:
            pass
        except Exception:
            logger.exception("realtime bridge failed")
        finally:
            await self._cleanup()

    async def _connect_upstream(self) -> bool:
        url: str = _upstream_url()
        if not _key_allowed(url):
            logger.error("refusing to send key to untrusted ASR host")
            return False
        try:
            key: str = load_api_key()
        except Exception:
            return False
        stream: AsrStream = AsrStream(url, key, self.language)
        if not await stream.connect():
            if getattr(stream, "auth_failed", False):
                self._auth_failed = True
            return False
        self._fold_stream()
        self.stream = stream
        self.upstream = stream
        self.connected_at = time.monotonic()
        return True

    async def _upstream_supervisor(self) -> None:
        attempts: int = 0
        while not self.ended and self.browser_open and not self.replaced:
            if self.stream is None:
                await asyncio.sleep(0.05)
                continue
            audio_flowed_before: bool = self._audio_flowed or (self.stream is not None and self.stream.bytes_sent > 0)
            auth_before: bool = bool(getattr(self.stream, "auth_failed", False)) if self.stream is not None else self._auth_failed
            code: Optional[int] = await self._upstream_loop(self.stream)
            uptime: float = time.monotonic() - self.connected_at if self.connected_at else 0.0
            self._fold_stream()
            auth_failed: bool = self._auth_failed or auth_before
            if self.ended or self.replaced or not self.browser_open:
                return
            if code == 1008:
                if auth_failed and not audio_flowed_before:
                    await self._send_auth_fallback()
                else:
                    await self._send_fallback()
                return
            if uptime >= 30:
                attempts = 0
            while not self.ended and self.browser_open and not self.replaced:
                attempts += 1
                if attempts > 3:
                    if self._auth_failed and not self._audio_flowed:
                        await self._send_auth_fallback()
                    else:
                        await self._send_fallback()
                    return
                await self._send({"type": "reconnecting"})
                await self._live(mic="offline")
                await asyncio.sleep(_backoff(attempts))
                if self.ended or self.replaced or not self.browser_open:
                    return
                if await self._connect_upstream():
                    await self._live(mic="listening")
                    break
                if self._auth_failed and not self._audio_flowed:
                    await self._send_auth_fallback()
                    return
        return

    async def _upstream_loop(self, stream: AsrStream) -> Optional[int]:
        async for event in stream.events():
            await self._handle_upstream(event)
            if self.ended:
                return 1000
        code: Optional[int] = stream.close_code
        return int(code) if code is not None else 1011

    async def _handle_upstream(self, event: Dict[str, Any]) -> None:
        kind: Any = event.get("type")
        turn_id: Any = event.get("turnId")
        now: float = time.monotonic()
        if kind == "speechStart":
            self.latest_turn_id = turn_id
            if self._is_suspect_start(now):
                if turn_id is not None:
                    self.suspect_turns[turn_id] = {"confirmed": False, "stop_sent": False}
                    self.turn_started_playback[turn_id] = True
                return
            if turn_id is not None:
                self.speaking_turns.add(turn_id)
                self.turn_started_playback[turn_id] = False
            self.user_speaking = True
            self.speaking_since = now
            self.speech_start_counter += 1
            self.nudge_count = 0
            await self._live(mic="user_speaking", partial="")
        elif kind == "transcript":
            text: Any = event.get("transcript", "")
            if event.get("final") is True and (not isinstance(text, str) or not text.strip()):
                return
            if self.paused:
                return
            if event.get("final") is not True and isinstance(text, str):
                turn_key: Any = self.latest_turn_id
                if turn_key is not None and turn_key in self.suspect_turns and not self.suspect_turns[turn_key].get("confirmed"):
                    if len(text.strip()) >= 4 and not is_echo(text, self.last_spoken):
                        await self._confirm_suspect(turn_key, send_stop=True)
                        await self._live(mic="user_speaking", partial=text)
                    return
                await self._live(partial=text)
        elif kind == "speechEnd":
            if turn_id is not None and turn_id in self.suspect_turns and not self.suspect_turns[turn_id].get("confirmed"):
                return
            if turn_id is not None:
                self.speaking_turns.discard(turn_id)
            if not self.speaking_turns:
                self.user_speaking = False
            self.last_speech_end = now
            self.nudge_count = 0
            await self._live(mic="listening")
        elif kind == "speechComplete":
            text = event.get("transcript", "")
            if not isinstance(text, str) or not text.strip():
                if turn_id is not None:
                    self.suspect_turns.pop(turn_id, None)
                    self.speaking_turns.discard(turn_id)
                    if not self.speaking_turns:
                        self.user_speaking = False
                return
            if self.paused:
                if turn_id is not None:
                    self.suspect_turns.pop(turn_id, None)
                return
            if turn_id is not None and turn_id in self.suspect_turns:
                info: Dict[str, bool] = self.suspect_turns.pop(turn_id)
                if is_echo(text, self.last_spoken):
                    self.speaking_turns.discard(turn_id)
                    if not self.speaking_turns:
                        self.user_speaking = False
                    self.turn_started_playback.pop(turn_id, None)
                    return
                if not info.get("confirmed"):
                    self.suspect_turns[turn_id] = info
                    await self._confirm_suspect(turn_id, send_stop=True)
                    self.suspect_turns.pop(turn_id, None)
                self.speaking_turns.discard(turn_id)
                if not self.speaking_turns:
                    self.user_speaking = False
                self.turn_started_playback.pop(turn_id, None)
                self.last_speech_end = now
                self.nudge_count = 0
                await self._live(partial="", last_user=text)
                await self.queue.put(text)
                return
            if turn_id is not None:
                self.speaking_turns.discard(turn_id)
                self.turn_started_playback.pop(turn_id, None)
                if not self.speaking_turns:
                    self.user_speaking = False
            self.last_speech_end = now
            self.nudge_count = 0
            await self._live(partial="", last_user=text)
            await self.queue.put(text)
        elif kind == "error":
            logger.warning("upstream speech error")

    async def _browser_loop(self) -> None:
        try:
            while not self.ended and not self.replaced:
                incoming: Dict[str, Any] = await self.ws.receive()
                if incoming.get("type") == "websocket.disconnect":
                    self.browser_open = False
                    return
                data: Any = incoming.get("bytes")
                if data is not None:
                    await self._forward_audio(bytes(data))
                    continue
                text: Any = incoming.get("text")
                if isinstance(text, str):
                    await self._handle_browser_text(text)
        except WebSocketDisconnect:
            self.browser_open = False
        except asyncio.CancelledError:
            raise
        except Exception:
            self.browser_open = False

    async def _handle_browser_text(self, text: str) -> None:
        try:
            event: Any = json.loads(text)
        except Exception:
            return
        if not isinstance(event, dict):
            return
        kind: Any = event.get("type")
        if kind == "tts_started":
            self.tts_playing = True
            self.tts_started_at = time.monotonic()
            self.tts_event.clear()
            spoken: Any = event.get("text")
            if isinstance(spoken, str) and spoken:
                self.last_spoken = spoken[:500]
            await self._live(mic="ai_speaking")
        elif kind == "tts_finished":
            self.tts_playing = False
            self.tts_finished_at = time.monotonic()
            self.tts_event.set()
            await self._live(mic="paused" if self.paused else "listening")
        elif kind == "pause":
            if not self.paused:
                self.paused = True
                self.pause_started = time.monotonic()
            await self._live(mic="paused")
        elif kind == "resume":
            if self.paused and self.pause_started is not None:
                self.last_speech_end += time.monotonic() - self.pause_started
            self.paused = False
            self.pause_started = None
            await self._live(mic="listening")

    async def _forward_audio(self, data: bytes) -> None:
        if self.ended:
            return
        if len(data) > MAX_FRAME_BYTES:
            self.oversize_frames += 1
            if self.oversize_frames >= 3:
                try:
                    await self.ws.close(code=1009)
                except Exception:
                    pass
                self.browser_open = False
                self.ended = True
            return
        self.oversize_frames = 0
        if self.stream is None:
            return
        await self.stream.send_audio(data)
        self._sync_bytes()

    async def _worker_loop(self) -> None:
        while not self.ended and not self.replaced:
            first: str = await self.queue.get()
            parts: List[str] = [first]
            deadline: float = time.monotonic() + _env_float("BLACKOUT_COALESCE_SECONDS", 8.0)
            while time.monotonic() < deadline:
                if not self.queue.empty():
                    parts.append(str(self.queue.get_nowait()))
                    continue
                if not self.user_speaking and self.queue.empty():
                    try:
                        nxt: Any = await asyncio.wait_for(self.queue.get(), timeout=0.05)
                        parts.append(str(nxt))
                    except asyncio.TimeoutError:
                        break
                else:
                    await asyncio.sleep(0.02)
            while not self.queue.empty():
                parts.append(str(self.queue.get_nowait()))
            rest: List[str] = []
            special: List[str] = []
            awaiting: Set[Any] = getattr(conductor, "_awaiting_end", set())
            for part in parts:
                _content, ends = split_end(part)
                if ends or (is_confirm(part) and self.session_id in awaiting):
                    special.append(part)
                else:
                    rest.append(part)
            if rest:
                await self._process("\n".join(rest))
            for part in special:
                if self.ended or self.end_sent:
                    break
                await self._process(part)

    async def _process(self, text: str) -> None:
        starts_before: int = self.speech_start_counter
        try:
            result: Any = await asyncio.to_thread(conductor.process_speech, self.session_id, text, time.time())
        except KeyError:
            return
        except Exception:
            logger.exception("conductor failed in bridge")
            return
        if not isinstance(result, dict):
            return
        action: str = str(result.get("action", "listen"))
        reply: str = str(result.get("reply", ""))
        reason: str = str(result.get("reason", ""))
        await self._live(last_user=text, last_reply=reply, last_action=action, last_reason=reason, mic="listening")
        if result.get("budget_exhausted"):
            await self._send_end("budget")
            return
        if result.get("end"):
            await self._send_end("confirmed" if is_confirm(text) else "phrase")
            return
        if action == "listen" or not reply:
            if action == "listen":
                await self._send({"type": "tick"})
            return
        if self.speech_start_counter != starts_before:
            return
        await self.say_queue.put((reply, "reply", starts_before))

    async def _delivery_loop(self) -> None:
        while not self.ended and not self.replaced:
            text, kind, queued_counter = await self.say_queue.get()
            if kind == "reply" and queued_counter != self.speech_start_counter:
                continue
            while (self.user_speaking or self.tts_playing or self.paused) and not self.ended:
                self._clear_stuck_speaking()
                self._clear_stuck_tts()
                if not self.tts_playing and not self.user_speaking and not self.paused:
                    break
                await asyncio.sleep(0.02)
            if self.ended:
                return
            if kind == "reply" and queued_counter != self.speech_start_counter:
                continue
            self.last_spoken = str(text)
            self.tts_playing = True
            self.tts_started_at = time.monotonic()
            self.tts_event.clear()
            await self._live(mic="ai_speaking")
            if not await self._send({"type": "say", "text": str(text), "kind": str(kind)}):
                self.tts_playing = False
                return
            try:
                await asyncio.wait_for(self.tts_event.wait(), timeout=_tts_timeout())
            except asyncio.TimeoutError:
                self.tts_playing = False
                self.tts_finished_at = time.monotonic()
                self.tts_event.set()
            if kind in ("announcement", "nudge"):
                try:
                    await asyncio.to_thread(conductor.note_spoken, self.session_id, str(text), str(kind), time.time())
                except Exception:
                    logger.exception("note_spoken failed")

    async def _announcement_loop(self) -> None:
        while not self.ended and not self.replaced:
            items: List[Dict[str, str]] = await asyncio.to_thread(store.drain_announcements, self.session_id)
            for item in items:
                if isinstance(item, dict) and item.get("text"):
                    await self.say_queue.put((str(item["text"]), str(item.get("kind", "announcement")), self.speech_start_counter))
            await asyncio.sleep(_env_float("BLACKOUT_ANNOUNCE_POLL", 0.2))

    async def _nudge_loop(self) -> None:
        interval: float = _env_float("BLACKOUT_NUDGE_CHECK_INTERVAL", 1.0)
        while not self.ended and not self.replaced:
            await asyncio.sleep(min(1.0, max(0.02, interval)))
            self._clear_stuck_speaking()
            self._clear_stuck_tts()
            if self.paused or self.user_speaking or self.tts_playing:
                continue
            seconds: float = max(0.0, time.monotonic() - self.last_speech_end)
            record: Optional[Dict[str, Any]] = await asyncio.to_thread(store.get_session_copy, self.session_id)
            if record is None:
                continue
            probe: Dict[str, Any] = dict(record)
            probe["paused"] = self.paused
            try:
                text: Optional[str] = conductor.nudge_text(probe, seconds, self.nudge_count)
            except Exception:
                text = None
            if text:
                self.nudge_count += 1
                await self.say_queue.put((text, "nudge", self.speech_start_counter))

    async def _record_once(self) -> bool:
        self._sync_bytes()
        delta_bytes: int = self.forwarded_bytes - self.recorded_bytes
        if delta_bytes > 0:
            seconds: float = delta_bytes / BYTES_PER_SECOND
            await asyncio.to_thread(budget.record_audio_seconds, seconds)
            self.recorded_bytes = self.forwarded_bytes
        return await asyncio.to_thread(budget.can_spend)

    async def _record_loop(self) -> None:
        interval: float = _env_float("BLACKOUT_AUDIO_RECORD_INTERVAL", 30.0)
        while not self.ended and not self.replaced:
            await asyncio.sleep(min(30.0, max(0.05, interval)))
            if not await self._record_once():
                await self._send_end("budget")
                return

    async def _cleanup(self) -> None:
        current: Optional[Bridge] = _bridges.get(self.session_id)
        is_current: bool = current is self
        for task in list(self.tasks):
            task.cancel()
        stream: Optional[AsrStream] = self.stream
        self._fold_stream()
        if stream is not None:
            await stream.close()
        try:
            await self._record_once()
        except Exception:
            logger.exception("audio accounting failed")
        if is_current:
            _bridges.pop(self.session_id, None)
            try:
                await asyncio.to_thread(store.update_live, self.session_id, mic="offline", partial="")
            except Exception:
                pass


async def handle_websocket(websocket: WebSocket, session_id: str) -> None:
    record: Optional[Dict[str, Any]] = await asyncio.to_thread(store.get_session, session_id)
    if record is None or not store.can_access(record, owner_of(websocket)):
        try:
            await websocket.close(code=1008)
        except Exception:
            pass
        return
    bridge: Bridge = Bridge(websocket, session_id)
    await bridge.run()
