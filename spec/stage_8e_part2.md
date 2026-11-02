From `spec/stage_8e_proof.md`, shown above, do only sections 4, 5, and 6.

Return the full content of exactly these files: `app/static/example.html`, `app/static/js/example.js`, `app/static/js/result.js`, `app/static/app.css`, `app/static/setup.html`, `app/static/js/i18n.js`, `tests/test_example.py`.

`tests/test_example.py` has only the static checks on `example.html` and `example.js`.

`example.html` needs these from the app's pages: `app.css`, `map.css`, `observer.css`, and the scripts `js/i18n.js`, `js/cues.js`, `js/speech.js`, `js/map.js`, `js/result.js`, `js/example.js`. `app/static/js/result.js` hides or shows `page-start` and `page-black` and uses `page-result`, `resultTitle`, `resultGoal`, `degradedNotice`, `resultSummary`, `stopReadingBtn`, `posterFigure`, `result`, `resultErr`, `copyBtn`, `sketchLabel`, `sketchInput`, and `restartBtn`, so `example.html` includes those ids, with `page-start` and `page-black` as empty hidden elements. Look at `observer.js` for how the map is drawn in the night theme and which classes the stage uses. Reuse those classes rather than adding near-copies. CSS needed only for the example goes in `app.css` under a `.example-` prefix.

`observer.css` sets `body { overflow: hidden; height: 100vh }`, which would stop the result page scrolling, so `example.js` adds a class to `body` when it moves to the result page, and `app.css` uses that class to restore scrolling and the paper background.
