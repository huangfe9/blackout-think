The new summary and picture work very well. Fix these remaining items. Return the full content of exactly these files: `app/static/index.html`, `app/static/app.css`, `app/static/js/black.js`, `app/static/js/result.js`, `app/static/js/start.js`, `app/prompts.py`, `app/poster.py`, `build_with_muse.py`, `test_build_with_muse.py`. Keep lines under 120 characters where possible, with one statement per line.

## Turn the light on immediately
The final pass takes about 18 seconds. Today the screen stays black and silent for all of that, which is the opposite of the light coming on.

In `endSession`, after stopping capture and closing the socket:
- Say 好，我来整理，稍等一下。 The budget variant stays as it is.
- Immediately leave fullscreen, release the wake lock, and show the result page in a pending state: the fade to paper plays now, with the goal as the title and one gently pulsing line 正在整理你说的话…
- Then call `/finish`. When it returns, fill in the page with `showResult(result, id, {read: true})` and read the summary as now.
- If it fails, stay on the paper page, show 整理失败了，你说的话都还在。 and a 重试 button that calls `/finish` again. Saying or pressing anything else is not needed. The session stays resumable.

Add `BlackoutResult.showPending(goal)`, and `black.js` needs the goal: `enter(id, resumed, goal)`, with `start.js` passing it. When resuming from the list, the goal is known from the list. If the goal is unknown, the title is empty.

Remove the old "按 Esc 再试一次" path. Leaving fullscreen during this must not start a second finish; keep the guard.

## Start page headline
"不看屏幕，说着把事想清楚。" wraps and leaves a lone 楚. Break it deliberately into two lines using two block-level spans in `index.html`: 不看屏幕， and 说着把事想清楚。 On phones it may wrap naturally within each span.

## `app/prompts.py`: the live map is too crowded
A long talk gave 49 nodes, because the same thing was recorded both as a decision and a todo, such as 周日白天录 twice. In `TURN_SYSTEM_PROMPT`, say that one thing is recorded once: an action the person will do is a todo, and a choice between alternatives is a decision. Keep the rest of the prompt as it is. The final pass reorganizes everything at the end, so the live map only needs the gist.

## `app/poster.py`
A session deleted while its picture is being drawn leaves an orphan file. Save the picture under the session lock, after confirming the session still exists.

## `build_with_muse.py`
Sending the whole project made the prompt 500,000 characters, and the model then returned junk such as a single file containing "hello". Add `--context` taking comma-separated file paths: when given, the prompt holds the spec, only those files, and the feedback. Also add `--expect`, comma-separated paths: if the response has a path outside this list, or a nearly empty file, refuse the whole response and write nothing. Binary and non-UTF-8 files are skipped. Update the module docstring. In `test_build_with_muse.py`, add tests for the context limit, the refusal for unexpected paths, and the refusal for nearly empty content, without any network calls.
