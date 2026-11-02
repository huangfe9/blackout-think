"""Blackout FastAPI application."""
import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, WebSocket
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import keys, realtime
from app.routes import router
from app.security import SecurityMiddleware

logger: logging.Logger = logging.getLogger(__name__)
logging.getLogger("websockets").setLevel(logging.INFO)
keys.install_log_redaction()
app: FastAPI = FastAPI(title="Blackout")
app.add_middleware(SecurityMiddleware)
STATIC_DIR: Path = Path(__file__).resolve().parent / "static"
INDEX_PATH: Path = STATIC_DIR / "index.html"
OBSERVER_PATH: Path = STATIC_DIR / "observer.html"
SETUP_PATH: Path = STATIC_DIR / "setup.html"


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Validation errors use the envelope with 400, not 422."""
    return JSONResponse(status_code=400, content={"error": {"code": "invalid_input", "message": "输入有误，请检查后重试。"}})


@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    """Unexpected errors use the envelope."""
    logger.exception("unhandled error")
    return JSONResponse(status_code=500, content={"error": {"code": "internal_error", "message": "出了一点问题，请再试一次。"}})


@app.get("/")
def serve_index() -> FileResponse:
    """Serve the frontend."""
    return FileResponse(str(INDEX_PATH), media_type="text/html")


@app.get("/setup")
def serve_setup() -> FileResponse:
    """Serve the key setup page."""
    return FileResponse(str(SETUP_PATH), media_type="text/html")


@app.get("/observer")
def serve_observer() -> Any:
    """Serve the observer page when present."""
    if OBSERVER_PATH.is_file():
        return FileResponse(str(OBSERVER_PATH), media_type="text/html")
    return JSONResponse(status_code=404, content={"error": {"code": "not_found", "message": "页面不存在。"}})


@app.websocket("/ws/sessions/{session_id}")
async def ws_session(websocket: WebSocket, session_id: str) -> None:
    """Hands-free realtime bridge."""
    await realtime.handle_websocket(websocket, session_id)


app.include_router(router)
if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
