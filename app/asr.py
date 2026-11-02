"""Upstream realtime ASR connection: handshake, pacing, silence pump."""
import asyncio
import json
import logging
import time
import urllib.parse
from typing import Any, AsyncIterator, Dict, List, Optional

import websockets

logger: logging.Logger = logging.getLogger(__name__)
BYTES_PER_SECOND: int = 48000
FRAME_BYTES: int = 3840


class AsrStream:
    """One upstream connection. Pacing and byte counts are per connection."""

    def __init__(self, url: str, api_key: str, language: str = "zh") -> None:
        self.url: str = url
        self._api_key: str = api_key
        self.language: str = language if language in ("zh", "en") else "zh"
        self.ws: Any = None
        self.started: float = 0.0
        self.bytes_sent: int = 0
        self.auth_failed: bool = False
        self._send_lock: asyncio.Lock = asyncio.Lock()
        self._pump_task: Optional[asyncio.Task] = None
        self._closed: bool = False

    @property
    def close_code(self) -> Optional[int]:
        code: Any = getattr(self.ws, "close_code", None) if self.ws is not None else None
        return int(code) if code is not None else None

    def _language_bias(self) -> List[str]:
        if self.language == "en":
            return ["English", "Mandarin Chinese"]
        return ["Mandarin Chinese", "English"]

    def _expected_netloc(self) -> str:
        parsed: urllib.parse.ParseResult = urllib.parse.urlparse(self.url)
        netloc: str = parsed.netloc
        if not netloc:
            return ""
        if "@" in netloc:
            netloc = netloc.rsplit("@", 1)[-1]
        return netloc.lower()

    def _matches_expected_endpoint(self, ws: Any) -> bool:
        expected: str = self._expected_netloc()
        if not expected:
            return False
        request: Any = getattr(ws, "request", None)
        if request is None:
            return False
        headers: Any = getattr(request, "headers", None)
        if headers is None:
            return False
        try:
            actual: Any = headers.get("Host", "")
        except Exception:
            return False
        if not isinstance(actual, str):
            return False
        return actual.lower() == expected

    async def connect(self) -> bool:
        """Connect, handshake, wait for sessionId, then start the pump."""
        self.auth_failed = False
        try:
            ws: Any = await websockets.connect(self.url, compression=None)
            if not self._matches_expected_endpoint(ws):
                try:
                    await ws.close()
                except Exception:
                    pass
                return False
            handshake: Dict[str, Any] = {
                "authorization": {"accessToken": f"Bearer {self._api_key}"},
                "audioEncoding": "PCM_24KHZ", "model": "muse-voice-transcribe-1.0",
                "mode": "ENDPOINTING", "partialMode": "CUMULATIVE",
                "languageBias": self._language_bias(), "emitAudioProgress": False,
            }
            await ws.send(json.dumps(handshake))
            ack_raw: Any = await asyncio.wait_for(ws.recv(), timeout=10)
            if isinstance(ack_raw, str) and "Unauthorized" in ack_raw:
                self.auth_failed = True
                try:
                    await ws.close()
                except Exception:
                    pass
                return False
            ack: Any = json.loads(ack_raw) if isinstance(ack_raw, str) else {}
            if isinstance(ack, dict) and "Unauthorized" in json.dumps(ack):
                self.auth_failed = True
                try:
                    await ws.close()
                except Exception:
                    pass
                return False
            if not isinstance(ack, dict) or not ack.get("sessionId"):
                try:
                    await ws.close()
                except Exception:
                    pass
                return False
            self.ws = ws
            self._closed = False
            self.bytes_sent = 0
            self.started = time.monotonic()
            self._pump_task = asyncio.create_task(self._pump())
            return True
        except Exception as exc:
            code: Any = getattr(exc, "code", None)
            if code is None:
                code = getattr(getattr(exc, "rcvd", None), "code", None)
            if code is None:
                code = getattr(getattr(exc, "response", None), "status_code", None)
            if code == 1008:
                self.auth_failed = True
            logger.warning("upstream connect failed: %s", type(exc).__name__)
            return False

    async def _send_raw(self, data: bytes) -> None:
        async with self._send_lock:
            if self.ws is None:
                raise ConnectionError("upstream closed")
            await self.ws.send(data)
            self.bytes_sent += len(data)

    async def send_audio(self, data: bytes) -> bool:
        """Send one browser frame, dropping frames too far ahead of real time."""
        if self.ws is None or self._closed or not data:
            return False
        elapsed: float = max(0.0, time.monotonic() - self.started)
        projected: float = (self.bytes_sent + len(data)) / BYTES_PER_SECOND
        if projected > elapsed + 3.0:
            return False
        try:
            await self._send_raw(data)
            return True
        except Exception:
            return False

    async def _pump(self) -> None:
        """Keep the stream at real time with silence when the browser stalls."""
        try:
            while not self._closed and self.ws is not None:
                await asyncio.sleep(0.1)
                if self._closed or self.ws is None:
                    return
                elapsed: float = max(0.0, time.monotonic() - self.started)
                sent_seconds: float = self.bytes_sent / BYTES_PER_SECOND
                behind: float = elapsed - sent_seconds
                if behind <= 0.4:
                    continue
                need: int = int(((elapsed - 0.2) - sent_seconds) * BYTES_PER_SECOND)
                need -= need % 2
                while need > 0 and not self._closed:
                    chunk: int = min(FRAME_BYTES, need)
                    try:
                        await self._send_raw(b"\x00" * chunk)
                    except Exception:
                        return
                    need -= chunk
        except asyncio.CancelledError:
            raise
        except Exception:
            return

    async def events(self) -> AsyncIterator[Dict[str, Any]]:
        """Yield parsed JSON events, ignoring binary and unknown frames."""
        if self.ws is None:
            return
        try:
            async for raw in self.ws:
                if isinstance(raw, bytes):
                    continue
                try:
                    event: Any = json.loads(raw)
                except Exception:
                    continue
                if isinstance(event, dict):
                    yield event
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            code: Any = getattr(exc, "code", None)
            if code is None:
                code = getattr(getattr(exc, "rcvd", None), "code", None)
            if code is not None and self.ws is not None:
                try:
                    self.ws.close_code = int(code)  # type: ignore[attr-defined]
                except Exception:
                    pass
            return

    async def close(self) -> None:
        """Stop the pump, send endStream, and close the socket."""
        self._closed = True
        if self._pump_task is not None:
            self._pump_task.cancel()
            self._pump_task = None
        if self.ws is not None:
            try:
                async with self._send_lock:
                    await self.ws.send(json.dumps({"type": "endStream"}))
            except Exception:
                pass
            try:
                await self.ws.close()
            except Exception:
                pass
            self.ws = None
