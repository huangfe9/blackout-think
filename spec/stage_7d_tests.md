Bring the tests up to date with stage 7: per-browser ownership, English, and the new start page. Do not change anything under `app/`. If a test exposes a real defect, leave it failing and describe the defect in a comment at its top. Do not weaken what tests check.

Return the full content of exactly these files: `tests/conftest.py`, `tests/test_owner.py` (new), `tests/test_language.py` (new), `tests/test_routes.py`, `tests/test_security.py`, `tests/test_static.py`, `tests/test_state.py`, `tests/test_conductor.py`.

## `tests/test_owner.py`
Two separate `TestClient` instances are two browsers.
- A first request sets a `blackout_owner` cookie with HttpOnly and SameSite=Lax, and Secure when using `https://`. The stored owner is a hash and is not the cookie value. A malformed cookie is replaced.
- A session created by one client is listed for that client and not for the other. A client with no cookie gets an empty list.
- For another client, every route on that session returns the same 404 envelope as a missing session: read, live, announcements, turns, text-turns, finish, poster GET and POST, sketches, and delete. No model call or spend happens, checked with fakes.
- A WebSocket from another client, or with no cookie, closes with 1008, and no upstream connection is opened on the fake server.
- The owner's own WebSocket works.
- A session with no owner, saved earlier, is never listed for anyone and remains reachable by its exact id.
- No response body contains `owner` or the cookie value. Session files on disk do not contain the raw cookie value.
- `/api/status` gives `spent_usd` to a loopback client only.

## `tests/test_language.py`
- `split_end`: OK, stop. and Stop. and I'm done. end with no content. first idea, ok, stop ends with the content first idea. That part is done. and I want to stop using the old design. do not end. Chinese cases still hold.
- `speech_language` and `recent_language`.
- `message()` for every key in both languages, with falling back to `zh`.
- A conductor turn with English text uses English fixed sentences for the task acknowledgement, confirmation, and limit; with Chinese text it uses Chinese.
- `nudge_text` follows the most recent language, and does not split a Latin word when shortening.
- `AsrStream` handshake `languageBias` order follows the language, using the fake server.
- Markdown headings follow `result["language"]`.
- `POST /api/sessions` stores `language`, and an invalid value becomes `zh`.

## Fix the existing tests
- `tests/test_static.py`: `sample_poster.jpg` is gone. `how_it_works_zh.jpg` and `how_it_works_en.jpg` exist and are served as `image/jpeg`. No static file mentions 周末 or `demo` in user-visible text. `i18n.js` has the same keys for `zh` and `en`, checked by parsing the table. `index.html` still contains no inline script or style.
- `tests/test_routes.py`, `tests/test_security.py`, `tests/test_state.py`, `tests/test_conductor.py`: update for the changes above, keeping their coverage. `conftest.py` keeps its protections, and does not let any test touch the real ledger.
