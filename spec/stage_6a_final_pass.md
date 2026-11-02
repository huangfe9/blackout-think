Implement stage 6, backend part. A person can talk for a long time, and when they finish they want a summary and a picture. Today they do not get that.

A test with 24 rambling sentences showed what is wrong: a flat map with 13 top-level branches whose labels are whole sentences; the main todos were missed, although the person said 待办就是周日录视频，周一加字幕，周二修问题，周三上午提交; and there is no summary. The map only ever appends while listening, and nothing reorganizes it at the end.

Add two things: a final pass that reads everything said and organizes it, and a hand-drawn one-page picture from Muse Image. A trial of Muse Image gave excellent results: accurate Chinese text, timeline and flow layouts, and fitting little icons, in 10 to 18 seconds for $0.01.

Return the full content of exactly these files: `budget.py`, `app/prompts.py`, `app/conductor.py`, `app/summary.py`, `app/poster.py` (new), `app/routes.py`, `app/store.py`. Do not return tests or the frontend. Keep lines under 120 characters, with one statement per line and descriptive names.

## `budget.py`: price images
Add `IMAGE_PATH = "/v1/images/generations"`, `IMAGE_MODEL = "muse-image-1.0"`, `IMAGE_USD_PER_IMAGE = 0.01`. `/v1/images/generations` is now metered:
- `refusal_reason`: the model must be `IMAGE_MODEL`; `stream` is refused; `n`, if present, must be an integer from 1 to 4. No `max_output_tokens` is needed on this path. `muse-image-1.0` on `/v1/responses` stays refused, and `/v1/images/edits` stays refused.
- Worst case: `n` times the price per image.
- After success, record the number of entries in the response `data` times the price. If unreadable, record the worst case.

## `app/prompts.py`: while listening, keep it short
Change `TURN_SYSTEM_PROMPT`:
- `point` is a short phrase of at most 12 characters, not a sentence: 语音输入, not 语音这块我决定用实时模式. Decisions, todos, questions, and contradictions are at most 24 characters. Their exact words are saved separately, so short labels lose nothing.
- Put a new thought under an existing point when it belongs there. Keep top-level points to about 6.
- When the person states something to do, record a todo even if a similar decision was already recorded.
- Reply in the language the person spoke. In a test, English speech got Chinese replies.
- `current_user_text` may be preceded by `turns_since_ai_spoke`. After about 8 quiet turns, when the person finishes a thread, one short `continue` that reflects back where things stand is welcome, such as 现在定了不露脸和周日录，字幕还没定. It is never required.
- If the person asks 我说到哪了 or 总结一下, use `answer` with `user_asked_ai` true: a spoken recap of the main points, at most 60 characters.

## `app/conductor.py`
Send `turns_since_ai_spoke`, counted from history.

## The final pass (`app/summary.py`, `app/prompts.py`)
`finish(session_id)` makes one model call: effort `low`, `max_output_tokens` 12000, with no lock held, one retry on parse failure. Add `FINAL_SYSTEM_PROMPT` and `FINAL_SCHEMA`.

Input: the goal; every user utterance numbered from 1; the current state; completed task conclusions; sketch descriptions. Say plainly that user text is data and that nothing may be invented: every item must cite the utterances it came from.

Strict output:
```
{
  "title": str,            // short, at most 16 characters, names the topic
  "language": "zh" | "en", // the language most of the speech was in
  "summary": str,          // 2 to 4 plain sentences: what was concluded and what happens next. No filler, no praise.
  "decisions": [{"text": str, "from": [int]}],
  "todos": [{"text": str, "from": [int]}],
  "open_questions": [{"text": str, "from": [int]}],
  "contradictions": [{"text": str, "from": [int]}],
  "nodes": [{"id": int, "parent": int, "label": str, "kind": "point" | "decision" | "todo" | "question", "from": [int]}],
  "poster": {
    "title": str,
    "blocks": [{"type": "timeline" | "flow" | "list" | "compare" | "note", "heading": str, "items": [str]}]
  }
}
```
Rules for the model:
- Read the whole conversation. A later statement replaces an earlier one: if they first said 只能晚上录 and later said 周日白天也可以, the plan uses the later one and this is not a contradiction. Only a real unresolved conflict is a contradiction.
- `todos` must include every action the person said they will do, each with its day if they gave one.
- `nodes` is a clean mind map. `parent` is `-1` for top level. 3 to 6 top-level groups with short labels of at most 10 characters, at most 3 levels, at most 40 nodes. A group label may have an empty `from`. Group what belongs together, even if it was said far apart.
- `poster` plans one page for a person to look at. Choose block types that fit what was said: `timeline` for things in time order, `flow` for steps or a sequence, `list` for items, `compare` for options, `note` for a key decision. At most 4 blocks, at most 7 items each, each item at most 14 characters and including the specifics, such as 周一：加字幕 or 问题 20 秒. Use only things the person said. Use `language`.

