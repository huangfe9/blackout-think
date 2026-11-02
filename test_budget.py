"""Tests for budget.py spend guard."""
import builtins
import json
import os
from pathlib import Path
from typing import Any

import httpx
import openai
import pytest

import budget
from budget import BudgetedHttpClient, actual_usd, can_spend, record_audio_seconds, record_spend, refusal_reason, spent_usd, web_search_call_count, worst_case_usd

MODEL: str = "muse-spark-1.3"
BASE: str = "https://api.meta.ai/v1"


def _ok_handler(usage: dict[str, Any], seen: dict[str, int]) -> Any:
    def handle(request: httpx.Request) -> httpx.Response:
        seen["n"] = int(seen.get("n", 0)) + 1
        return httpx.Response(200, json={"id": "resp_1", "usage": usage})
    return handle


def _make_openai(ledger: Path, handler: Any, max_retries: int = 0, limit: float = 140.0) -> openai.OpenAI:
    transport: httpx.MockTransport = httpx.MockTransport(handler)
    http_client: BudgetedHttpClient = BudgetedHttpClient(ledger=ledger, limit_usd=limit, transport=transport)
    return openai.OpenAI(api_key="test-key", base_url=BASE, http_client=http_client, max_retries=max_retries)


def test_actual_cost_recorded(tmp_path: Path) -> None:
    ledger: Path = tmp_path / "spend.jsonl"
    seen: dict[str, int] = {}
    client: openai.OpenAI = _make_openai(ledger, _ok_handler({"input_tokens": 1000, "output_tokens": 500}, seen))
    client.responses.create(model=MODEL, input="hi", max_output_tokens=200)
    assert seen["n"] == 1
    expect: float = 1000 / 1_000_000 * 1.25 + 500 / 1_000_000 * 4.25
    assert spent_usd(ledger) == pytest.approx(expect)


def test_spend_accumulates(tmp_path: Path) -> None:
    ledger: Path = tmp_path / "spend.jsonl"
    seen: dict[str, int] = {}
    client: openai.OpenAI = _make_openai(ledger, _ok_handler({"input_tokens": 1000, "output_tokens": 100}, seen))
    client.responses.create(model=MODEL, input="a", max_output_tokens=100)
    client.responses.create(model=MODEL, input="b", max_output_tokens=100)
    one: float = 1000 / 1_000_000 * 1.25 + 100 / 1_000_000 * 4.25
    assert spent_usd(ledger) == pytest.approx(one * 2)


def test_blocked_at_limit(tmp_path: Path) -> None:
    ledger: Path = tmp_path / "spend.jsonl"
    seen: dict[str, int] = {}
    client: openai.OpenAI = _make_openai(ledger, _ok_handler({"input_tokens": 10, "output_tokens": 10}, seen), limit=0.001)
    with pytest.raises(openai.APIStatusError) as exc:
        client.responses.create(model=MODEL, input="hi", max_output_tokens=2000)
    assert exc.value.status_code == 402
    assert seen.get("n", 0) == 0
    assert spent_usd(ledger) == 0.0


def test_blocked_not_retried(tmp_path: Path) -> None:
    ledger: Path = tmp_path / "spend.jsonl"
    seen: dict[str, int] = {}
    client: openai.OpenAI = _make_openai(ledger, _ok_handler({"input_tokens": 10, "output_tokens": 10}, seen), max_retries=2, limit=0.001)
    with pytest.raises(openai.APIStatusError):
        client.responses.create(model=MODEL, input="hi", max_output_tokens=2000)
    assert seen.get("n", 0) == 0


def test_refuse_no_max_output(tmp_path: Path) -> None:
    ledger: Path = tmp_path / "spend.jsonl"
    seen: dict[str, int] = {}
    client: openai.OpenAI = _make_openai(ledger, _ok_handler({"input_tokens": 1, "output_tokens": 1}, seen))
    with pytest.raises(openai.APIStatusError) as exc:
        client.responses.create(model=MODEL, input="hi")
    assert exc.value.status_code == 402
    assert seen.get("n", 0) == 0


def test_refuse_stream(tmp_path: Path) -> None:
    ledger: Path = tmp_path / "spend.jsonl"
    seen: dict[str, int] = {}
    client: openai.OpenAI = _make_openai(ledger, _ok_handler({"input_tokens": 1, "output_tokens": 1}, seen))
    with pytest.raises(openai.APIStatusError):
        client.responses.create(model=MODEL, input="hi", max_output_tokens=50, stream=True)  # type: ignore[call-arg]
    assert seen.get("n", 0) == 0


