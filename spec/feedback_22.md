Update the documentation and one test. Return exactly these files, each with full content: `README.md`, `docs/demo_script.md`, `docs/submission.md`, `tests/test_static.py`. Do not change anything else.

## `tests/test_static.py`
`test_observer_never_shows_money` fails because the session id check in `observer.js` is a regular expression ending in `$`, which is not a dollar amount. Keep the intent. Check for `/api/status`, `spent`, 花费, and a dollar sign followed by a digit or by a template expression that formats money. Do not flag `$` at the end of a regular expression.

## All three documents must describe the product as it is now
- The concept is 关灯 → 星图 → 开灯. You press 关灯; the screen is pure black; a separate star map window, for video viewers, shows thoughts appearing as a real mind map; when you say 结束 the light comes on and the page turns to paper with the map at the top.
- Hands-free: no keys needed. The AI stays silent by default. The microphone stays on while the AI speaks, so you can talk over it, and it stops.
- A real mind map: the model places each point, decision, todo, question, and contradiction under the point it belongs to, in a tree built by the server, using additions only. It is also available as a nested outline in the Markdown copy.
- Ending: an utterance ends the session if its last clause is an end phrase, so 好，结束 works, or by Esc, leaving fullscreen, or holding the screen on a phone.
- Rename the observer to the star map (星图). It shows no money.
- Data is stored in `%LOCALAPPDATA%\Blackout` on Windows and `~/.blackout` elsewhere, including the spend ledger and the phone TLS files. The spend ledger lives there regardless of `BLACKOUT_DATA_DIR`, and `BLACKOUT_LEDGER_FILE` overrides it. Do not mention `data/tls/` or `.muse_spend.jsonl` as current locations.
- Background work has a per-session ceiling of 12 tasks and refuses duplicates.

## `README.md`
- In "How this project was built": Muse Spark and Muse Wonder generated the code in this repository, through the Meta Model API. Keep every other statement about who did what, and mention that a separate security review by Claude Code produced findings that Muse then fixed. Keep the note about the first two commits.
- Remove any statement that the phone flow, Chinese speech, or real speakers have been tested on real hardware by anyone other than the author. Under limitations, add: automated end-to-end runs used a simulated microphone with English speech and a simulated speech output; Chinese speech was tried by the author on a real computer; the phone flow has been exercised over HTTPS in a desktop browser, not yet on a physical phone.

## `docs/demo_script.md`
- Keep it to 3 minutes, in Chinese, with exact lines to say that reliably trigger each behaviour.
- Two-window recording: viewers watch the star map window at 1280×720, and hear the real conversation.
- Show the 关灯 moment at the start, and the 开灯 moment at the end, where the screen fades to paper with the map on top. Open with the black screen, because it is the memorable image.
- Refer to the person speaking without a gendered pronoun: use 我 or 出镜的人, never 他 or 她.
- A short section on what to do if something goes wrong while recording.
- Add a checklist item: tick 录视频：同时打开星图窗口 on the start page. Fullscreen is skipped in that mode, by design.

## `docs/submission.md`
English. Theme Build for Your World, Indie developer track. Rewrite it for the current product. Explain the use of Meta models accurately: `muse-voice-transcribe-1.0` realtime endpointing, `muse-spark-1.3` for conducting each turn, for background search with `web_search`, drafting, sketch understanding, and summarising, and `muse-wonder-1.0` and `muse-spark-1.3` as the coding models that generated the code. Keep the demo video link as a clear TODO. No invented anecdotes or metrics. Write the problem as: the tool you work with and the thing that distracts you are the same screen. Keep the authorship statement accurate, including the role of Claude Code.
