"""Client-side hard spend cap for the Meta Model API."""
import json
import logging
import math
import os
import shutil
import time
from pathlib import Path
from typing import Any, NamedTuple

import httpx
import openai

logger: logging.Logger = logging.getLogger(__name__)

DEFAULT_STOP_AT_USD: float = 10.0
MAX_STOP_AT_USD: float = 140.0


def _resolve_stop_at(env_file: Path | None = None) -> float:
    """Resolve the spend cap from the environment, then the .env file."""
    raw: str = os.environ.get("BLACKOUT_STOP_AT_USD") or ""
    if not raw.strip():
        path: Path = Path(__file__).parent / ".env" if env_file is None else env_file
        try:
            text: str = path.read_text(encoding="utf-8-sig")
        except OSError:
            text = ""
        for line in text.splitlines():
            stripped: str = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in line:
                continue
            name: str
            _: str
            value: str
            name, _, value = line.partition("=")
            if name.strip() == "BLACKOUT_STOP_AT_USD":
                raw = value.strip()
                if len(raw) >= 2 and ((raw[0] == '"' and raw[-1] == '"') or (raw[0] == "'" and raw[-1] == "'")):
                    raw = raw[1:-1].strip()
                break
    try:
        amount: float = float(raw.strip())
    except Exception:
        return DEFAULT_STOP_AT_USD
    if not math.isfinite(amount) or amount <= 0:
        return DEFAULT_STOP_AT_USD
    if amount > MAX_STOP_AT_USD:
        return MAX_STOP_AT_USD
    return amount


STOP_AT_USD: float = _resolve_stop_at()
OLD_LEDGER_FILE: Path = Path(__file__).parent / ".muse_spend.jsonl"
IMAGE_PATH: str = "/v1/images/generations"
IMAGE_MODEL: str = "muse-image-1.0"
IMAGE_USD_PER_IMAGE: float = 0.01
METERED_PATHS: tuple[str, ...] = ("/v1/responses", "/v1/chat/completions", IMAGE_PATH)
TRANSCRIBE_PATH: str = "/v1/asr/transcribe"
TRANSCRIBE_MODEL: str = "muse-voice-transcribe-1.0"
TRANSCRIBE_USD_PER_HOUR: float = 0.18
TRANSCRIBE_WORST_CASE_USD: float = 0.03
WEB_SEARCH_USD_PER_QUERY: float = 2.50 / 1000.0
WEB_SEARCH_WORST_CASE_QUERIES: int = 10

_record_failed: bool = False


def _default_ledger_file() -> Path:
    """Default ledger location outside the repository."""
    if os.name == "nt":
        local: str = os.environ.get("LOCALAPPDATA") or ""
        if local:
            return Path(local) / "Blackout" / "spend.jsonl"
        return Path.home() / "Blackout" / "spend.jsonl"
    return Path.home() / ".blackout" / "spend.jsonl"


def _resolve_ledger_file() -> Path:
    """Resolve the ledger path, migrating the old repo ledger once."""
    explicit: str = os.environ.get("BLACKOUT_LEDGER_FILE") or ""
    if explicit:
        return Path(explicit)
    new_path: Path = _default_ledger_file()
    old_path: Path = OLD_LEDGER_FILE
    try:
        if new_path == old_path:
            return new_path
    except Exception:
        pass
    if not new_path.exists() and old_path.exists():
        try:
            new_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(old_path, new_path)
        except Exception:
            logger.exception("could not copy old spend ledger; keeping old ledger path")
            return old_path
    return new_path


LEDGER_FILE: Path = _resolve_ledger_file()


class Price(NamedTuple):
    """USD per 1M tokens."""

    input: float
    cached_input: float
    output: float


PRICES: dict[str, Price] = {
    "muse-wonder-1.0": Price(4.00, 0.20, 20.00),
    "muse-spark-1.3": Price(1.25, 0.15, 4.25),
    "muse-spark-1.2": Price(1.25, 0.15, 4.25),
    "muse-spark-1.1": Price(1.25, 0.15, 4.25),
    "muse-spark-1.3-contributor": Price(0.10, 0.002, 0.20),
    "muse-spark-1.2-contributor": Price(0.10, 0.002, 0.20),
}


def reset_record_failure() -> None:
    """Clear the spend-recording failure latch (for tests and recovery)."""
    global _record_failed
    _record_failed = False


def _ledger_path(ledger: Path | None) -> Path:
    """Resolve None to the module's current LEDGER_FILE at call time."""
    return LEDGER_FILE if ledger is None else ledger