def test_refuse_background(tmp_path: Path) -> None:
    ledger: Path = tmp_path / "spend.jsonl"
    seen: dict[str, int] = {}
    client: openai.OpenAI = _make_openai(ledger, _ok_handler({"input_tokens": 1, "output_tokens": 1}, seen))
    with pytest.raises(openai.APIStatusError):
        client.responses.create(model=MODEL, input="hi", max_output_tokens=50, background=True)  # type: ignore[call-arg]
    assert seen.get("n", 0) == 0


def test_refuse_unpriced_model(tmp_path: Path) -> None:
    ledger: Path = tmp_path / "spend.jsonl"
    seen: dict[str, int] = {}
    client: openai.OpenAI = _make_openai(ledger, _ok_handler({"input_tokens": 1, "output_tokens": 1}, seen))
    with pytest.raises(openai.APIStatusError):
        client.responses.create(model="nope-9.9", input="hi", max_output_tokens=50)
    assert seen.get("n", 0) == 0


def test_web_search_allowed_and_charged_per_call(tmp_path: Path) -> None:
    ledger: Path = tmp_path / "spend.jsonl"
    seen: dict[str, int] = {}
    def handle(request: httpx.Request) -> httpx.Response:
        seen["n"] = int(seen.get("n", 0)) + 1
        return httpx.Response(200, json={"id": "r", "usage": {"input_tokens": 1000, "output_tokens": 100}, "output": [{"type": "web_search_call"}, {"type": "web_search_call"}, {"type": "message"}]})
    client: openai.OpenAI = _make_openai(ledger, handle)
    client.responses.create(model=MODEL, input="hi", max_output_tokens=50, tools=[{"type": "web_search", "search_context_size": "medium"}], include=["web_search_call.results"])  # type: ignore[call-arg]
    assert seen["n"] == 1
    tokens: float = 1000 / 1_000_000 * 1.25 + 100 / 1_000_000 * 4.25
    assert spent_usd(ledger) == pytest.approx(tokens + 2 * budget.WEB_SEARCH_USD_PER_QUERY)
    assert web_search_call_count({"output": [{"type": "web_search_call"}]}) == 1
    assert worst_case_usd({"model": MODEL, "max_output_tokens": 10, "tools": [{"type": "web_search"}]}, 0) > worst_case_usd({"model": MODEL, "max_output_tokens": 10}, 0)


def test_web_search_worst_case_includes_ten_queries() -> None:
    assert budget.WEB_SEARCH_WORST_CASE_QUERIES == 10
    tokens: float = 1000 / 1_000_000 * 4.25
    one_tool: float = worst_case_usd({"model": MODEL, "max_output_tokens": 1000, "tools": [{"type": "web_search"}]}, 0)
    three_tools: float = worst_case_usd({"model": MODEL, "max_output_tokens": 1000, "tools": [{"type": "web_search"}, {"type": "web_search"}, {"type": "web_search"}]}, 0)
    assert one_tool == pytest.approx(tokens + 10 * budget.WEB_SEARCH_USD_PER_QUERY)
    assert three_tools == pytest.approx(one_tool)
    assert worst_case_usd({"model": MODEL, "max_output_tokens": 1000}, 0) == pytest.approx(tokens)


def test_web_search_refused_on_chat_completions(tmp_path: Path) -> None:
    body: dict[str, Any] = {"model": MODEL, "max_tokens": 50, "tools": [{"type": "web_search"}]}
    assert refusal_reason("/v1/chat/completions", body) == "built-in search tools are billed per query and cannot be metered"
    responses_body: dict[str, Any] = {"model": MODEL, "max_output_tokens": 50, "tools": [{"type": "web_search"}]}
    assert refusal_reason("/v1/responses", responses_body) is None
    ledger: Path = tmp_path / "spend.jsonl"
    seen: dict[str, int] = {}
    def handle(request: httpx.Request) -> httpx.Response:
        seen["n"] = 1
        return httpx.Response(200, json={"id": "x", "usage": {"input_tokens": 1, "output_tokens": 1}})
    transport: httpx.MockTransport = httpx.MockTransport(handle)
    with BudgetedHttpClient(ledger=ledger, transport=transport) as http_client:
        resp: httpx.Response = http_client.post(f"{BASE}/chat/completions", json={"model": MODEL, "max_tokens": 50, "messages": [], "tools": [{"type": "web_search"}]})
    assert resp.status_code == 402
    assert seen.get("n", 0) == 0
    assert spent_usd(ledger) == 0.0


