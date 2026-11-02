Implement stage 5: a real mind map, and a design that belongs to this product. A user tried the app and said the observer looks wrong: it reads like an admin dashboard, money should not appear, and the "思路图" is only lists, not a mind map. They are right. Also fix one real bug from their session (see "End phrases").

Return the full content of every changed or new file. Your response must contain: `app/state.py`, `app/prompts.py`, `app/conductor.py`, `app/realtime.py`, `app/tasks.py`, `app/summary.py`, `app/routes.py`, `app/static/index.html`, `app/static/app.css`, `app/static/observer.html`, `app/static/observer.css`, `app/static/js/map.js`, `app/static/js/observer.js`, `app/static/js/result.js`, `app/static/js/start.js`, `app/static/js/black.js`, `tests/test_state.py`, `tests/test_conductor.py`, `tests/test_realtime.py`, `tests/test_summary.py`, `tests/test_routes.py`, `tests/test_static.py`, `README.md`, `docs/demo_script.md`.

## The concept: 关灯 → 星图 → 开灯
Three moments, one metaphor. Everything serves it.
1. **关灯 (start).** You do not fill in a form. You say what you want to think through, and you turn off the light.
2. **黑屏 and 星图.** The screen in front of you is pure black and shows nothing. Unchanged. For someone watching, such as a video viewer, a separate window shows your thoughts appearing in the dark as a star map that grows while you speak.
3. **开灯 (result).** When you finish, the light comes on: the page fades from black to warm paper, and the map is now ink on that paper, with the page of results beneath it.

It must not look like a dashboard. No cards, no rounded panels, no grid of boxes, no green "status" styling, no counters in boxes, and never any money or spend.

## Design tokens
Define these as CSS custom properties in `app.css` and `observer.css`:
- Night: `--night: #000000`, `--dusk: #0b0b0c` (start page background, so going to true black is visible), `--star: #f4efe6` (warm white), `--star-dim: #8a8478`, `--line: #3a3833`
- Accent: `--amber: #e8b44c` (AI speaking, unfinished points), `--signal: #e5604d` (contradiction only), `--parked: #7d93b2` (parking lot and questions)
- Paper: `--paper: #f6f1e7`, `--ink: #1c1a17`, `--ink-dim: #6b655a`, `--rule: #d9d1c1`

Type: system fonts only, no external resources: `"PingFang SC", "Microsoft YaHei UI", "Microsoft YaHei", "Noto Sans CJK SC", "Segoe UI", system-ui, sans-serif`. Large text is weight 300. Respect `prefers-reduced-motion`: no pulsing or tweening, nodes simply appear.

The Content-Security-Policy forbids inline styles and scripts. Style with classes. Setting properties with `element.style.x = ...` from JS and SVG attributes are allowed.

## Start page
Background `--dusk`, centered column, no boxes:
- The Blackout name, small and quiet at the top.
- A large question: 今天要想清楚什么？
- One large input with only a bottom hairline, weight 300, placeholder 比如：想清楚比赛 demo 的技术方案. A mic control as an inline SVG icon at its right end, with `aria-label` 语音输入目标; while recording it pulses amber.
- One large round button labelled **关灯**, softly glowing warm white. It does what 开始 does.
- Under it, one quiet line: 屏幕会全黑。你说，它听。说「结束」，灯再亮。
- A small checkbox: 录视频：同时打开星图窗口.
- The no-Chinese-voice warning as one small amber line, and errors in `--signal`.
- Below that, recent sessions as a plain list with hairlines between items: goal text, date, and quiet text buttons 查看 or 继续, and 删除. If nothing is stored, show nothing at all rather than a heading with an empty note. 继续上次 appears as a quiet text button under 关灯 when relevant.
Keep the existing element ids where the JS uses them, or update the JS consistently.

Pressing 关灯: the screen fades to pure black in about 500 ms. Fullscreen and audio priming must still happen inside the user gesture as they do now. When the star map window is being opened, do not request fullscreen at all: opening the popup consumes the gesture, and losing fullscreen would end the session.

The black page stays exactly as it is: pure `#000`, a dim corner dot, a hint that fades.

## The map: data
A real tree, built deterministically by the server. Nothing can be lost from it.

