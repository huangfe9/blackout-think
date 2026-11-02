Small follow-ups from stage 8. Return the full content of exactly these files: `tests/test_look.py`, `tests/test_static.py`, `tests/test_summary.py`, `docs/demo_talk.json`, `.gitignore`. Change only what is listed. Every other line of each file stays the same.

1. `tests/test_look.py`, `test_observer_and_map_features`: older labels now dim to 0.55 and are no longer cut, by design. Check for `0.55` rather than `0.45`, and drop any check that labels are cut.

2. `tests/test_static.py`, `test_no_external_urls_anywhere`: also allow exactly `https://github.com/huangfe9/blackout-think#run-it`, the project's own repository, in `example.html` and `example.js` and nowhere else.

3. `tests/test_summary.py`, `test_verbatim_fields`, line 78: a good final result no longer has an unfinished-points section, so the Markdown must not contain `## 没说完的点`. Change the assertion to `not in`.

4. `docs/demo_talk.json`: replace `scene_captions` with exactly these, which are shorter and speak to the viewer:
   - `start`: "Type one goal. Press Lights off."
   - `black`: "This black screen is all you get. From here, voice only."
   - `wait`: "Lights on at once. The real 15-second summary wait is shortened here."
   - `result`: "One page: summary, decisions, todos, and a picture from Muse Image."
   - `words`: "Every item opens to the exact words behind it."
   - `draft`: "It noticed a writing todo and drafted it in the background."
   - `picture`: "The same picture, drawn from the checked summary."
   Change the line "Actually, I really want hot pot tonight." to "By the way, I really want hot pot tonight." Everything else in that file stays as it is.

5. `.gitignore`: add `submission/`, the local folder holding the finished demo video.