def test_web_search_queries_in_response_are_charged(tmp_path: Path) -> None:
    ledger: Path = tmp_path / "spend.jsonl"
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "r", "usage": {"input_tokens": 2000, "output_tokens": 200}, "output": [{"type": "web_search_call"}, {"type": "web_search_call"}, {"type": "web_search_call"}, {"type": "message"}]})
    client: openai.OpenAI = _make_openai(ledger, handle)
    client.responses.create(model=MODEL, input="hi", max_output_tokens=50, tools=[{"type": "web_search", "search_context_size": "medium"}], include=["web_search_call.results"])  # type: ignore[call-arg]
    tokens: float = 2000 / 1_000_000 * 1.25 + 200 / 1_000_000 * 4.25
    assert web_search_call_count({"output": [{"type": "web_search_call"}] * 3}) == 3
    assert spent_usd(ledger) == pytest.approx(tokens + 3 * budget.WEB_SEARCH_USD_PER_QUERY)


def test_can_spend_real_with_temporary_ledger(tmp_path: Path) -> None:
    ledger: Path = tmp_path / "spend.jsonl"
    assert can_spend(ledger=ledger, limit_usd=10.0) is True
    assert can_spend(9.99, ledger=ledger, limit_usd=10.0) is True
    assert can_spend(10.01, ledger=ledger, limit_usd=10.0) is False
    ledger.write_text(json.dumps({"model": MODEL, "usd": 9.50}) + "\n", encoding="utf-8")
    assert spent_usd(ledger) == pytest.approx(9.50)
    assert can_spend(0.50, ledger=ledger, limit_usd=10.0) is True
    assert can_spend(0.51, ledger=ledger, limit_usd=10.0) is False
    ledger.write_text("not-json\n", encoding="utf-8")
    assert can_spend(ledger=ledger, limit_usd=10.0) is False
    assert budget.ledger_ok(ledger) is False
    with pytest.raises(ValueError):
        spent_usd(ledger)


def test_can_spend_at_exact_limit() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        ledger: Path = Path(tmp) / "spend.jsonl"
        ledger.write_text(json.dumps({"model": MODEL, "usd": budget.STOP_AT_USD}) + "\n", encoding="utf-8")
        assert can_spend(ledger=ledger) is False
        assert can_spend(0.0, ledger=ledger) is False
        ledger.write_text(json.dumps({"model": MODEL, "usd": 1.0}) + "\n", encoding="utf-8")
        assert can_spend(ledger=ledger, limit_usd=10.0) is True
        assert can_spend(9.0, ledger=ledger, limit_usd=10.0) is True
        assert can_spend(9.01, ledger=ledger, limit_usd=10.0) is False


def test_refuse_other_builtin_tools(tmp_path: Path) -> None:
    for tool in ({"type": "image_generation"}, {"type": "code_interpreter"}, "function"):
        ledger: Path = tmp_path / "spend.jsonl"
        if ledger.exists():
            ledger.unlink()
        seen: dict[str, int] = {}
        client: openai.OpenAI = _make_openai(ledger, _ok_handler({"input_tokens": 1, "output_tokens": 1}, seen))
        with pytest.raises(openai.APIStatusError):
            client.responses.create(model=MODEL, input="hi", max_output_tokens=50, tools=[tool])  # type: ignore[call-arg]
        assert seen.get("n", 0) == 0


def test_function_tool_allowed(tmp_path: Path) -> None:
    ledger: Path = tmp_path / "spend.jsonl"
    seen: dict[str, int] = {}
    client: openai.OpenAI = _make_openai(ledger, _ok_handler({"input_tokens": 100, "output_tokens": 10}, seen))
    client.responses.create(model=MODEL, input="hi", max_output_tokens=50, tools=[{"type": "function", "name": "get_weather", "description": "x", "parameters": {"type": "object", "properties": {}}}])  # type: ignore[call-arg]
    assert seen.get("n", 0) == 1


def test_refuse_unpriced_endpoint(tmp_path: Path) -> None:
    ledger: Path = tmp_path / "spend.jsonl"
    seen: dict[str, int] = {}
    def handle(request: httpx.Request) -> httpx.Response:
        seen["n"] = int(seen.get("n", 0)) + 1
        return httpx.Response(200, json={})
    client: openai.OpenAI = _make_openai(ledger, handle)
    with pytest.raises(openai.APIStatusError):
        client.embeddings.create(model=MODEL, input="hi")
    assert seen.get("n", 0) == 0


