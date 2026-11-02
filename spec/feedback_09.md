Review of stage 2 found the defects below. Five tests fail and some of the worst defects have no test at all. Fix everything here. Return the full content of every changed file.

`app/realtime.py` is 552 lines, over the 400-line limit. Split the upstream connection into `app/asr.py` with a class `AsrStream` that owns the connection, handshake, event iteration, pacing, and byte counts. `realtime.py` keeps the bridge.

## Critical: bridge logic
1. **All audio dropped after a reconnect.** `_forward_audio` compares the lifetime `forwarded_bytes` against `elapsed` from a `started` that is reset on reconnect, so after any reconnect `projected` is far ahead and every frame is dropped forever. Pacing must be per upstream connection, with its own start time and byte count, reset on connect. `forwarded_bytes` for billing stays lifetime. Test: after a 1011 reconnect, new frames reach the new fake connection.

2. **Silent hang when a reconnect fails.** In `_upstream_supervisor`, when `_connect_upstream` fails with attempts below 3, the loop goes back to the top, sees `upstream is None`, sleeps, and repeats forever without retrying. Restructure as one clear loop: run the stream, and on a retryable close try to reconnect with backoff 1, 2, 4 seconds; after 3 consecutive failures send `fallback`. Reset the attempt count only after a connection has stayed up for at least 30 seconds, otherwise a server that accepts and immediately closes causes an endless loop. Treat an unexpected close with 1000 while the session is active as retryable. Test: a server that refuses every reconnect ends in `fallback`; a server that accepts then closes immediately also ends in `fallback`.

3. **"结束" while the model is thinking does nothing.** The worker joins queued text with newlines, so `"上一句\n结束"` is not an exact end phrase and the session does not end. In the worker: separate parts that are end phrases from the rest; process the rest as one turn; then, if any part was an end phrase, process it on its own and send `end`. Same for a lone confirmation while awaiting an end confirmation. Test: `speechComplete` for 上一句 during a slow fake model call, then for 结束, results in `end` being sent, with both recorded.

4. **Upstream starves before audio starts.** The browser only starts capture after `ready`, and a microphone permission prompt can take many seconds. The upstream closes streams that stop sending audio or fall below real time. Add a silence pump to `AsrStream`: from the moment the stream is acknowledged, a task checks every 100 ms, and if the stream is more than 0.4 seconds behind real time it sends zeroed PCM to bring it to 0.2 seconds behind. This also covers browser stalls and hidden-tab throttling. Pump bytes count as forwarded for billing, because they are billed. Test: with no browser frames, the fake server receives approximately real-time bytes; with normal browser frames, the pump adds almost nothing.

5. **Wrong call to the spending check.** Verify every call to `budget.can_spend` matches its signature. If the function requires `usd`, the call with no arguments raises `TypeError`, which the outer handler swallows, so a real session could never start. Pass a small amount such as `TRANSCRIBE_WORST_CASE_USD`, or give the parameter a default, and add a test using the real `budget.can_spend` with a temporary ledger rather than a mock.

6. **`inspect.signature` hack.** `_call_conductor` guesses the argument count, which is why mocks get called wrongly and tests fail. Always call `conductor.process_speech(session_id, text, time.time())`. Fix the tests' fakes to accept three arguments. Remove the `test-key` fallback in `_connect_upstream`: a missing key means `fallback`.

## High
7. **Stale reply at delivery.** A reply can sit in `say_queue` while the user starts talking. Record the `speech_start_counter` when queuing. At delivery, discard a `reply` if the counter changed. Do not discard `announcement` kinds.

8. **Spoken text not recorded.** Nudges and announcements do not reach `stats`, history, or the speaking gap. Add `conductor.note_spoken(session_id, text, kind, now)`, which under the lock appends to history as `assistant` for announcements and nudges, increments `stats.nudges` for nudges, and updates `_last_spoke`. Call it with `asyncio.to_thread` after delivery. Test it.

9. **Finished session.** If the record is already finished on connect, send `end` with reason `phrase` and close, without opening an upstream connection.

10. **Stuck playback.** If `tts_playing` stays true for 30 seconds with no `tts_finished`, clear it, so one lost message cannot stop all delivery and nudges.

11. **Closing the browser socket.** After `end` or `fallback`, close the browser socket with 1000 rather than letting the handler return without closing. Serialize sends to the browser with an `asyncio.Lock`, because several tasks send.

12. **Audio compression.** Open the upstream with `compression=None`. PCM does not compress well and this costs CPU on every frame.

## High: security
13. `hmac.compare_digest` raises `TypeError` on non-ASCII `str` input, so a crafted token returns a 500. Compare encoded bytes. Remove the `x-access-token` and `Authorization` token sources; the spec only allows the query parameter and the cookie. Move `import json` to the top of the module. Test: a non-ASCII token returns 401.

14. `test_token_flow` fails because the cookie is `Secure` and the test client uses `http://testserver`. The implementation is right. Use `TestClient(app, base_url="https://testserver")` in that test.

## Medium
15. In `app/summary.py`: a model that adds items violates "nothing new may be added". A live run invented an open question from a contradiction. If the model's `decisions`, `todos`, or `open_questions` list is longer than the state's list, use the state's list instead. Add a test. Merging is still allowed because it only makes a list shorter.

16. In `app/tasks.py`: the search `detail` sometimes begins with a leftover label such as "细节是". Tell the search prompt to write details as plain sentences with no label.

17. Remove the module-level aliases `bridge_websocket` and `websocket_handler`, and the empty `finally: pass` in `_cleanup`.

18. In `budget.py`: the worst case counts one query per `web_search` tool, but one call can run several queries. Add `WEB_SEARCH_WORST_CASE_QUERIES = 10` and use it in `worst_case_usd`. `refusal_reason` must allow `web_search` only when `path` is `/v1/responses`, and refuse it on `/v1/chat/completions`. Add tests for both. Item 5 above can be closed: `can_spend` has a default argument, so keep it, and add only the test using the real function.

## Tests must be fast and cannot hang
`ws.receive_json()` blocks forever when nothing arrives, which made the failing tests take over a minute each. Write a helper in `tests/test_realtime.py` that receives on a daemon thread with a timeout and fails clearly. `tests/test_realtime.py` must finish in under 30 seconds in total. All tests must pass.
