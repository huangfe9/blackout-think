Implement stage 7, part B: the backend speaks English as well as Chinese. Judges may not read Chinese. The AI must answer in the language the person speaks.

Return the full content of exactly these files: `app/messages.py` (new), `app/state.py`, `app/conductor.py`, `app/tasks.py`, `app/summary.py`, `app/poster.py`, `app/asr.py`, `app/realtime.py`, `app/routes.py`, `app/prompts.py`. Keep lines under 120 characters, with one statement per line. Keep all existing Chinese behaviour exactly as it is.

## `app/messages.py`
`MESSAGES: dict[str, dict[str, str]]` and `message(language, key, **values) -> str`, falling back to `zh`. Move every fixed sentence the server speaks here, with these keys and English:
- `task_ack`: "OK, I'm on it. Keep going."
- `confirm_end`: "Want to finish? Just say stop."
- `end_reply`: "OK, let me pull this together."
- `task_limit`: "That's a lot of background work for one session, so I'll note that as a question."
- `nudge_point`: "You haven't finished with {point}. Still thinking?"
- `nudge_generic`: "Still there? If you're stuck, try saying the smallest question."
- `found`: "Found it: {conclusion}"
- `draft_done`: "The draft is ready. It's on your result page."
- `task_failed`: "That didn't work. I noted it on your result page."
- `budget`: "The budget is used up, so I can't continue."
- `fallback`: "Automatic listening stopped. Press space to start talking, and press it again when you finish."
- `poster_failed`: "Couldn't draw the picture. Please try again."
- `poster_budget`: "The budget is used up, so the picture wasn't drawn."
- `default_title`: "Blackout result"

## `app/state.py`
- `speech_language(text) -> str`: `zh` if the text has any CJK character, otherwise `en`.
- `recent_language(record) -> str`: the language of the most recent user utterance, otherwise `record["language"]`, otherwise `zh`. Fixed sentences use this, so the app answers in the language actually being spoken.
- End phrases in English, compared in lowercase with punctuation and spaces removed: stop, end, finish, done, imdone, thatsall, thatsit, weredone, letsstop, letsend, wrapup. English leading fillers: ok, okay, alright, so, yes. English confirmations: yes, yeah, yep, ok, okay, sure, right.
- `split_end` splits clauses on Chinese and Western punctuation, including a period, a comma, and a question mark. "That part is done." does not end. "OK, stop." ends. "I want to stop using the old design." does not end. "Stop." ends. "I'm done." ends. A long sentence that merely contains one of the words does not end.
- In `conductor`, the rule that a model `summarize` ends straight away if the text contains 结束 or 停止 also applies to the English words `stop` and `finish` as whole words.

## `app/prompts.py`
- `TURN_SYSTEM_PROMPT`: strengthen the rule: `reply`, `reason`, and every addition are in the language of `current_user_text`. Add one worked example in English: "By the way, I want hot pot tonight" during a technical discussion is `pull_back`, with the reply "Noted for later. Back to the plan."
- `SEARCH_SYSTEM_PROMPT` and `DRAFT_SYSTEM_PROMPT`: answer in the language of the instruction. `SKETCH_SYSTEM_PROMPT`: use the language of the goal.
- `FINAL_SYSTEM_PROMPT`: everything, including the summary and poster text, is in the `language` it chooses.

## `app/summary.py`
Markdown headings and the labels come from a table by `result["language"]`. English: Decisions, To do, Parking lot, Still open, Contradictions, Unfinished, Looked up and drafted, Paper sketch, Outline, Goal. The default title and the degraded path use the record's recent language.

## `app/tasks.py`, `app/conductor.py`, `app/poster.py`
Use `message()` with `recent_language(record)` for every fixed sentence. `nudge_text` uses it too. Keep the point truncation rule. Do not split a Latin word when shortening a point: cut at a space when one exists.

## `app/asr.py`, `app/realtime.py`
`AsrStream` takes a `language`. `languageBias` is `["Mandarin Chinese", "English"]` for `zh` and `["English", "Mandarin Chinese"]` for `en`. The bridge passes the record's language. The fallback message uses `message()`. The echo logic stays as it is.

## `app/routes.py`
`/api/sessions/{id}/turns` passes the matching language order to `transcribe_wav`, from the record's language. `POST /api/transcribe` takes an optional `?language=en` query parameter for the same purpose.