def test_failed_call_records_nothing(tmp_path: Path) -> None:
    ledger: Path = tmp_path / "spend.jsonl"
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})
    client: openai.OpenAI = _make_openai(ledger, handle)
    with pytest.raises(openai.APIStatusError):
        client.responses.create(model=MODEL, input="hi", max_output_tokens=50)
    assert spent_usd(ledger) == 0.0


def test_unreadable_usage_records_worst_case(tmp_path: Path) -> None:
    ledger: Path = tmp_path / "spend.jsonl"
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "resp_1"})
    client: openai.OpenAI = _make_openai(ledger, handle)
    client.responses.create(model=MODEL, input="hi", max_output_tokens=50)
    assert spent_usd(ledger) > 0.0


def test_get_uncharged(tmp_path: Path) -> None:
    ledger: Path = tmp_path / "spend.jsonl"
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})
    transport: httpx.MockTransport = httpx.MockTransport(handle)
    with BudgetedHttpClient(ledger=ledger, transport=transport) as http_client:
        resp: httpx.Response = http_client.get(f"{BASE}/models")
    assert resp.status_code == 200
    assert spent_usd(ledger) == 0.0


def test_cached_tokens_rate() -> None:
    usage: dict[str, Any] = {"input_tokens": 1000, "output_tokens": 100, "input_tokens_details": {"cached_tokens": 1000}}
    assert actual_usd(MODEL, usage) == pytest.approx(1000 / 1_000_000 * 0.15 + 100 / 1_000_000 * 4.25)


def test_chat_cached_tokens_rate() -> None:
    usage: dict[str, Any] = {"prompt_tokens": 2000, "completion_tokens": 10, "prompt_tokens_details": {"cached_tokens": 500}}
    expect: float = 1500 / 1_000_000 * 1.25 + 500 / 1_000_000 * 0.15 + 10 / 1_000_000 * 4.25
    assert actual_usd(MODEL, usage) == pytest.approx(expect)


def test_transcription_charged_by_duration(tmp_path: Path) -> None:
    ledger: Path = tmp_path / "spend.jsonl"
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"transcript": "hi", "audioDurationMs": 60000})
    transport: httpx.MockTransport = httpx.MockTransport(handle)
    with BudgetedHttpClient(ledger=ledger, transport=transport) as http_client:
        resp: httpx.Response = http_client.post(f"{BASE}/asr/transcribe", content=b"fake")
    assert resp.status_code == 200
    assert spent_usd(ledger) == pytest.approx(60000 / 3_600_000 * 0.18)


def test_transcription_blocked_at_limit(tmp_path: Path) -> None:
    ledger: Path = tmp_path / "spend.jsonl"
    seen: dict[str, int] = {}
    def handle(request: httpx.Request) -> httpx.Response:
        seen["n"] = 1
        return httpx.Response(200, json={"transcript": "hi", "audioDurationMs": 1000})
    transport: httpx.MockTransport = httpx.MockTransport(handle)
    with BudgetedHttpClient(ledger=ledger, limit_usd=0.001, transport=transport) as http_client:
        resp: httpx.Response = http_client.post(f"{BASE}/asr/transcribe", content=b"fake")
    assert resp.status_code == 402
    assert seen.get("n", 0) == 0


def test_spent_usd_corrupt_raises(tmp_path: Path) -> None:
    for bad in ("not-json", "[1, 2]", '{"model": "x"}', '{"model": "x", "usd": "lots"}', '{"model": "x", "usd": null}'):
        ledger: Path = tmp_path / "spend.jsonl"
        ledger.write_text(bad + "\n", encoding="utf-8")
        with pytest.raises(ValueError):
            spent_usd(ledger)
    ledger.write_text('\n{"model": "a", "usd": 0.5}\n\n{"model": "b", "usd": 0.25}\n', encoding="utf-8")
    assert spent_usd(ledger) == pytest.approx(0.75)