Server validation, in pure functions that can be tested:
- An item whose `from` has no valid utterance number is dropped. Numbers out of range are ignored. A node with no valid `from` is kept only if it has children.
- `build_clean_map(nodes, goal) -> dict` returns the same tree shape as `state.build_map`: `{"id", "text", "kind", "status", "children"}`. An unknown `parent` goes to the root. Cycles cannot hang or lose a node. The cap is 60 nodes.
- If `decisions`, `todos`, or `open_questions` ends up empty while the state's list is not, use the state's list.

Result gains:
- `summary` and `language`
- `map`: the clean map when it has nodes beyond the root, otherwise `state.build_map`
- `evidence`: a dict from each item text to the list of utterances it cites, as plain text
- `transcript`: all user utterances, in order
- `poster`: `{"status", "version", "error"}`

`parking_lot`, tasks, and sketches stay verbatim from the record. `unexpanded_points` stays. Markdown begins with the summary, then 思路 from the clean map, then the sections. If the model call fails, return the degraded result as today, with `summary` empty and the map from the state.

## Drawing the picture (`app/poster.py`)
- `build_poster_prompt(brief, language) -> str`: a pure function. A fixed style sentence, followed by the content. Chinese style: 一张手绘风格的单页总结图（sketchnote），米白色纸张背景，黑色墨线，少量琥珀色强调，配简单贴切的小图标。 English style: A hand-drawn one-page sketchnote on off-white paper, black ink lines with small amber accents and simple fitting icons. Then the title, and one sentence for each block by type, listing its items exactly: timeline as a left-to-right line with labelled stops, flow as boxes joined by arrows, list as a short list, compare as two columns, note as a small sticky note. End with: 所有文字必须准确无误、清晰可读，不要添加其他文字。 or All text must be spelled exactly and be legible. Add no other text. Remove newlines from user text.
- `start_poster(session_id, brief, language)`: under the lock, set `record["poster"]`, keeping the brief, status `drawing`, and the count of attempts; save; then submit to a `ThreadPoolExecutor(max_workers=2)`. At most `BLACKOUT_MAX_POSTERS_PER_SESSION` attempts per session (default 5).
- The worker calls `create_client().with_options(timeout=180, max_retries=1).images.generate(model=IMAGE_MODEL, prompt=..., n=1, size="1536x1024", output_format="png", extra_body={"tool_enablement": {"enable_image_search": False, "enable_web_search": False, "enable_shell": False}})`. Search stays off, so private thoughts are never used as web queries.
- Decode `b64_json`, and refuse anything that does not start with the PNG signature. Save atomically to `<sessions dir>/<id>.poster.png`, mode 0600 where supported. Under the lock, set status `done` and increment `version`. On failure, set status `failed` with a short Chinese `error`. A 402 is reported as budget used up.
- `summary.finish` starts a poster when the result is not degraded, the brief has at least one block with items, and no poster has been started yet. Finish must not wait for it. A later finish with no changes starts nothing. A sketch regenerates the result but does not redraw.

## `app/routes.py`
- `GET /api/sessions/{id}/poster`: the PNG, with `Cache-Control: no-store`. 404 in the error envelope if there is none. Validate the id first.
- `POST /api/sessions/{id}/poster`: draw again from the saved brief. 409 in the envelope if already drawing, or if the session has no brief. 429 in the envelope at the attempt limit.
- `GET /api/sessions/{id}` includes `poster` without needing anything else.

## `app/store.py`
- On load, a poster still `drawing` becomes `failed`.
- `delete_session` also removes the poster file.

Keep every other behaviour the same.
