"""ASGI security layer: host, origin, token, rate limit, headers, body size."""
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from collections import defaultdict, deque
from typing import Any, Deque, Dict, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse

ALLOWED_DEFAULT_HOSTS: frozenset = frozenset({"127.0.0.1", "localhost"})
RATE_LIMIT_ENV: Tuple[str, ...] = ("BLACKOUT_RATE_LIMIT", "BLACKOUT_RATE_LIMIT_PER_MINUTE")
_window_state: Dict[str, Deque[float]] = defaultdict(deque)
_window_config: Dict[str, Tuple[int, float]] = {}
COOKIE_NAME: str = "blackout_access_token"
OWNER_COOKIE: str = "blackout_owner"
_OWNER_RE: re.Pattern = re.compile(r"^[A-Za-z0-9_-]{20,64}$")
_HOST_RE: re.Pattern = re.compile(r"^[A-Za-z0-9.:\[\]-]+$")
_CSP_TEMPLATE: str = "default-src 'self'; script-src 'self' blob:; worker-src 'self' blob:; connect-src {connect}; img-src 'self' blob: data:; style-src 'self'; media-src 'self' blob:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
CSP: str = _CSP_TEMPLATE.format(connect="'self'")
SECURITY_HEADERS: Tuple[Tuple[str, str], ...] = (("x-content-type-options", "nosniff"), ("referrer-policy", "no-referrer"), ("x-frame-options", "DENY"))


def csp_for(host: Optional[str]) -> str:
    """Content-Security-Policy narrowed to the validated host."""
    value: str = str(host or "").strip()
    if value and _HOST_RE.match(value):
        return _CSP_TEMPLATE.format(connect=f"'self' ws://{value} wss://{value}")
    return CSP


def _host_name(host: str) -> str:
    value: str = host.strip().lower()
    if value.startswith("["):
        end: int = value.find("]")
        return value[1:end] if end > 0 else value
    if value.count(":") == 1:
        return value.split(":", 1)[0]
    return value


def allowed_hosts() -> set:
    hosts: set = set(ALLOWED_DEFAULT_HOSTS)
    raw: str = os.environ.get("BLACKOUT_ALLOWED_HOSTS", "")
    for item in raw.replace(";", ",").split(","):
        if item.strip():
            hosts.add(_host_name(item.strip()))
    return hosts


def is_allowed_host(host: Optional[str]) -> bool:
    if host and _host_name(host) == "testserver" and "testserver" in allowed_hosts():
        return True
    return bool(host) and _host_name(host or "") in allowed_hosts()


def origin_allowed(origin: Optional[str], host: Optional[str]) -> bool:
    if not origin:
        return True
    parsed: Any = urlparse(origin)
    return bool(parsed.netloc) and parsed.netloc.lower() == (host or "").lower()


def _rate_settings() -> Tuple[int, float]:
    limit_raw: str = ""
    for name in RATE_LIMIT_ENV:
        if os.environ.get(name):
            limit_raw = os.environ[name]
            break
    try:
        limit: int = int(limit_raw) if limit_raw else 300
    except ValueError:
        limit = 300
    try:
        window: float = float(os.environ.get("BLACKOUT_RATE_WINDOW", os.environ.get("BLACKOUT_RATE_WINDOW_SECONDS", "60")))
    except ValueError:
        window = 60.0
    return max(0, limit), max(0.001, window)


def reset_rate_limit() -> None:
    _window_state.clear()
    _window_config.clear()


clear_rate_limits = reset_rate_limit
clear_rate_limit = reset_rate_limit


def check_rate_limit(client_ip: str, now: Optional[float] = None) -> bool:
    limit, window = _rate_settings()
    if limit <= 0:
        return False
    stamp: float = time.monotonic() if now is None else now
    config: Tuple[int, float] = (limit, window)
    if _window_config.get(client_ip) != config:
        _window_state[client_ip].clear()
        _window_config[client_ip] = config
    bucket: Deque[float] = _window_state[client_ip]
    while bucket and stamp - bucket[0] >= window:
        bucket.popleft()
    if len(bucket) >= limit:
        return False
    bucket.append(stamp)
    return True