def test_corrupt_ledger_refused_and_can_spend_false(tmp_path: Path) -> None:
    ledger: Path = tmp_path / "spend.jsonl"
    ledger.write_text("corrupt\n", encoding="utf-8")
    seen: dict[str, int] = {}
    client: openai.OpenAI = _make_openai(ledger, _ok_handler({"input_tokens": 1, "output_tokens": 1}, seen))
    with pytest.raises(openai.APIStatusError) as exc:
        client.responses.create(model=MODEL, input="hi", max_output_tokens=50)
    assert exc.value.status_code == 402
    assert seen.get("n", 0) == 0
    assert can_spend(ledger=ledger) is False
    assert budget.ledger_ok(ledger) is False


def test_can_spend_and_record_audio_seconds(tmp_path: Path) -> None:
    ledger: Path = tmp_path / "spend.jsonl"
    assert can_spend(1.0, ledger=ledger, limit_usd=2.0) is True
    cost: float = record_audio_seconds(3600, ledger=ledger)
    assert cost == pytest.approx(0.18)
    assert spent_usd(ledger) == pytest.approx(0.18)
    assert can_spend(2.0, ledger=ledger, limit_usd=2.0) is False


def test_multipart_refused(tmp_path: Path) -> None:
    ledger: Path = tmp_path / "spend.jsonl"
    seen: dict[str, int] = {}
    def handle(request: httpx.Request) -> httpx.Response:
        seen["n"] = 1
        return httpx.Response(200, json={"id": "resp_1", "usage": {"input_tokens": 1, "output_tokens": 1}})
    transport: httpx.MockTransport = httpx.MockTransport(handle)
    with BudgetedHttpClient(ledger=ledger, transport=transport) as http_client:
        resp: httpx.Response = http_client.post(f"{BASE}/responses", files={"file": ("a.txt", b"hello")})
    assert resp.status_code == 402
    assert seen.get("n", 0) == 0


# --- spent_usd / record_spend validation and latch ----------------------

@pytest.mark.parametrize("raw", ['{"model": "x", "usd": -1}', '{"model": "x", "usd": -0.5}', '{"model": "x", "usd": NaN}', '{"model": "x", "usd": Infinity}', '{"model": "x", "usd": -Infinity}'])
def test_spent_usd_rejects_negative_and_nonfinite_and_can_spend_false(tmp_path: Path, raw: str) -> None:
    ledger: Path = tmp_path / "spend.jsonl"
    ledger.write_text(raw + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        spent_usd(ledger)
    assert can_spend(ledger=ledger) is False
    assert budget.ledger_ok(ledger) is False


@pytest.mark.parametrize("amount", [-1.0, -0.01, float("nan"), float("inf"), float("-inf")])
def test_record_spend_refuses_negative_or_nonfinite(tmp_path: Path, amount: float) -> None:
    budget.reset_record_failure()
    ledger: Path = tmp_path / "spend.jsonl"
    with pytest.raises(ValueError):
        record_spend(ledger, MODEL, amount)
    assert spent_usd(ledger) == 0.0


def test_record_spend_retries_twice_then_succeeds_without_latch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    budget.reset_record_failure()
    ledger: Path = tmp_path / "spend.jsonl"
    calls: dict[str, int] = {"n": 0}
    real_open: Any = builtins.open
    def flaky(file: Any, *args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] <= 2:
            raise PermissionError("locked")
        return real_open(file, *args, **kwargs)
    monkeypatch.setattr(builtins, "open", flaky)
    monkeypatch.setattr(budget.time, "sleep", lambda _s: None)
    try:
        record_spend(ledger, MODEL, 0.25)
        assert calls["n"] == 3
        assert budget._record_failed is False
        assert can_spend(ledger=ledger, limit_usd=10.0) is True
    finally:
        budget.reset_record_failure()
    assert spent_usd(ledger) == pytest.approx(0.25)
    assert len(ledger.read_text(encoding="utf-8").strip().splitlines()) == 1


def test_record_spend_always_failing_latches_and_client_refuses_without_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    budget.reset_record_failure()
    ledger: Path = tmp_path / "spend.jsonl"
    def always_fail(file: Any, *args: Any, **kwargs: Any) -> Any:
        raise PermissionError("locked")
    monkeypatch.setattr(builtins, "open", always_fail)
    monkeypatch.setattr(budget.time, "sleep", lambda _s: None)
    try:
        record_spend(ledger, MODEL, 0.25)
        assert budget._record_failed is True
        assert can_spend(ledger=ledger) is False
        seen: dict[str, int] = {}
        client: openai.OpenAI = _make_openai(ledger, _ok_handler({"input_tokens": 1, "output_tokens": 1}, seen))
        with pytest.raises(openai.APIStatusError) as exc:
            client.responses.create(model=MODEL, input="hi", max_output_tokens=50)
        assert exc.value.status_code == 402
        assert seen.get("n", 0) == 0
    finally:
        monkeypatch.undo()
        budget.reset_record_failure()
    assert budget._record_failed is False
    assert can_spend(ledger=ledger, limit_usd=10.0) is True


def test_transport_error_records_worst_case_and_reraises(tmp_path: Path) -> None:
    budget.reset_record_failure()
    ledger: Path = tmp_path / "spend.jsonl"
    seen: dict[str, int] = {}
    def broken(request: httpx.Request) -> httpx.Response:
        seen["n"] = int(seen.get("n", 0)) + 1
        raise httpx.ConnectError("connection dropped", request=request)
    client: openai.OpenAI = _make_openai(ledger, broken)
    with pytest.raises(openai.APIConnectionError):
        client.responses.create(model=MODEL, input="hi", max_output_tokens=50)
    assert seen["n"] == 1
    # The provider may have billed a request that died in transit, so the
    # worst case is recorded even though no response came back.
    assert spent_usd(ledger) > 0.0


def test_500_response_records_nothing_direct_client(tmp_path: Path) -> None:
    budget.reset_record_failure()
    ledger: Path = tmp_path / "spend.jsonl"
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})
    transport: httpx.MockTransport = httpx.MockTransport(handle)
    with BudgetedHttpClient(ledger=ledger, transport=transport) as http_client:
        resp: httpx.Response = http_client.post(f"{BASE}/responses", json={"model": MODEL, "input": "hi", "max_output_tokens": 50})
    assert resp.status_code == 500
    assert spent_usd(ledger) == 0.0


