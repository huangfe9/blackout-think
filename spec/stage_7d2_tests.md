Bring the tests up to date with stage 7: per-browser ownership, English, and the new start page. Do not change anything under `app/`. If a test exposes a real defect, leave it failing and describe the defect in a comment at its top. Do not weaken what tests check.

Return the full content of exactly these files: `tests/test_language.py` (new), `tests/test_state.py`, `tests/test_conductor.py`.

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
Update `tests/test_state.py` and `tests/test_conductor.py` for the changes above, keeping their coverage.
