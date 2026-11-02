Implement stage 8, part D: the star map can be read on video, and the result page is really one page.

The star map is what a viewer watches for two minutes, and at 1280x720 its labels are about 10 pixels high, the centre sits left of the middle, and the goal's text sits on top of the connecting lines. The result page promises "one page" and takes 3.4 screens: decisions and todos are on the third screen and the copy button is at the very bottom. The feature that builds the most trust, seeing your own original words behind each item, has no visible sign that it can be clicked. Opening a past session lands partway down the page, cutting off the title.

Return the full content of exactly these files: `app/static/js/map.js`, `app/static/map.css`, `app/static/js/observer.js`, `app/static/observer.css`, `app/static/js/result.js`, `app/static/app.css`, `app/static/js/i18n.js`, `app/static/js/start.js`, `app/static/index.html`, `tests/test_look.py` (new). Keep every behaviour and every id you are not asked to change, because scripts and tests use them. Keep the black screen exactly as it is. No inline styles or scripts, since the Content Security Policy forbids them. Everything stays `textContent`, never `innerHTML` with data. Keep both languages. Colours come from the existing palette.

## 1. The star map (`map.js`, `observer.css`, `observer.js`)
All of this applies to the night theme in the star map window. The result page's paper map is section 3.

- The map fills the stage. Reserve less space: 44px at the top, 90px at the bottom, 220px on the right when the parking lot has items, and no right margin when it is empty. The tree's centre is at the centre of that area.
- Labels have a constant size on screen, however many nodes there are. Compute a scale from the SVG's rendered width and the viewBox width, then set font sizes so that a normal label is at least 18 CSS pixels at 1280x720, a top-level branch at least 20, and the goal at least 24. Line and mark sizes scale the same way. Recompute on resize.
- Fix collisions with the larger text by widening the layout, not by shrinking text. Keep the existing collision passes.
- Not every label needs to be readable at once, like a real night sky: the goal, the top-level branches, and the 8 most recently added nodes show full text at full brightness. Older leaf nodes keep their mark and label, dimmed to about 45% opacity, and the label is cut to 8 Chinese characters or 14 Latin ones. Track "recently added" by the order nodes first appear across renders. On first render with many nodes, the last 8 in tree order count as recent.
- The newest node gets a soft glow for about 3 seconds.
- Connecting lines are visible on a video: at least 1.5 CSS pixels wide, in a brighter tone than now. The conflict's dashed red line stays but is thin, and a `contradiction` label uses amber rather than alarm red, since it is a tension and not an error.
- The goal has a dark halo so lines do not run through its text. Lines stop at the edge of the goal's box.
- The bottom of the star map shows the last thing heard as a caption, at least 22 CSS pixels, one or two lines, and the AI's last spoken line in amber when it spoke within the last 12 seconds. If a caption already exists in `observer.js`, restyle it rather than adding a second one.
- The counter line adds "抓到矛盾 N 次" / "Caught N changes" from `stats.conflicts_asked` when above zero.
- The header's "未连接" / "Offline" stays, but after the session has finished it is hidden.

## 2. The final result page (`result.js`, `app.css`)
At 1000 CSS pixels wide and above, the top of the page is two columns: on the left the title, goal, summary, decisions, todos, and still-open questions; on the right the picture, sticky near the top. On a 1280x720 window the title, summary, picture, and the first items are all on the first screen. Below that, across the full width, in this order: the first draft, looked-up answers, the mind map, the parking lot, changes and tensions, your words. Under 1000 pixels it is one column in the order title, summary, picture, decisions, todos, still open, then the rest. Text sizes do not shrink below 15 pixels.

- Copy, download, and redraw move to a small row at the top of the page under the title, always reachable. "Add a paper sketch" and "Start again" stay at the bottom. The ids stay the same.
- Empty sections stay hidden. The section `unfinished` stays hidden when its list is empty, which is now normal.
- The picture has a hover or tap action to open full size in the same page, using a plain overlay with the same image and a close button. `Esc` closes it.

### First draft
A task with `kind` of `draft` is shown above other tasks, as its own block, whatever the `auto` flag says. Heading "第一份草稿" / "First draft". The instruction as a small line. The draft text itself is visible by default, not collapsed, in a readable block that keeps line breaks, using `white-space: pre-wrap`, with a "复制草稿" / "Copy draft" button beside it. While the task runs: "正在起草：{instruction}" / "Drafting: {instruction}". The page already polls while a task runs. When a polled task changes from running to done, update the block without reloading the page and without losing the scroll position, including the task list, which today only updates on reload.

### Original words
- Every item with evidence gets a visible small label after its text: "原话" / "Your words", underlined with dots, in the dim colour, and an arrow that turns when open. The whole item stays clickable, and the button has `aria-expanded`.
- Opened evidence appears as a quote block with a thin left line. It keeps the existing "Original words:" prefix only in the screen-reader text.
- Decisions and todos are shown with a marker: a diamond for decisions and an empty square for todos. The same marks are used on the map, so the two read as one system.

### Spoken ending
In `maybeSpeakSummary`, a degraded result does not say "All done". Add `degradedSpoken`: "整理没有完成，你说的原话都在页面上。" / "The summary didn't finish. Your words are all on the page." "All done" stays only for a truly empty session. If a draft task is running or done when the summary is read, add one sentence after the summary: "第一份草稿也写好了。" or, when running, "第一份草稿马上就好。" / "Your first draft is ready too." or "Your first draft is almost ready." The summary's first two sentences are read as they are now.

## 3. The map on the result page (`map.js`, `map.css`)
The paper map uses the same rule for label sizes: a normal label is at least 15 CSS pixels at the width it is drawn, a branch at least 17, the goal at least 20. The map may be as tall as it needs, up to 640 pixels, and it uses the page's full width below the columns. Lines are at least 1.2 CSS pixels and clearly visible on paper. The dimming and cutting of older nodes in section 1 does not apply here: every label is complete and dark.

## 4. Small fixes (`start.js`, `index.html`, `i18n.js`)
- Opening anything into the result page, and going back to the start page, runs `window.scrollTo(0, 0)`. Do this in `result.js` `showResult` as well.
- `observerCheck` becomes "同时打开星图窗口（第二块屏幕）" / "Also open the star map (for a second screen)". The checkbox stays. It no longer mentions recording a video.
- The start page fits a 1280x720 window with no vertical scroll. Reduce the vertical spacing as needed.
- `quiet-line`'s text stays.

## `tests/test_look.py` (new)
Static checks in the style of `tests/test_static.py`, reading files only:
- `observer.css` and `map.js`, `result.js`, and `app.css` contain what is needed: `white-space: pre-wrap`; `aria-expanded`; `scrollTo(0, 0)`, in both `result.js` and `start.js`; `position: sticky`; a `@media` rule at 1000px.
- `i18n.js` has both languages for each new key.
- `observerCheck` does not mention recording.
- No file changed here uses `innerHTML`.
- `index.html` still has every id it had: `page-start`, `page-black`, `page-result`, `goalInput`, `micBtn`, `startBtn`, `continueLastBtn`, `voiceWarning`, `startErr`, `openObserver`, `pastToggle`, `recentSection`, `recentList`, `dot`, `hint`, `resultTitle`, `resultGoal`, `degradedNotice`, `resultSummary`, `stopReadingBtn`, `posterFigure`, `result`, `resultErr`, `copyBtn`, `sketchLabel`, `sketchInput`, `restartBtn`, `langToggle`, `keyLink`, `howItWorksImg`.
