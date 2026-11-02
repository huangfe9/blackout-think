Write the tests for stage 6. Do not change anything in `app/` or `budget.py`. If a test exposes a real defect, leave it failing and describe the defect in a comment at its top. No test may touch the real ledger or make a network call; `tests/conftest.py` already protects this.

Return the full content of exactly these files: `tests/test_poster.py` (new), `tests/test_summary.py`, `tests/test_routes.py`, `tests/test_static.py`, `test_budget.py`.

## `tests/test_poster.py`
- `build_poster_prompt`: Chinese and English versions include the fixed style sentence, the title, every item exactly, the exact-text rule at the end, and no newlines from user text. An unknown block type falls back to a list.
- `start_poster` sets status `drawing` and saves; a second call while drawing returns false; the attempt limit from `BLACKOUT_MAX_POSTERS_PER_SESSION` is respected.
- The worker, with a fake client: valid PNG bytes are saved and status becomes `done` with `version` incremented; bytes that are not a PNG are refused and status becomes `failed`; invalid base64 fails; a 402 gives the budget message; a request has search tools turned off in `extra_body`, `n=1`, and `size="1536x1024"`.
- A session deleted during drawing leaves no file.
- `delete_session` removes the poster file. A poster still `drawing` on load becomes `failed`.

## `tests/test_summary.py`
Update `test_verbatim_fields` for the new behaviour. Add:
- `valid_from_numbers`, `clean_items`, and `clean_nodes`: out-of-range and non-integer citations are ignored; an item with no valid citation is dropped; a group node without citations stays only if it has children.
- `build_clean_map`: nesting, unknown parents go to the root, cycles neither hang nor lose a node, the cap of 60.
- `finish` with a fake model: `summary`, `language`, the clean `map`, `evidence` mapping each item to its quoted utterances, and `transcript` are present. Parking lot and tasks stay verbatim. If a list ends up empty while the state's list is not, the state's list is used.
- An invented item with no citation does not appear.
- A poster starts once when the brief has items, and `finish` does not wait for it. A second `finish` with no changes starts nothing. A degraded result starts no poster. A session with no utterances makes no model call.
- Markdown begins with the title and summary and contains the 思路 section.
- If the model fails, the result is degraded, with an empty summary and the map from the state.

## `tests/test_routes.py`
- `GET /api/sessions/{id}/poster`: 404 in the envelope when there is none; the PNG with `Cache-Control: no-store` when present; 404 for an invalid id.
- `POST /api/sessions/{id}/poster`: 409 when already drawing and when there is no brief; 429 at the limit; success starts drawing. Use a fake for the worker so nothing is drawn.
- Keep the rest passing.

## `tests/test_static.py`
- `sample_poster.jpg` exists and is served as `image/jpeg`.
- `index.html` states what the product does, containing 不看屏幕 and 关灯，开始说.
- The start page and result page have no text saying 花费 or a dollar amount.

## `test_budget.py`
- `/v1/images/generations`: allowed for `muse-image-1.0` with `n` absent or from 1 to 4; refused for another model, for `n` of 0 or 5 or a non-integer, and for `stream`; no `max_output_tokens` needed. The worst case is `n` times $0.01. On success the number of `data` entries times $0.01 is recorded; unreadable data records the worst case; a failed response records nothing.
- `/v1/images/edits` stays refused. `muse-image-1.0` on `/v1/responses` stays refused.