# --- Ledger location and one-time migration -----------------------------

def test_data_dir_env_does_not_change_ledger_location(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("BLACKOUT_LEDGER_FILE", raising=False)
    before: Path = budget._default_ledger_file()
    monkeypatch.setenv("BLACKOUT_DATA_DIR", str(tmp_path / "somewhere-else"))
    assert budget._default_ledger_file() == before
    assert tmp_path not in budget._default_ledger_file().parents


def test_explicit_ledger_file_env_wins(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    custom: Path = tmp_path / "custom" / "spend.jsonl"
    old: Path = tmp_path / "repo" / ".muse_spend.jsonl"
    old.parent.mkdir(parents=True)
    old.write_text('{"model": "x", "usd": 1.0}\n', encoding="utf-8")
    monkeypatch.setenv("BLACKOUT_LEDGER_FILE", str(custom))
    monkeypatch.setattr(budget, "OLD_LEDGER_FILE", old)
    monkeypatch.setattr(budget, "_default_ledger_file", lambda: tmp_path / "default" / "spend.jsonl")
    assert budget._resolve_ledger_file() == custom
    # The explicit location is used as-is: no migration copy is made.
    assert not custom.exists()


def test_migration_copies_old_ledger_once_only_when_default_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("BLACKOUT_LEDGER_FILE", raising=False)
    old: Path = tmp_path / "repo" / ".muse_spend.jsonl"
    old.parent.mkdir(parents=True)
    old.write_text('{"model": "x", "usd": 3.5}\n', encoding="utf-8")
    default: Path = tmp_path / "home" / ".blackout" / "spend.jsonl"
    monkeypatch.setattr(budget, "OLD_LEDGER_FILE", old)
    monkeypatch.setattr(budget, "_default_ledger_file", lambda: default)
    resolved: Path = budget._resolve_ledger_file()
    assert resolved == default
    assert default.read_text(encoding="utf-8") == '{"model": "x", "usd": 3.5}\n'
    # A second resolution must not copy again over newer default content.
    default.write_text('{"model": "y", "usd": 9.0}\n', encoding="utf-8")
    old.write_text('{"model": "x", "usd": 100.0}\n', encoding="utf-8")
    assert budget._resolve_ledger_file() == default
    assert default.read_text(encoding="utf-8") == '{"model": "y", "usd": 9.0}\n'


def test_migration_never_overwrites_existing_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("BLACKOUT_LEDGER_FILE", raising=False)
    old: Path = tmp_path / "repo" / ".muse_spend.jsonl"
    old.parent.mkdir(parents=True)
    old.write_text('{"model": "x", "usd": 100.0}\n', encoding="utf-8")
    default: Path = tmp_path / "home" / ".blackout" / "spend.jsonl"
    default.parent.mkdir(parents=True)
    default.write_text('{"model": "y", "usd": 2.0}\n', encoding="utf-8")
    monkeypatch.setattr(budget, "OLD_LEDGER_FILE", old)
    monkeypatch.setattr(budget, "_default_ledger_file", lambda: default)
    assert budget._resolve_ledger_file() == default
    assert default.read_text(encoding="utf-8") == '{"model": "y", "usd": 2.0}\n'
    assert spent_usd(default) == pytest.approx(2.0)
    assert os.path.exists(str(old))


# --- Image generation metering -------------------------------------------

IMAGE_MODEL: str = "muse-image-1.0"
IMAGE_PATH: str = "/v1/images/generations"


def _image_client(ledger: Path, handler: Any, limit: float = 140.0) -> BudgetedHttpClient:
    transport: httpx.MockTransport = httpx.MockTransport(handler)
    return BudgetedHttpClient(ledger=ledger, limit_usd=limit, transport=transport)


def test_image_generations_allowed_for_image_model_without_max_tokens() -> None:
    # No max_output_tokens is needed for a flat per-image price.
    assert refusal_reason(IMAGE_PATH, {"model": IMAGE_MODEL}) is None
    assert refusal_reason(IMAGE_PATH, {"model": IMAGE_MODEL, "prompt": "draw this"}) is None


@pytest.mark.parametrize("n", [1, 2, 3, 4])
def test_image_generations_allowed_n_1_to_4(n: int) -> None:
    assert refusal_reason(IMAGE_PATH, {"model": IMAGE_MODEL, "n": n}) is None


def test_image_generations_refused_for_another_model() -> None:
    assert refusal_reason(IMAGE_PATH, {"model": MODEL}) is not None
    assert refusal_reason(IMAGE_PATH, {"model": "muse-image-9.9"}) is not None
    assert refusal_reason(IMAGE_PATH, {}) is not None


@pytest.mark.parametrize("n", [0, 5, -1, 100])
def test_image_generations_refused_n_out_of_range(n: int) -> None:
    assert refusal_reason(IMAGE_PATH, {"model": IMAGE_MODEL, "n": n}) is not None


@pytest.mark.parametrize("n", ["1", "two", 1.5, 2.0, True, False, None])
def test_image_generations_refused_non_integer_n(n: Any) -> None:
    assert refusal_reason(IMAGE_PATH, {"model": IMAGE_MODEL, "n": n}) is not None


def test_image_generations_refused_for_stream() -> None:
    assert refusal_reason(IMAGE_PATH, {"model": IMAGE_MODEL, "stream": True}) is not None
    assert refusal_reason(IMAGE_PATH, {"model": IMAGE_MODEL, "stream": 1}) is not None


def test_image_refusals_do_not_reach_network_or_ledger(tmp_path: Path) -> None:
    ledger: Path = tmp_path / "spend.jsonl"
    seen: dict[str, int] = {}
    def handle(request: httpx.Request) -> httpx.Response:
        seen["n"] = int(seen.get("n", 0)) + 1
        return httpx.Response(200, json={"data": [{"b64_json": "x"}]})
    bodies: list[dict[str, Any]] = [
        {"model": MODEL},
        {"model": IMAGE_MODEL, "n": 0},
        {"model": IMAGE_MODEL, "n": 5},
        {"model": IMAGE_MODEL, "n": "2"},
        {"model": IMAGE_MODEL, "stream": True},
    ]
    with _image_client(ledger, handle) as http_client:
        for body in bodies:
            resp: httpx.Response = http_client.post(f"{BASE}/images/generations", json=body)
            assert resp.status_code == 402, body
    assert seen.get("n", 0) == 0
    assert spent_usd(ledger) == 0.0


def test_image_worst_case_is_n_times_one_cent() -> None:
    assert budget.IMAGE_USD_PER_IMAGE == pytest.approx(0.01)
    assert worst_case_usd({"model": IMAGE_MODEL}, 0) == pytest.approx(0.01)
    assert worst_case_usd({"model": IMAGE_MODEL, "n": 1}, 0) == pytest.approx(0.01)
    assert worst_case_usd({"model": IMAGE_MODEL, "n": 3}, 999999) == pytest.approx(0.03)
    assert worst_case_usd({"model": IMAGE_MODEL, "n": 4}, 0) == pytest.approx(0.04)


def test_image_success_records_data_entries_times_one_cent(tmp_path: Path) -> None:
    ledger: Path = tmp_path / "spend.jsonl"
    seen: dict[str, int] = {}
    def handle(request: httpx.Request) -> httpx.Response:
        seen["n"] = int(seen.get("n", 0)) + 1
        return httpx.Response(200, json={"data": [{"b64_json": "a"}, {"b64_json": "b"}]})
    with _image_client(ledger, handle) as http_client:
        resp: httpx.Response = http_client.post(
            f"{BASE}/images/generations",
            json={"model": IMAGE_MODEL, "prompt": "draw", "n": 1},
        )
    assert resp.status_code == 200
    assert seen["n"] == 1
    # Actual billing follows the returned entries, not the requested n.
    assert spent_usd(ledger) == pytest.approx(2 * 0.01)


def test_image_success_single_entry_records_one_cent(tmp_path: Path) -> None:
    ledger: Path = tmp_path / "spend.jsonl"
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"b64_json": "a"}]})
    with _image_client(ledger, handle) as http_client:
        resp: httpx.Response = http_client.post(f"{BASE}/images/generations", json={"model": IMAGE_MODEL, "prompt": "draw"})
    assert resp.status_code == 200
    assert spent_usd(ledger) == pytest.approx(0.01)


