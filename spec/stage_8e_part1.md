From `spec/stage_8e_proof.md`, shown above, do only sections 1, 2, 3, and 7.

Return the full content of exactly these files: `tests/evals/talks.json`, `tests/evals/run_evals.py`, `tests/evals/make_samples.py`, `docs/demo_talk.json`, `tests/test_eval_data.py` (new).

`tests/test_eval_data.py` has the static checks from that spec's test section that concern `talks.json` and `demo_talk.json`, and the check on `app/static/sample/en.json` if it exists.

In `docs/demo_talk.json`, also include `"scene_captions"`, an object of captions for the parts of the video outside the talk, each at most 12 words, for a viewer who has never seen this:
- `start`: the person types one goal and presses Lights off.
- `black`: this black screen is all the person gets; from here it is voice only.
- `wait`: lights on at once; the real summary wait of about 15 seconds is shortened here.
- `result`: one page: the summary, decisions, todos, and a picture drawn by Muse Image.
- `words`: every item opens to the exact words behind it.
- `draft`: it noticed a writing todo and drafted it in the background.
- `picture`: the same picture, drawn from the checked summary.

Facts you need:
- `app.store.create_session(goal, owner="", language="zh")` returns a record with `id`.
- `app.conductor.process_speech(session_id, text, now=None)` returns a dict with `action`, `reply`, `end`, `task_started`, and more. `now` is a float of seconds. `app.conductor.clear_memory()` exists.
- `app.summary.finish(session_id)` returns the result dict: `title`, `summary`, `language`, `decisions`, `todos`, `open_questions`, `parking_lot`, `contradictions`, `unexpanded_points`, `tasks`, `map`, `evidence`, `transcript`, `poster`, `markdown`, `degraded`, and more. Items in those lists are strings.
- `app.store.get_session_copy(session_id)` returns the record: `state`, `tasks`, `stats`, `poster`, `result`, `owner`, and more. `poster.status` is `drawing`, `done`, or `failed`.
- `app.state.build_map(state, tasks)` builds the map.
- `app.poster.poster_path(session_id)` gives the picture's path.
- `budget.spent_usd()` gives dollars spent, and `budget.can_spend()` says whether more is allowed.
- Set `BLACKOUT_DATA_DIR` before importing `app` modules, because `app.store` reads it. The modules run from the repo root, so `python -m tests.evals.run_evals` must work. Add an empty package marker only if it is needed, and if so return `tests/evals/__init__.py` as well, with a one-line docstring.
- These scripts make real, paid calls through the normal client, so they do not run under pytest. Their file names do not start with `test_`.
