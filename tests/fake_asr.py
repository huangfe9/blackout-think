"""A local fake realtime speech server for tests. No real network or keys."""
import asyncio
import json
from typing import Any, Dict, List, Optional

import websockets


class FakeASRServer:
    """Scripted fake for wss://api.meta.ai/v1/asr/realtime."""
    def __init__(self, events: Optional[List[Dict[str, Any]]] = None, close_code: Optional[int] = None, fail_handshake: bool = False, event_delay: float = 0.05, fail_handshake_from: Optional[int] = None, close_after_handshake_code: Optional[int] = None) -> None:
        self.events: List[Dict[str, Any]] = list(events or [])
        self.close_code: Optional[int] = close_code
        self.fail_handshake: bool = fail_handshake
        self.event_delay: float = event_delay
        # 1-based connection number from which handshakes should be refused.
        self.fail_handshake_from: Optional[int] = fail_handshake_from
        # If set, close every accepted connection with this code right after the ack.
        self.close_after_handshake_code: Optional[int] = close_after_handshake_code
        self.handshake: Optional[Dict[str, Any]] = None
        self.handshakes: List[Optional[Dict[str, Any]]] = []
        self.received_bytes: int = 0
        self.received_frames: int = 0
        # Per-connection received byte counts, in connection order.
        self.received_bytes_by_connection: List[int] = []
        self.received_frames_by_connection: List[int] = []
        self.end_stream_received: bool = False
        self.connection_count: int = 0
        self.closed_codes: List[int] = []
        self._server: Any = None
        self._connections: List[Any] = []
        self.port: int = 0
        self.url: str = ""

    async def start(self) -> "FakeASRServer":
        self._server = await websockets.serve(self._handle, "127.0.0.1", 0)
        sockets: Any = self._server.sockets
        self.port = int(sockets[0].getsockname()[1])
        self.url = f"ws://127.0.0.1:{self.port}/asr/realtime"
        return self

    async def stop(self) -> None:
        for conn in list(self._connections):
            try:
                await conn.close()
            except Exception:
                pass
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def __aenter__(self) -> "FakeASRServer":
        return await self.start()

    async def __aexit__(self, *args: Any) -> None:
        await self.stop()

    def _should_fail_handshake(self, connection_number: int) -> bool:
        if self.fail_handshake:
            return True
        return self.fail_handshake_from is not None and connection_number >= self.fail_handshake_from

    async def _handle(self, connection: Any) -> None:
        self.connection_count += 1
        connection_number: int = self.connection_count
        index: int = connection_number - 1
        while len(self.received_bytes_by_connection) <= index:
            self.received_bytes_by_connection.append(0)
            self.received_frames_by_connection.append(0)
        self._connections.append(connection)
        try:
            raw: Any = await asyncio.wait_for(connection.recv(), timeout=5)
            self.handshake = json.loads(raw) if isinstance(raw, str) else None
            self.handshakes.append(self.handshake)
            if self._should_fail_handshake(connection_number):
                await connection.send(json.dumps({"error": "no session"}))
                await connection.close(code=1008)
                return
            auth: Any = (self.handshake or {}).get("authorization", {})
            if not isinstance(auth, dict) or not str(auth.get("accessToken", "")).startswith("Bearer "):
                await connection.close(code=1008)
                return
            await connection.send(json.dumps({"sessionId": "fake-session"}))
            if self.close_after_handshake_code is not None:
                await asyncio.sleep(self.event_delay)
                await connection.close(code=self.close_after_handshake_code)
                return
            sender: asyncio.Task = asyncio.create_task(self._play(connection))
            try:
                async for frame in connection:
                    if isinstance(frame, bytes):
                        self.received_bytes += len(frame)
                        self.received_frames += 1
                        self.received_bytes_by_connection[index] += len(frame)
                        self.received_frames_by_connection[index] += 1
                    elif isinstance(frame, str):
                        try:
                            payload: Any = json.loads(frame)
                        except Exception:
                            continue
                        if isinstance(payload, dict) and payload.get("type") == "endStream":
                            self.end_stream_received = True
                            await connection.send(json.dumps({"type": "transcript", "transcript": "", "final": True}))
                            await connection.close(code=1000)
            finally:
                sender.cancel()
        except Exception:
            pass
        finally:
            code: Any = getattr(connection, "close_code", None)
            if code is not None:
                self.closed_codes.append(int(code))
            if connection in self._connections:
                self._connections.remove(connection)

    async def _play(self, connection: Any) -> None:
        await asyncio.sleep(self.event_delay)
        for event in self.events:
            await connection.send(json.dumps(event))
            await asyncio.sleep(0.01)
        if self.close_code is not None:
            await asyncio.sleep(self.event_delay)
            await connection.close(code=self.close_code)

    async def send_event(self, event: Dict[str, Any]) -> None:
        for conn in list(self._connections):
            try:
                await conn.send(json.dumps(event))
            except Exception:
                pass

    async def close_current(self, code: int = 1011) -> None:
        """Close all currently-open upstream connections with `code`."""
        for conn in list(self._connections):
            try:
                await conn.close(code=code)
            except Exception:
                pass


# Convenient aliases for tests written against either name.
FakeSpeechServer = FakeASRServer
FakeASR = FakeASRServer
