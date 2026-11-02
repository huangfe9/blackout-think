Implement stage 4 of the v2 spec above: the observer window, phone mode, and all documentation. Return the full content of every changed or new file. Do not change existing backend behaviour except as listed.

## Observer window
`app/static/observer.html`, `app/static/observer.css`, `app/static/js/observer.js`, and the `GET /observer` route, exactly as the "Observer window" section specifies. It must read clearly in a 1280×720 video: large type, high contrast, dark background, and everything visible without scrolling at that size. When the session has finished, show the result title and stop polling. A missing or invalid `session` parameter shows a friendly message. Use `textContent` for everything. No inline script or style.

`live.mic` is ambiguous today: `speaking` is used both when the user talks and when the AI talks. Change the values to `listening`, `paused`, `user_speaking`, `ai_speaking`, and `offline`, in `app/realtime.py`, `app/conductor.py`, and `app/store.py`, and update any tests and the spec's `/live` shape. The observer shows these as 在听, 暂停, 用户在说, AI 在说, 未连接.

## Phone mode
`app/phone.py`, exactly as specified, using `python -m app.phone`. It must:
- reuse an existing valid certificate if its IP still matches, otherwise regenerate it
- store the private key with restrictive permissions where the platform supports it
- detect the LAN IP with a UDP socket trick that sends no packets, with a clear error when no network is available
- never log the token apart from the one printed start-up URL and QR code
- work if `segno` is missing by printing the URL only

Add `tests/test_phone.py`: the certificate has the IP in its subject alternative names and parses correctly; a regenerated certificate replaces a mismatched one; the token is generated with sufficient length; no network calls are made in tests beyond a mocked socket.

## Documentation
`README.md`, in English, for judges and for anyone who wants to run it. Sections: what it is and the problem; how it differs from a voice assistant; a short demo of the flow; how it uses Meta models, naming each with what it does (`muse-voice-transcribe-1.0` realtime endpointing, `muse-spark-1.3` for conducting each turn, background search with `web_search` and drafting, sketch understanding, and result summarising, and `muse-wonder-1.0` as the coding model that generated much of this repository); architecture; how to run on a computer; how to run on a phone with `python -m app.phone`; spend control; privacy (sessions are stored locally in `data/`, and audio and text go to the Meta Model API); limitations, stated honestly: browser speech output quality depends on the device, speech output is not a Meta model, the phone flow has a certificate warning, and there is no usage data yet. Keep the "How this project was built" section accurate as it stands, and add the stage files in `spec/` to it. Do not invent user numbers or results.

`docs/demo_script.md`, in Chinese: a 3-minute script for the new flow. Two-window recording: the observer window is what viewers see, and the audience hears the real conversation. Scenes: the problem (20 s); start and black screen (15 s); thinking out loud with the AI staying quiet and the observer's map filling up (45 s); drift to 火锅, pulled back, parked (25 s); 帮我查一下, keep talking, the answer arrives in one sentence (30 s); an unfinished point gets a nudge (15 s); 结束, the one-page result (20 s); close (10 s). Give exact lines to say that reliably trigger each behaviour. Include a setup checklist.

`docs/submission.md`, in English: theme Build for Your World, Indie developer track. Rewrite "What it does" and "How it works" for the new product. Keep the Indie scope statement accurate, and keep the demo video link as a clear TODO. Write the problem section without invented anecdotes or metrics, keeping to: the tool you work with and the thing that distracts you are the same screen.

`LICENSE`: the MIT License, copyright 2026 huangfe9.

The README, demo script, and submission must describe the current behaviour: hands-free listening, staying silent by default, the microphone staying on while the AI speaks so it can be interrupted, the data directory location (`%LOCALAPPDATA%\Blackout` on Windows, otherwise `~/.blackout`), and the push-to-talk fallback. In the README's "How this project was built", keep every statement about who did what, and also mention the `feedback_*` and `stage_*` files.

Your response must contain every file named above, and `tests/test_static.py` updated so `observer.html` is covered by the same checks as `index.html`.

Keep `tests/` passing.
