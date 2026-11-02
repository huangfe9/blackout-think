Implement stage 6, frontend part. The backend now returns `summary`, a clean `map`, `evidence`, `transcript`, and `poster`, as the code shows. Read `app/summary.py` and `app/routes.py`, and match them.

The person's request: the whole UI should be concise and make it instantly clear what this software does, and after talking for a long time it should summarize and draw.

Return the full content of exactly these files: `app/static/index.html`, `app/static/app.css`, `app/static/js/start.js`, `app/static/js/result.js`, `app/static/js/black.js`, `app/static/js/observer.js`, `app/static/observer.html`, `app/static/observer.css`, `app/static/js/map.js`. Keep lines under 120 characters, with one statement per line and descriptive names. No inline scripts or styles. Everything rendered uses `textContent`.

## Start page: understood in three seconds
上一版的“今天要想清楚什么？”和“关灯”很有气质，但第一次来的人不知道这是干什么的. Keep the dark background, and say what it is. A sample of the result does most of the explaining.

Two columns on wide screens, one on phones. No cards.

Left column:
- `Blackout`, small and quiet.
- Headline, large, weight 300: 不看屏幕，说着把事想清楚。
- One line under it: 你只管说。它安静地听，跑题了拉你回来；说完，给你一页总结和一张图。
- The goal input with only a bottom hairline, placeholder 这次想想清楚什么？比如：周末怎么做完 demo 视频, with the mic icon at its right end.
- One primary button, a warm white pill rather than a big circle: 关灯，开始说
- One small line under it: 屏幕会变黑，直接开口。说「结束」，灯亮，出图。
- 继续上次 as a quiet text button when relevant. Errors and the no-Chinese-voice warning as one small line each.

Right column: `/static/sample_poster.jpg` (already in place), as a sheet of paper lying on the dark background, tilted about -1.5 degrees with a soft shadow, and a small caption under it: 说完就有这样一张图. `alt`: 一张手绘总结图，有时间线和流程图. On phones it comes after the button, full width with no tilt.

Below both columns, quietly: the recent sessions list as now, and the small checkbox 录视频：同时打开星图窗口. Show the list only when there are sessions.

## Result page: 总结, 图, 其余
Always paper. In this order, and hide whatever is empty:
1. Title, large, weight 300. The goal under it in `--ink-dim` only if it differs.
2. **Summary**: `result.summary` as a paragraph at about 20 px, line height 1.7. This is the first thing read.
3. **Picture**: a figure, full content width.
   - `drawing`: a paper-toned placeholder with the same 3:2 shape and gently pulsing text 正在画总结图…
   - `done`: `<img src="/api/sessions/<id>/poster?v=<version>">` with `alt` from the title, and two quiet text controls under it: 下载这张图 (an `<a download>` link) and 重画一张 (POST, then back to `drawing`).
   - `failed`: the error in one line and 重画一张.
   - While `drawing`, poll `GET /api/sessions/{id}` every 3 seconds, for up to 3 minutes, and update the figure when it changes. Do not re-render or reset the rest of the page when polling. Merge this with the existing task polling into one polling loop. Stop when nothing is pending, or when the page is left.
4. **思维导图**: a small label, then the map in paper theme, or the outline on narrow screens, from `result.map`.
5. 决定 and 待办 side by side on wide screens, then 还没想清楚, 前后矛盾, 没说完的点, 停车场, 后台查到和写好的, 纸上草稿.
6. **Evidence**: an item with an entry in `result.evidence` is a plain button that looks like text. Clicking it shows its original words beneath it in `--ink-dim`, prefixed 原话：, and clicking again hides them. Items without evidence are plain text.
7. A `<details>` at the end, 你说的原话（N 句）, listing `result.transcript`, so nothing said is out of reach.
8. Buttons: 复制为 Markdown, 加入纸上草稿, 再来一次.

If there is nothing at all: 这次没有记下内容。

## Reading the summary aloud
The person may not be looking yet: the phone may be face down. When a session ends and the result appears, speak `result.summary` with `BlackoutSpeech.speak`. If it is over about 120 characters, read the first two sentences. While speaking, show one small quiet control near the summary, 停止朗读, and any click on it or Space stops it. Do not read when reopening a saved result from the list. If the summary is empty, say 整理好了。 Add a parameter to `showResult` for this, and have `black.js` pass it from `endSession`.

## Star map window: the ending is the picture
- During the session it shows the live map as now.
- When the session finishes, it first renders `result.map` in night theme, tweening from the raw map to the clean one. Keep polling; do not stop at finish.
- When `poster.status` is `done`, fade the map out and fade the picture in, centered and fully visible on black, as large as fits the window, with the line 灯亮了 · <title> above it. Hide the subtitles and the parking column at that point. Stop polling then, or when the poster has failed, or after 3 minutes. If it failed, stay on the clean map.

## `map.js`: labels must not overlap
With 25 nodes, labels overlap and become unreadable. Keep the radial layout, then add a separate, readable pass that resolves collisions: estimate each label's box, and repeatedly push the node that is farther from the center outward along its own direction until no boxes overlap, within a limit of about 40 passes. Connectors follow the new positions, and the bounding box and `viewBox` use them. This must not move the root.