Additions carry `under`, as the spec's schema now says. `under` is the exact text of an existing point or a point added in the same turn; empty means directly under the goal.

`state.py`:
- `main_points` entries gain `under`. Add `state["links"]`: a dict from a decision, todo, question, or contradiction text to its `under`. The lists `decisions`, `todos`, `open_questions`, and `contradictions` stay plain strings, so the summary and everything else keep working. `apply_additions` accepts both the new object form and old plain strings, so sessions saved earlier still load.
- Add a pure function `build_map(state, tasks) -> dict` returning `{"id", "text", "kind", "status", "children": [...]}`. The root is the goal with kind `goal`. Kinds: `point` (with `status` of 已展开 or 未展开), `decision`, `todo`, `question`, `contradiction`, `task` (with `status` of running, done, or failed; text is the conclusion when done, and the instruction while running). Children of a point come in insertion order: sub-points, then decisions, todos, questions, contradictions, tasks. An `under` that matches nothing goes under the root. A cycle must not hang or lose a node: break it by attaching to the root. `id` is a stable hash of kind and text, so the client can tell which nodes are new. The parking lot is not in the tree.
- `GET /api/sessions/{id}` adds `"map"`, computed on the fly. Result gains `"map"`, and it is refreshed whenever the result is regenerated or a late task result arrives.
- Tasks record `under`.
- `summary.py` Markdown: add a section 思路 with the map as a nested list, so pasting it into any outline or mind-map tool keeps the structure. Keep the other sections.

Prompt: explain `under` in `TURN_SYSTEM_PROMPT` with a worked example. Someone says 语音、状态、成果页三个部分: three points with empty `under`. Then 语音这块我决定用实时模式: decision with `under` 语音. Then 实时模式能自动判断说完: a sub-point with `under` 语音. Text in `under` must exactly match existing text.

## The map: drawing (`js/map.js`)
A shared renderer used by the star map window and the result page: `BlackoutMap.render(svgElement, tree, {theme: "night" | "paper", animate: bool})`. No libraries. Build SVG with `createElementNS`, and set labels with `textContent`. Full text goes in a `<title>` child.

Layout: a radial tree. The root is at the center. Each top-level subtree gets an angular span proportional to its leaf count, starting at the top and going clockwise. Children fan out within their parent's span. Ring radii are about 200, then 350, then 480 for deeper levels. Labels sit outward from the node: `text-anchor` start on the right half and end on the left. Wrap at about 12 Chinese characters or 22 Latin characters, at most two lines, then an ellipsis.

The whole map must always fit: compute the bounding box of nodes and estimated label sizes, set the `viewBox` to it with padding, and never scale up beyond 1.2 times. A map with 2 nodes must look intentional and centered, and 40 nodes must remain legible, without overlapping labels at 1280×720 in the common case. Use leaf-weighted spans so a busy branch gets more room.

Node marks:
- `goal`: no shape. Larger text with a soft glow in night theme.
- `point` 未展开: a hollow amber ring that pulses slowly. It reads as: this is not finished.
- `point` 已展开: a solid bright star-like dot with a soft glow.
- `decision`: a small solid diamond in `--star`, bolder label.
- `todo`: a small hollow square.
- `question`: a small ring in `--parked`.
- `contradiction`: a small mark in `--signal`, with a dashed `--signal` connector.
- `task` running: a small amber dot with a moving pulse, labelled 在查：… or 在写：…. Done: a small filled dot. Failed: dim.

Paper theme: the same geometry in ink, with no glow and no animation. `--rule` lines, `--ink` text, amber only for 未展开 rings. It should look printed.

Animation (night theme, when `animate` is true, and only for nodes whose `id` is new): the connector draws from the parent to the node with a stroke-dash reveal, then the mark and label fade in. When positions shift because of a new node, tween all positions over about 600 ms using `requestAnimationFrame`, updating connectors each frame. Tween the `viewBox` too. Do not rebuild everything on each poll: if the tree has not changed, do nothing.