def configured_token() -> str:
    return os.environ.get("BLACKOUT_ACCESS_TOKEN", "")


def _headers(scope: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for key, value in scope.get("headers", []):
        out[key.decode("latin-1").lower()] = value.decode("latin-1")
    return out


def _provided_token(scope: Dict[str, Any], headers: Dict[str, str]) -> Tuple[Optional[str], bool]:
    pairs: list = parse_qsl(scope.get("query_string", b"").decode("latin-1"), keep_blank_values=True)
    in_query: bool = any(k == "token" for k, _ in pairs)
    for key, value in pairs:
        if key == "token":
            return value, True
    cookie: str = headers.get("cookie", "")
    for part in cookie.split(";"):
        if "=" in part:
            key, value = part.strip().split("=", 1)
            if key == COOKIE_NAME:
                return value, in_query
    return None, in_query


def _owner_token(headers: Dict[str, str]) -> Optional[str]:
    cookie: str = headers.get("cookie", "")
    for part in cookie.split(";"):
        if "=" in part:
            key, value = part.strip().split("=", 1)
            if key == OWNER_COOKIE:
                token: str = value.strip()
                return token if _OWNER_RE.match(token) else None
    return None


def _owner_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def owner_of(connection: Any) -> str:
    scope: Any = getattr(connection, "scope", {})
    if not isinstance(scope, dict):
        return ""
    value: Any = scope.get("blackout_owner", "")
    return value if isinstance(value, str) else ""


def _tokens_match(provided: Optional[str], expected: str) -> bool:
    if provided is None:
        return False
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


def _token_ok(scope: Dict[str, Any], headers: Dict[str, str]) -> bool:
    expected: str = configured_token()
    if not expected:
        return True
    provided, _ = _provided_token(scope, headers)
    return _tokens_match(provided, expected)


def _body_limit(scope: Dict[str, Any]) -> int:
    path: str = str(scope.get("path", ""))
    if path == "/api/setup/key":
        return 8192
    if path in ("/api/transcribe",) or path.endswith("/turns"):
        return 32 * 1024 * 1024 + 1024 * 1024
    if path.endswith("/sketches"):
        return 8 * 1024 * 1024 + 1024 * 1024
    if path.startswith("/api/"):
        return 65536
    return 32 * 1024 * 1024 + 1024 * 1024


def _error(status: int, code: str, message: str) -> Tuple[int, bytes]:
    body: bytes = json.dumps({"error": {"code": code, "message": message}}, ensure_ascii=False).encode("utf-8")
    return status, body


def _security_headers_bytes(host: Optional[str] = None) -> list:
    headers: list = [(b"content-security-policy", csp_for(host).encode("latin-1"))]
    return headers + [(key.encode("latin-1"), value.encode("latin-1")) for key, value in SECURITY_HEADERS]


class SecurityMiddleware:
    """Pure ASGI middleware, so WebSockets and body limits are covered pre-read."""
    def __init__(self, app: Any) -> None:
        self.app: Any = app

    async def __call__(self, scope: Dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers: Dict[str, str] = _headers(scope)
        host: Optional[str] = headers.get("host")
        if not is_allowed_host(host):
            await self._reject(scope, send, 400, "invalid_host", "请求地址不正确。", 1008)
            return
        method: str = str(scope.get("method", "GET")).upper()
        path: str = str(scope.get("path", ""))
        if scope.get("type") == "http" and method != "GET" and path.startswith("/api/"):
            fetch_site: str = headers.get("sec-fetch-site", "").strip().lower()
            if fetch_site in ("cross-site", "same-site"):
                await self._reject(scope, send, 403, "forbidden_origin", "来源不正确。", 1008)
                return
        if scope.get("type") == "http" and method in ("POST", "PUT", "PATCH") and path.startswith("/api/"):
            if "transfer-encoding" in headers and "content-length" not in headers:
                await self._reject(scope, send, 411, "length_required", "请求缺少长度信息，请重试。", 1008)
                return
        if scope.get("type") == "websocket" or method != "GET":
            if not origin_allowed(headers.get("origin"), host):
                await self._reject(scope, send, 403, "forbidden_origin", "来源不正确。", 1008)
                return
        expected: str = configured_token()
        if expected:
            provided, in_query = _provided_token(scope, headers)
            valid: bool = _tokens_match(provided, expected)
            if in_query and valid and scope.get("type") == "http":
                await self._redirect_without_token(scope, send)
                return
            if not valid:
                await self._reject(scope, send, 401, "unauthorized", "访问令牌不正确。", 1008)
                return
        new_owner_token: Optional[str] = None
        valid_owner: Optional[str] = _owner_token(headers)
        if scope.get("type") == "http":
            effective_owner: str = valid_owner or ""
            if valid_owner is None:
                new_owner_token = secrets.token_urlsafe(24)
                effective_owner = new_owner_token
            scope["blackout_owner"] = _owner_digest(effective_owner)
        else:
            scope["blackout_owner"] = _owner_digest(valid_owner) if valid_owner else ""
        if scope.get("type") == "http":
            if path.startswith("/api/"):
                client: Any = scope.get("client") or ("unknown", 0)
                if not check_rate_limit(str(client[0])):
                    await self._reject(scope, send, 429, "rate_limited", "请求太频繁，请稍后再试。", 1008)
                    return
            length: Optional[str] = headers.get("content-length")
            if length is not None:
                try:
                    too_big: bool = int(length) > _body_limit(scope)
                except ValueError:
                    too_big = True
                if too_big:
                    await self._reject(scope, send, 400, "invalid_input", "内容太大，请缩小后再试。", 1008)
                    return
            secure: bool = str(scope.get("scheme", "")) == "https"
            await self.app(scope, receive, self._send_with_headers(send, new_owner_token, secure, host))
            return
        await self.app(scope, receive, send)

    def _send_with_headers(self, send: Any, owner_token: Optional[str] = None, secure: bool = False, host: Optional[str] = None) -> Any:
        async def wrapped(message: Dict[str, Any]) -> None:
            if message.get("type") == "http.response.start":
                headers: list = list(message.get("headers", []))
                present: set = {k.decode("latin-1").lower() for k, _ in headers}
                if "content-security-policy" not in present:
                    headers.append((b"content-security-policy", csp_for(host).encode("latin-1")))
                for key, value in SECURITY_HEADERS:
                    if key not in present:
                        headers.append((key.encode("latin-1"), value.encode("latin-1")))
                if owner_token:
                    cookie: str = f"{OWNER_COOKIE}={owner_token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=31536000"
                    if secure:
                        cookie = cookie + "; Secure"
                    headers.append((b"set-cookie", cookie.encode("latin-1")))
                message = dict(message)
                message["headers"] = headers
            await send(message)
        return wrapped

    async def _reject(self, scope: Dict[str, Any], send: Any, status: int, code: str, message: str, ws_code: int) -> None:
        if scope.get("type") == "websocket":
            await send({"type": "websocket.close", "code": ws_code})
            return
        status_out, body = _error(status, code, message)
        headers: list = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())] + _security_headers_bytes()
        await send({"type": "http.response.start", "status": status_out, "headers": headers})
        await send({"type": "http.response.body", "body": body})

    async def _redirect_without_token(self, scope: Dict[str, Any], send: Any) -> None:
        pairs: list = [(k, v) for k, v in parse_qsl(scope.get("query_string", b"").decode("latin-1"), keep_blank_values=True) if k != "token"]
        path: str = str(scope.get("path", "/"))
        location: str = path + (("?" + urlencode(pairs)) if pairs else "")
        cookie: str = f"{COOKIE_NAME}={configured_token()}; Path=/; HttpOnly; Secure; SameSite=Strict"
        headers: list = [(b"location", location.encode("latin-1")), (b"set-cookie", cookie.encode("latin-1")), (b"content-length", b"0")] + _security_headers_bytes()
        await send({"type": "http.response.start", "status": 303, "headers": headers})
        await send({"type": "http.response.body", "body": b""})