def _validate_usd(usd_val: Any) -> float:
    if isinstance(usd_val, bool) or not isinstance(usd_val, (int, float)):
        raise ValueError(f"spend amount is not a number: {usd_val!r}")
    value: float = float(usd_val)
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"spend amount is negative or non-finite: {usd_val!r}")
    return value


def spent_usd(ledger: Path | None = None) -> float:
    """Sum the JSONL ledger; 0.0 if missing."""
    path: Path = _ledger_path(ledger)
    try:
        text: str = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return 0.0
    total: float = 0.0
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row: Any = json.loads(line)
        except Exception as exc:
            raise ValueError(f"spend ledger is unreadable: invalid JSON: {line!r}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"spend ledger is unreadable: not an object: {line!r}")
        usd_val: Any = row.get("usd")
        try:
            value: float = _validate_usd(usd_val)
        except ValueError as exc:
            raise ValueError(f"spend ledger is unreadable: bad usd value: {line!r}") from exc
        total += value
    if not math.isfinite(total) or total < 0:
        raise ValueError("spend ledger total is negative or non-finite")
    return total


def ledger_ok(ledger: Path | None = None) -> bool:
    """Whether the ledger can be read."""
    try:
        spent_usd(ledger)
    except Exception:
        return False
    return True


def can_spend(additional_usd: float = 0.0, ledger: Path | None = None, limit_usd: float | None = None) -> bool:
    """Whether additional spend is allowed; a corrupt ledger cannot spend."""
    if _record_failed:
        return False
    path: Path = _ledger_path(ledger)
    limit: float = STOP_AT_USD if limit_usd is None else limit_usd
    try:
        if not math.isfinite(float(limit)):
            return False
        spent: float = spent_usd(path)
    except Exception:
        return False
    try:
        additional_value: float = float(additional_usd)
    except Exception:
        return False
    if not math.isfinite(additional_value):
        return False
    additional: float = max(0.0, additional_value)
    if additional == 0.0:
        return spent < float(limit)
    return spent + additional <= float(limit)


def record_spend(ledger: Path, model: str, usd: float) -> None:
    """Append one spend line; append-only for concurrent processes."""
    global _record_failed
    value: float = _validate_usd(usd)
    row: str = json.dumps({"model": model, "usd": value})
    last_exc: Exception | None = None
    for attempt in range(5):
        try:
            ledger.parent.mkdir(parents=True, exist_ok=True)
            with open(ledger, "a", encoding="utf-8") as fh:
                fh.write(row + "\n")
            return
        except OSError as exc:
            last_exc = exc
            if attempt < 4:
                time.sleep(0.25)
    _record_failed = True
    logger.error("spend could not be recorded after retries: %s", last_exc)


def record_audio_seconds(seconds: float, ledger: Path | None = None) -> float:
    """Record realtime-audio spend for `seconds` and return its USD cost."""
    path: Path = _ledger_path(ledger)
    try:
        seconds_value: float = float(seconds)
    except Exception as exc:
        raise ValueError("audio seconds is not a number") from exc
    if not math.isfinite(seconds_value):
        raise ValueError("audio seconds is non-finite")
    cost: float = max(0.0, seconds_value) / 3600.0 * TRANSCRIBE_USD_PER_HOUR
    if cost:
        record_spend(path, TRANSCRIBE_MODEL, cost)
    return cost


def max_output_tokens(body: dict[str, Any]) -> int | None:
    """First truthy max-output value or None."""
    for key in ("max_output_tokens", "max_completion_tokens", "max_tokens"):
        val: Any = body.get(key)
        if val:
            try:
                return int(val)
            except Exception:
                return None
    return None


def _web_search_tool_count(body: dict[str, Any]) -> int:
    tools: Any = body.get("tools")
    if not isinstance(tools, list):
        return 0
    count: int = 0
    for tool in tools:
        if isinstance(tool, dict) and tool.get("type") == "web_search":
            count += 1
    return count


def web_search_call_count(data: Any) -> int:
    """Number of billed web_search_call items in a Responses payload."""
    if not isinstance(data, dict):
        return 0
    output: Any = data.get("output")
    if not isinstance(output, list):
        return 0
    count: int = 0
    for item in output:
        if isinstance(item, dict) and item.get("type") == "web_search_call":
            count += 1
    return count


def _image_count(body: dict[str, Any]) -> int:
    n_value: Any = body.get("n", 1)
    if isinstance(n_value, bool) or not isinstance(n_value, int):
        return 1
    return n_value if 1 <= n_value <= 4 else 1


def refusal_reason(path: str, body: dict[str, Any]) -> str | None:
    """Return refusal message or None if the call can be metered."""
    if path not in METERED_PATHS:
        return f"{path} has no price rule in budget.py"
    if path == IMAGE_PATH:
        if body.get("model") != IMAGE_MODEL:
            return f"model {body.get('model')!r} has no price in budget.py"
        if body.get("stream"):
            return "streaming and background calls cannot be metered"
        if "n" in body:
            n_value: Any = body.get("n")
            if isinstance(n_value, bool) or not isinstance(n_value, int):
                return "n must be an integer from 1 to 4"
            if n_value < 1 or n_value > 4:
                return "n must be an integer from 1 to 4"
        return None
    model: Any = body.get("model")
    if not isinstance(model, str) or model not in PRICES:
        return f"model {model!r} has no price in budget.py"
    if body.get("stream") or body.get("background"):
        return "streaming and background calls cannot be metered"
    tools: Any = body.get("tools")
    if isinstance(tools, list):
        for tool in tools:
            if not isinstance(tool, dict):
                return f"built-in tool {tool!r} has no price in budget.py"
            ttype: Any = tool.get("type", "")
            if ttype == "web_search":
                if path == "/v1/responses":
                    continue
                return "built-in search tools are billed per query and cannot be metered"
            if isinstance(ttype, str) and "search" in ttype.lower():
                return "built-in search tools are billed per query and cannot be metered"
            if ttype != "function":
                return f"built-in tool {ttype!r} has no price in budget.py"
    if not max_output_tokens(body):
        return "set max_output_tokens so the worst-case cost is known"
    return None


def worst_case_usd(body: dict[str, Any], request_bytes: int) -> float:
    """Worst-case cost: input bytes, max output tokens, ten searches if searching."""
    model: Any = body.get("model", "")
    if model == IMAGE_MODEL:
        return float(_image_count(body)) * IMAGE_USD_PER_IMAGE
    price: Price | None = PRICES.get(model) if isinstance(model, str) else None
    if price is None:
        return 0.0
    max_out: int = max_output_tokens(body) or 0
    in_tokens: float = float(request_bytes) / 2.0
    tokens: float = in_tokens / 1_000_000 * price.input + max_out / 1_000_000 * price.output
    search_tools: int = _web_search_tool_count(body)
    search: float = WEB_SEARCH_WORST_CASE_QUERIES * WEB_SEARCH_USD_PER_QUERY if search_tools else 0.0
    return tokens + search


def actual_usd(model: str, usage: dict[str, Any]) -> float:
    """Actual cost from usage; missing counts raise KeyError."""
    price: Price = PRICES[model]
    if "input_tokens" in usage:
        in_total: Any = usage["input_tokens"]
    elif "prompt_tokens" in usage:
        in_total = usage["prompt_tokens"]
    else:
        raise KeyError("input_tokens")
    if "output_tokens" in usage:
        out_total: Any = usage["output_tokens"]
    elif "completion_tokens" in usage:
        out_total = usage["completion_tokens"]
    else:
        raise KeyError("output_tokens")
    if not isinstance(in_total, (int, float)):
        raise KeyError("input_tokens")
    if not isinstance(out_total, (int, float)):
        raise KeyError("output_tokens")
    cached: int = 0
    for key in ("input_tokens_details", "prompt_tokens_details"):
        det: Any = usage.get(key)
        if isinstance(det, dict) and isinstance(det.get("cached_tokens"), (int, float)):
            cached = int(det["cached_tokens"])
            break
    rest: float = float(in_total) - float(cached)
    cached_cost: float = float(cached) / 1_000_000 * price.cached_input
    return rest / 1_000_000 * price.input + cached_cost + float(out_total) / 1_000_000 * price.output


def refusal_response(request: httpx.Request, message: str) -> httpx.Response:
    """Local 402 refusal; never raise from send."""
    payload: dict[str, Any] = {"error": {"code": "local_budget_guard", "message": f"Blocked locally: {message}"}}
    body: bytes = json.dumps(payload).encode("utf-8")
    return httpx.Response(402, content=body, headers={"Content-Type": "application/json"}, request=request)


def _duration_ms(data: Any) -> float | None:
    """Find audio duration ms in a transcribe response."""
    if isinstance(data, dict):
        for key in ("audioDurationMs", "audio_duration_ms", "durationMs", "duration_ms"):
            val: Any = data.get(key)
            if isinstance(val, (int, float)):
                return float(val)
        usage: Any = data.get("usage")
        if isinstance(usage, dict):
            found: float | None = _duration_ms(usage)
            if found is not None:
                return found
    return None


def _read_body(resp: httpx.Response) -> None:
    """Read response body, ignoring errors."""
    try:
        resp.read()
    except Exception:
        pass


class BudgetedHttpClient(openai.DefaultHttpxClient):
    """httpx client that enforces a hard spend cap locally."""

    def __init__(self, *, ledger: Path | None = None, limit_usd: float | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._ledger: Path = _ledger_path(ledger)
        self._limit_usd: float = STOP_AT_USD if limit_usd is None else limit_usd

    def send(self, request: httpx.Request, **kwargs: Any) -> httpx.Response:
        if request.method.upper() == "GET":
            return super().send(request, **kwargs)
        if _record_failed:
            return refusal_response(request, "spend could not be recorded, further paid calls are refused")
        path: str = request.url.path
        if path == TRANSCRIBE_PATH:
            return self._send_transcribe(request, **kwargs)
        return self._send_metered(request, **kwargs)

    def _send_transcribe(self, request: httpx.Request, **kwargs: Any) -> httpx.Response:
        if _record_failed:
            return refusal_response(request, "spend could not be recorded, further paid calls are refused")
        try:
            spent: float = spent_usd(self._ledger)
        except ValueError:
            return refusal_response(request, "spend ledger is unreadable, request blocked")
        if spent + TRANSCRIBE_WORST_CASE_USD > self._limit_usd:
            return refusal_response(request, "spending limit exceeded for transcription")
        try:
            resp: httpx.Response = super().send(request, **kwargs)
        except Exception:
            try:
                record_spend(self._ledger, TRANSCRIBE_MODEL, TRANSCRIBE_WORST_CASE_USD)
            except Exception:
                logger.exception("record transcribe spend failed")
            raise
        _read_body(resp)
        if not 200 <= resp.status_code < 300:
            return resp
        try:
            ms: float | None = _duration_ms(resp.json())
            if ms is None:
                raise ValueError("no duration")
            cost: float = ms / 3_600_000 * TRANSCRIBE_USD_PER_HOUR
        except Exception:
            cost = TRANSCRIBE_WORST_CASE_USD
        try:
            record_spend(self._ledger, TRANSCRIBE_MODEL, cost)
        except Exception:
            logger.exception("record transcribe spend failed")
        return resp

    def _send_metered(self, request: httpx.Request, **kwargs: Any) -> httpx.Response:
        if _record_failed:
            return refusal_response(request, "spend could not be recorded, further paid calls are refused")
        try:
            request.read()
        except Exception:
            pass
        try:
            raw: bytes = request.content or b""
        except Exception:
            return refusal_response(request, "request body is not JSON and cannot be priced")
        try:
            current_spent: float = spent_usd(self._ledger)
        except ValueError:
            return refusal_response(request, "spend ledger is unreadable, request blocked")
        try:
            body: Any = json.loads(raw.decode("utf-8"))
            if not isinstance(body, dict):
                raise ValueError("not a dict")
        except Exception:
            return refusal_response(request, "request body is not JSON and cannot be priced")
        reason: str | None = refusal_reason(request.url.path, body)
        if reason is not None:
            return refusal_response(request, reason)
        worst: float = worst_case_usd(body, len(raw))
        if current_spent + worst > self._limit_usd:
            return refusal_response(request, "spending limit exceeded for this call")
        try:
            resp: httpx.Response = super().send(request, **kwargs)
        except Exception:
            try:
                record_spend(self._ledger, str(body.get("model", "")), worst)
            except Exception:
                logger.exception("record spend failed")
            raise
        _read_body(resp)
        if not 200 <= resp.status_code < 300:
            return resp
        model: str = str(body.get("model", ""))
        if request.url.path == IMAGE_PATH:
            try:
                payload: Any = resp.json()
                entries: Any = payload.get("data") if isinstance(payload, dict) else None
                if not isinstance(entries, list):
                    raise ValueError("missing image data")
                cost = float(len(entries)) * IMAGE_USD_PER_IMAGE
            except Exception:
                cost = worst
            try:
                record_spend(self._ledger, IMAGE_MODEL, cost)
            except Exception:
                logger.exception("record spend failed")
            return resp
        try:
            data: Any = resp.json()
            usage: Any = data.get("usage") if isinstance(data, dict) else None
            if not isinstance(usage, dict):
                raise ValueError("missing usage")
            cost = actual_usd(model, usage) + web_search_call_count(data) * WEB_SEARCH_USD_PER_QUERY
        except Exception:
            cost = worst
        try:
            record_spend(self._ledger, model, cost)
        except Exception:
            logger.exception("record spend failed")
        return resp


if __name__ == "__main__":
    total: float = spent_usd()
    print(f"Spent ${total:.4f} of the ${STOP_AT_USD:.2f} limit")
