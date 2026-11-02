The last response fixed the bridge but returned no tests and did not change `budget.py`. Do only that now.

Return exactly these files, each with full content: `budget.py`, `test_budget.py`, `tests/fake_asr.py`, `tests/test_realtime.py`, `tests/test_security.py`, `tests/test_conductor.py`, `tests/test_summary.py`. Do not change anything under `app/`. If a test exposes a real defect in `app/`, do not hide it: write the test anyway and describe the defect in a comment at the top of that test.

## budget.py
Add `WEB_SEARCH_WORST_CASE_QUERIES: int = 10` and use it in `worst_case_usd`: when a `web_search` tool is present, add that number times the per-query price, regardless of how many tool entries there are. `refusal_reason` allows `web_search` only when `path` is `/v1/responses`, and otherwise refuses with the existing search message. Keep everything else.

## test_budget.py
Add: the worst case with `web_search` includes ten queries; `web_search` is refused on `/v1/chat/completions`; queries in a response are charged; the real `can_spend` with a temporary ledger, under and over the limit and with a corrupt ledger.

## tests/test_realtime.py
`ws.receive_json()` blocks forever when nothing arrives. Add a helper that receives on a daemon thread with a timeout and fails with a clear message, and use it for every receive. The file must finish in under 30 seconds in total.

Add a test for each behaviour:
1. After a 1011 close and reconnect, new browser frames reach the new fake connection (pacing is per connection).
2. A server that refuses every reconnect ends in `fallback`. A server that accepts and then immediately closes also ends in `fallback`, proving attempts are not reset by a short-lived connection.
3. `speechComplete` for 上一句 arrives during a slow fake conductor call, then 结束 arrives: `end` is sent with reason `phrase`, the conductor saw 上一句 and 结束 as separate calls, and 结束 was never joined to other text.
4. With no browser frames the fake server receives roughly real-time bytes from the silence pump. With browser frames at real time, the pump adds almost nothing.
5. A reply queued before a new `speechStart` is discarded at delivery, and an announcement queued the same way is still delivered afterward.
6. Announcements and nudges reach `conductor.note_spoken`, and `stats.nudges` increments.
7. Connecting to a finished session sends `end` and never opens an upstream connection.
8. `tts_started` with no `tts_finished` for longer than the stuck limit stops blocking delivery. Make the limit configurable through an environment variable or monkeypatch so the test is quick.
9. After `end` or `fallback` the browser socket is closed by the server.
10. Budget check using the real `budget.can_spend` with a temporary ledger, through monkeypatching `budget.LEDGER_FILE` or an equivalent, not a mock of `can_spend`.
11. Real-key check: no message sent to the browser contains the key, and `caplog` output contains neither the key nor any transcript text.

## tests/test_security.py
`test_token_flow`: use `TestClient(app, base_url="https://testserver")`, because the cookie is `Secure` and the implementation is right. Add: a non-ASCII token returns 401 rather than an error. The `x-access-token` header and `Authorization` header do not grant access.

## tests/test_conductor.py
Add tests for `note_spoken`: history, `stats.nudges`, and the speaking gap, and for a finished session returning `end: true` without changing the record.

## tests/test_summary.py
Add: a model list longer than the state's list falls back to the state's list, covering decisions, todos, and open questions.
