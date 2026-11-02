# Demo script

The video is about 3 minutes. It follows `docs/demo_talk.json`, goal: "Decide how to run a small product launch this week".

## What the video shows

- Title: "Blackout: thinking without a screen". On screen: "Recorded live against the real Meta API. The voices are computer speech."
- Start: "Type one goal. Press Lights off." The goal is typed and Lights off is pressed.
- Black: "This black screen is all you get. From here, voice only." The screen is pure black with a dim dot.
- Open: "One goal, three things to sort out." The speaker names the launch day, support cover, and the announcement.
- Quiet: "The AI stays silent and quietly builds the map." The speaker decides Thursday morning and three people on support. The AI says nothing.
- Drift: "Off topic: the idea is parked, attention returns." The speaker wants hot pot tonight. The AI parks it and pulls back.
- Lookup: "A lookup runs in the background while thinking continues." The speaker asks when launch emails get the most opens and keeps thinking.
- Conflict: "Five, not three: the AI asks about the change." The speaker says five people on support.
- Answer: "Corrected to three, with weekend cover on-call only." The speaker settles it.
- Todo: "A writing todo the AI can draft later." A short launch email is due Wednesday.
- Open question: "An open question is kept, not answered away." Marketing review timing is unknown.
- Stop: "One word ends it and brings the light back." The speaker says "Stop."
- Wait: "Lights on at once. The real 15-second summary wait is shortened here." The result page appears at once and fills in.
- Result: "One page: summary, decisions, todos, and a picture from Muse Image."
- Words: "Every item opens to the exact words behind it." A summary item is expanded to its source sentences.
- Draft: "It noticed a writing todo and drafted it in the background." The launch email draft is shown.
- Picture: "The same picture, drawn from the checked summary." The hand-drawn picture is shown, then the closing lines: "No screen while you think. One page when you finish." and "It runs on your own computer with your own Meta key."

The star map window is visible beside the black screen, so viewers can see the mind map growing while the speaker cannot.

## How it was made

- This was a real run, not a mock-up. A computer voice speaks the lines in `docs/demo_talk.json` into the app's microphone input.
- The app called the real Meta API during the recording. The speaker and the AI are both computer voices.
- The screen was captured and edited. The summary wait was shortened, and the video says so on screen.
- No lines, replies, or results were typed in by hand for the recording.

## How to re-record it with your own voice

- Run the app with your own key: `python start.py`. Keep the key page out of the recording.
- Tick the option to open the star map window, so the map is visible on screen.
- Read the same lines from `docs/demo_talk.json` in order, with the pauses marked there. Speak the end phrase last.
- Record with any screen recorder. Keep the black screen, the star map, and the result page in frame.
- If you shorten the summary wait in editing, say so on screen, as this video does.
