A real voice run and a probe found that a changed fact is asked about too late. Fix the timing. Return the full content of exactly these files: `app/conductor.py`, `app/prompts.py`, `tests/test_speaking.py`, `tests/evals/run_evals.py`, `docs/demo_talk.json`. Change only what is listed.

## 1. Ask about a changed fact while it still matters
A probe ran the same lines twice. Both times the model flagged "You said three on support, now five. Which one?" on the right turn. Both times the server held it back because the AI had spoken less than 20 seconds earlier, then asked it on the next turn, right after the person had already said "Right, it's three". In the recorded voice run it came after "Stop.". A question asked after the answer sounds broken.

- A conflict question has its own, shorter gap: `BLACKOUT_MIN_CONFLICT_GAP`, default 6 seconds since the AI last spoke, instead of the 20-second gap for other unasked-for speech. Everything else about the 20-second gap stays.
- When a question is held, it is not asked blindly on a later turn. The next turn's input includes `pending_conflict_question` with its text. Add to `TURN_SYSTEM_PROMPT`: when `pending_conflict_question` is set, and `current_user_text` or the latest history already settles which value holds, leave `conflict_question` empty; if it is still unsettled, copy it into `conflict_question`. The server then asks it only if the model returned it again, using the normal rules. If the model returned it empty, the held question is dropped. It is still dropped after 45 seconds, and never asked on an ending turn.
- Add `pending_conflict_question: Optional[str] = None` to `build_turn_user_content` in `app/prompts.py`, included in the JSON only when set.

Update `tests/test_speaking.py` to match: a held question is asked on a later turn only when the fake model returns it again, is dropped when the fake model returns an empty one, and a conflict question 7 seconds after the AI spoke is asked at once, while one 4 seconds after is held. Keep all other tests in that file.

## 2. `tests/evals/run_evals.py`
- `_markdown` reads `t['conflicts']['asked']`, but `_totals` stores that count under `hit`. Use `hit`, so the run no longer crashes after all the talks.
- Add `--from-json` to rebuild `docs/evals.md` from an existing `docs/evals.json` without running any talk.
- The Markdown also states the average cost per talk.
- In the per-talk table, "Draft done" shows "yes", "no", or "yes, unasked" when a draft finished for a talk with `must_draft` false.

## 3. `docs/demo_talk.json`
The search answer is spoken about 16 seconds after the request, and must not land on top of the changed-fact beat. Set `pause_after` to 8 on the line "Please look up what time of day launch emails get the most opens." and to 8 on "The announcement should be short and clear.". Change nothing else in that file.