## Star map window (`observer.html`)
The name in the UI is 星图. Full-bleed `--night`, with the SVG filling the window. Nothing else competes with the map. Designed to read at 1280×720 on video.
- Top left, very small: Blackout · 星图. Top right, small text with no pill: 在听, 暂停, 你在说, AI 在说, or 未连接 (it maps the `live.mic` values), with `--amber` for AI 在说.
- Bottom center, like film subtitles and with no box: the live caption or last thing said, in `--star` at about 26 px. When the AI has just spoken, its line appears beneath in `--amber`, and under that, very small in `--star-dim`, the decision and reason, such as 拉回主线 · 偏离目标. When it chose `listen`, show only 听着，没打断 in `--star-dim`, which is the point of the product. Subtitles fade after about 8 seconds with no change.
- Right edge, a narrow column labelled 停车场 in `--parked`, with parked ideas as plain text. A new one slides in from the map's center direction and glows amber for 2.5 seconds, so a viewer sees the idea get moved aside.
- Bottom left, very small in `--star-dim`: 说了 N 句 · 开口 M 次 · 拉回 K 次. These show the behaviour that makes the product different.
- **Remove all spend and money.** `observer.js` must not call `/api/status`.
- On finish: the map stays, and a line 灯亮了 · <title> fades in at the top center. Stop polling.
- A missing or invalid session parameter shows one quiet centered line.

## Result page: 开灯
When the result appears after a session, the background fades from `--night` to `--paper` over about 900 ms, like a light coming on. Reopening from the list goes straight to paper. Always paper, regardless of system color scheme.
- Title, large, weight 300. The goal beneath it, in `--ink-dim`, only if it differs from the title.
- The map, in paper theme, as the hero. Omit it entirely if there are no nodes beyond the goal.
- Below it, no cards: sections divided by hairlines, with small labels in `--ink-dim`. On wide screens 决定 and 待办 sit side by side and are visually first. Then 还没想清楚, 前后矛盾, 没说完的点, 停车场, 后台查到和写好的, 纸上草稿. Hide empty sections.
- If there is nothing at all, show one line: 这次没有记下内容。
- Buttons at the end, quiet text-style with one primary in ink: 复制为 Markdown, 加入纸上草稿, 再来一次.
- Keep every existing behaviour: late task polling, sketch upload, sources as safe links, the degraded notice.

Layout must work at phone width with no horizontal scroll. The map scales to the page width.

## End phrases
From the user's session: they said 首先我觉得就有个问题，好，结束。 and it did not end. They then said 我已经说结束了，你怎么还在, and it asked for confirmation. Both are wrong.
- `state.py`: add `split_end(text) -> tuple[str, bool]`, returning the content before the end phrase and whether the session should end, following the rule in the spec. Use it in `is_explicit_end`'s callers. `is_explicit_end` stays as an exact check on a whole utterance only if still needed.
- `conductor.process_speech`: when `split_end` says end and there is content, run one model turn on the content with its reply suppressed, then return `end: true`. With no content, make no model call.
- `conductor`: if the model returns `summarize` and the text contains 结束 or 停止, end straight away without asking.
- `realtime.py`: the worker's separation of end phrases must use `split_end`, so 第一句，好，结束 is not joined with other text.
- Tests: 好，结束。 / 好了结束 / 那就到这里吧 is not in the list so it goes to the model / 首先我觉得有个问题，好，结束 records the content and ends / 我想讨论怎么结束这个项目 does not end / 结束这个项目 does not end / 我已经说结束了你怎么还在 with a model `summarize` ends / 今天差不多了 with a model `summarize` still asks.

## Small things
- Add `"under"` handling so that `sketch.py` additions still work with no `under`.
- `tests/test_static.py`: `observer.js` contains neither `/api/status` nor `spent`, and all static checks cover the new files.
- `tests/test_state.py`: `build_map` covers nesting, unknown `under` going to the root, cycles, stable ids, old-format sessions with plain strings, and tasks.
- `README.md` and `docs/demo_script.md`: rename the observer to the star map (星图), describe 关灯 and 开灯, and describe what a viewer sees. In `docs/demo_script.md`, refer to the person speaking without a gendered pronoun: use 我 or 出镜的人, never 他 or 她. In the README, the cert path is under the data directory rather than `data/tls/`, and "How this project was built" should say Muse Spark and Muse Wonder generated the code.

All tests must pass.