@pytest.mark.parametrize("payload", [{}, {"data": "nope"}, {"data": None}, {"unexpected": []}])
def test_image_unreadable_data_records_worst_case(tmp_path: Path, payload: dict[str, Any]) -> None:
    ledger: Path = tmp_path / "spend.jsonl"
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)
    with _image_client(ledger, handle) as http_client:
        resp: httpx.Response = http_client.post(
            f"{BASE}/images/generations",
            json={"model": IMAGE_MODEL, "prompt": "draw", "n": 3},
        )
    assert resp.status_code == 200
    assert spent_usd(ledger) == pytest.approx(3 * 0.01)


def test_image_failed_response_records_nothing(tmp_path: Path) -> None:
    ledger: Path = tmp_path / "spend.jsonl"
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom", "data": [{"b64_json": "a"}]})
    with _image_client(ledger, handle) as http_client:
        resp: httpx.Response = http_client.post(f"{BASE}/images/generations", json={"model": IMAGE_MODEL, "prompt": "draw", "n": 2})
    assert resp.status_code == 500
    assert spent_usd(ledger) == 0.0


def test_image_blocked_when_worst_case_exceeds_limit(tmp_path: Path) -> None:
    ledger: Path = tmp_path / "spend.jsonl"
    seen: dict[str, int] = {}
    def handle(request: httpx.Request) -> httpx.Response:
        seen["n"] = 1
        return httpx.Response(200, json={"data": [{"b64_json": "a"}]})
    with _image_client(ledger, handle, limit=0.015) as http_client:
        resp: httpx.Response = http_client.post(f"{BASE}/images/generations", json={"model": IMAGE_MODEL, "n": 2})
    assert resp.status_code == 402
    assert seen.get("n", 0) == 0
    assert spent_usd(ledger) == 0.0


