Implement stage 8, part B: it says what matters, and it never fails silently.

Two long real talks showed this. In 46 sentences the AI spoke 6 times, and all six were process lines: pull back, "I'm on it", and closing. The conductor did notice a real conflict, recording "十小时变二十小时" in `add_contradictions`, and said nothing. And when a key is wrong or the network is down, a person on a black screen hears nothing at all and keeps talking into the void. The person cannot see the screen, so whatever is wrong has to be heard.

Silence stays the default. This adds one rare, valuable interruption, one rare status line, and honest failure messages.

Return the full content of exactly these files: `app/conductor.py`, `app/prompts.py`, `app/messages.py`, `app/asr.py`, `app/realtime.py`, `tests/test_speaking.py` (new). Keep every behaviour you are not asked to change. Do not rewrite unrelated code. Do not edit existing tests.

## 1. A changed fact gets one question, when it happens
`TURN_SCHEMA` gets a new required string field `conflict_question`.

Add to `TURN_SYSTEM_PROMPT`, in the same style: `conflict_question` is normally the empty string. Fill it only when `current_user_text` states a fact (a number, time, date, duration, amount, person, place, or chosen option) that differs from what the same user said earlier in `history` or `state`, and the user did not point out the change themselves. A person saying "I said twenty earlier but actually thirty" pointed it out, so leave it empty. A person who said "每周只有十个小时" and later says "一周至少二十个小时" did not, so fill it. A tension between two wishes is not a changed fact, so "想赚钱又怕做不完" stays in `add_contradictions` only. The question is one short spoken sentence in the user's language that names both values and asks which holds, for example "你刚说每周十小时，现在说二十，按哪个算？" or "You said ten hours a week, now twenty. Which one?".

In `app/conductor.py`:
- After parsing a turn, if `conflict_question` is non-empty, reply is not suppressed, and the model's action is `listen`, `follow_up`, or `continue`, consider asking it. The model's flag decides this, not its `action`.
- Ask only if fewer than `BLACKOUT_MAX_CONFLICT_QUESTIONS` (default 3) were asked this session, and the same question, compared with `state.clean_text`, was not asked before.
- Asking means `action = "follow_up"`, `reply` is the question run through `truncate_reply`, and `reason` is a short fixed label: "前后不一致" or, in English, "Changed fact". Count it in `record["stats"]["conflicts_asked"]`, and store the asked text in `record["asked_conflicts"]`, a list. The speaking gap in section 2 still applies.
- If the speaking gap has not passed, keep the question in memory as pending for up to 45 seconds and ask it on the first later turn where the gap has passed and that turn has no reply of its own. A pull-back, an answer, or a task acknowledgement always wins over a pending question. Drop it after 45 seconds.
- A question is never asked on a turn that ends the session.

## 2. One status line after a long quiet stretch
The existing guidance about reflecting after about 8 quiet turns did not fire once. Make it a rule of the server.
- A reflection is due when at least `BLACKOUT_REFLECT_TURNS` (default 10) user turns have passed since the AI last spoke, and at least `BLACKOUT_REFLECT_SECONDS` (default 150) have passed since the later of the AI's last speech and the session's first turn in this process.
- Add `reflect_due` to the turn input. In the prompt: when `reflect_due` is true and the user has just finished a thought rather than being in the middle of a list, use `action=continue` with one spoken line saying what is decided and what is still open, at most 40 characters in Chinese or 16 words in English, using only what was actually said.
- If `reflect_due` is true and the model still returned `listen` with no conflict question and no task, the server builds the line itself from `state`: the most recent decision and the first open question, falling back to the first unexpanded point. In `messages.py`: `reflect_both` "现在定了{decision}，还没定{open}。" / "So far: {decision}. Still open: {open}.", `reflect_decision` "现在定了{decision}。" / "So far: {decision}.", and `reflect_open` "还没定{open}。" / "Still open: {open}.". If `state` has neither, say nothing and do not count it as a reflection.
- After any reflection, the count starts again. Count it in `record["stats"]["reflections"]`. A `suppress_reply` turn or an ending turn never reflects.

## 3. Failures are heard
Replace the second element returned by `_call_model_with_retry` with a failure kind, one of `None`, `"budget"`, `"key"`, `"credits"`, or `"network"`. Keep `is_budget_error` behaviour: HTTP 402 is `budget`. Status 401 or 403 is `key`. Status 429 whose error body or message mentions quota, credit, billing, or insufficient is `credits`. Anything else is `network`. `key` and `credits` are not retried. Only a class name and status code are logged for these, never exception text.

The turn still saves the person's words, with `action` `listen`, exactly as now. Add to the result `ai_failed`, the kind or an empty string. Speech, through the normal `reply` field:
- `key`: on the first failure, then at most once every 120 seconds, `key_rejected`.
- `credits`: the same timing, `credits_out`.
- `network`: on the second failure in a row, then at most once every 120 seconds, `ai_unreachable`.
- The first successful turn after a spoken failure message replies `ai_back` if the turn has no reply of its own.
- `budget` keeps its current behaviour.

`messages.py` additions:
- `key_rejected`: "Meta 不接受现在的 key，AI 暂时帮不上忙。你说的话还在记录，说结束可以先看原话。" / "Meta rejected the key, so the AI can't help right now. Your words are still being recorded. Say stop to see them."
- `credits_out`: "你的 Meta 账户额度不够了，AI 暂时帮不上忙。你说的话还在记录。" / "Your Meta account is out of credit, so the AI can't help right now. Your words are still being recorded."
- `ai_unreachable`: "我暂时连不上 AI。你说的话还在记录，可以继续说。" / "I can't reach the AI right now. Your words are still being recorded, so keep going."
- `ai_back`: "连上了。" / "I'm back."
- `asr_key_rejected`: "Meta 不接受现在的 key，我听不到你。请按 Esc，然后换一个 key。" / "Meta rejected the key, so I can't hear you. Press Escape and change the key."

`clear_memory` clears all the new in-memory state.

## 4. The speech connection names a rejected key
In `app/asr.py`, `connect` sets `self.auth_failed = True` when the first message of the handshake is an error whose text contains "Unauthorized", or when the socket closes with code 1008 during the handshake, and returns False as now. Start with `self.auth_failed = False`. Do not log the handshake or the upstream text.

In `app/realtime.py`, where the upstream connection fails, or closes with 1008 before audio started flowing, and `auth_failed` is true, call `_send_fallback(message(language, "asr_key_rejected"))` instead of the generic fallback. Nothing else changes.

## `tests/test_speaking.py` (new)
Follow how `tests/test_conductor.py` fakes the model: it replaces `conductor._call_model_once`. Cover:
- A turn with `conflict_question` and action `listen` becomes `follow_up` with that reply, and increments the counter.
- The same question twice is asked once. A fourth distinct question is not asked.
- Inside the speaking gap the question is held, asked on a later eligible turn, and dropped after 45 seconds. A pull-back on that turn wins over it.
- It is not asked on a suppressed turn or an ending turn.
- A reflection is not due before the thresholds. Once due, the model's `continue` line is spoken. With `listen`, the server's line is built from `state` in the session's language. With an empty state, nothing is said. The count starts again afterwards.
- Failure kinds: a fake exception with status 401 gives `key` with no retry, 429 with "insufficient_quota" gives `credits`, a plain exception gives `network`, and 402 gives `budget`.
- Speech timing: `key_rejected` on the first failure and not again within 120 seconds, `ai_unreachable` on the second failure and not the first, and `ai_back` after recovery. The person's words are in `history` in every case.
- `AsrStream.connect` against a fake websocket that sends an Unauthorized error sets `auth_failed`.