def test_image_edits_stays_refused(tmp_path: Path) -> None:
    assert refusal_reason("/v1/images/edits", {"model": IMAGE_MODEL}) is not None
    ledger: Path = tmp_path / "spend.jsonl"
    seen: dict[str, int] = {}
    def handle(request: httpx.Request) -> httpx.Response:
        seen["n"] = 1
        return httpx.Response(200, json={"data": [{"b64_json": "a"}]})
    with _image_client(ledger, handle) as http_client:
        resp: httpx.Response = http_client.post(f"{BASE}/images/edits", json={"model": IMAGE_MODEL})
    assert resp.status_code == 402
    assert seen.get("n", 0) == 0
    assert spent_usd(ledger) == 0.0


def test_image_model_on_responses_stays_refused(tmp_path: Path) -> None:
    body: dict[str, Any] = {"model": IMAGE_MODEL, "max_output_tokens": 50, "input": "hi"}
    assert refusal_reason("/v1/responses", body) is not None
    ledger: Path = tmp_path / "spend.jsonl"
    seen: dict[str, int] = {}
    client: openai.OpenAI = _make_openai(ledger, _ok_handler({"input_tokens": 1, "output_tokens": 1}, seen))
    with pytest.raises(openai.APIStatusError) as exc:
        client.responses.create(model=IMAGE_MODEL, input="hi", max_output_tokens=50)
    assert exc.value.status_code == 402
    assert seen.get("n", 0) == 0
    assert spent_usd(ledger) == 0.0
