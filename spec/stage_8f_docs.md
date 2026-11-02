Implement stage 8, part F: the documents a stranger and a judge will read.

The project is about to go public in a new repository, and be submitted to the Meta Global AI Developer Hackathon. A reader should know within 20 seconds what this is, and be able to run it within 5 minutes. Everything must be true. Use plain, short sentences. No hype, no "revolutionary", no "seamless". Say what is not yet tested.

Return the full content of exactly these files: `README.md`, `docs/submission.md`, `docs/demo_script.md`, `docs/ci_tests.yml` (new). Change nothing else.

## Facts
- Repository: https://github.com/huangfe9/blackout-think
- Replay that needs no key and no install: https://huangfe9.github.io/blackout-think/app/static/example.html
- Demo video: https://github.com/huangfe9/blackout-think/releases/download/v1.0/blackout_demo.mp4
- Theme: Build for Your World. Track: Indie developer. Only human contributor: huangfe9 (GitHub), who had the idea, made the product decisions, and tried it.
- Models in the running product: `muse-voice-transcribe-1.0` (realtime speech, plus file transcription for the fallback and goal dictation); `muse-spark-1.3` (the conductor's structured decision each turn, background search with `web_search`, background drafting, paper sketch reading, the cited final pass, and reading the picture back to check its text); `muse-image-1.0` (the one-page hand-drawn picture, $0.01 each). `muse-wonder-1.0` and `muse-spark-1.3` generated the code, but only Spark, Voice, and Image are used at run time.
- How it was built: Muse Spark and Muse Wonder, through the Meta Model API, generated the code, tests, and docs. Raw model output is in `muse_runs/`, prompts in `spec/`. Claude Code (Anthropic's coding agent) drafted the prompts from the author's idea, ran the generation, reviewed and tested the output, wrote throwaway test scripts that are not in this repository, assembled the demo video from a real recording, and made the commits. Security reviews by Claude Code produced findings that Muse fixed. This public repository starts from a clean commit, and earlier development happened in a private repository during the event.
- Running it: Python 3.10 or newer, Chrome or Edge, a microphone, and the person's own Meta Model API key from https://dev.meta.ai/api-keys/ . Commands: `git clone https://github.com/huangfe9/blackout-think`, `cd blackout-think`, `pip install -r requirements.txt`, `python start.py`. A browser opens and asks for the key. A key in `.env` or the environment also works, see `.env.example`.
- Cost: from the person's own Meta account. A short talk of about 25 sentences costs about $0.20, including the search, the draft, and the picture; a longer talk costs more in proportion. Paid calls stop at `BLACKOUT_STOP_AT_USD`, default $10, at most $140, enforced locally by `budget.py`.
- Key handling: the key is saved in `%LOCALAPPDATA%\Blackout\api_key` or `~/.blackout/api_key`, outside the repository, with owner-only permissions where the system supports them. No route returns it, not even masked. It is sent only to `api.meta.ai`. It is checked with Meta before it is saved. Only the computer running the server can set, change, or delete it, and only from the app's own page. Logs redact it. The browser does not keep it. Anyone with access to the computer's user account can read the file, as with any local credential. Suggest using a key with a spending limit set in Meta's billing page.
- Privacy: speech and text go only to the Meta Model API. Sessions are saved on the person's own computer and can be deleted from the past sessions list. There are no accounts and nothing is sent to the author.
- What it does: you type a goal and press Lights off. The screen goes black. You think out loud, and it stays quiet, building a mind map. It pulls you back when you drift, parking the idea. If you say "please look up..." it searches in the background and tells you one sentence when done. If a fact you state changes, it asks which holds. After a long quiet stretch it gives one line of status. Say "Stop" and the light comes on: a summary read aloud, decisions, todos, open questions, every item traceable to your exact words, a first draft of something you said you needed to write, and a hand-drawn picture. If anything goes wrong, it says so out loud.
- A second window, the star map, shows the mind map growing, for a second screen or a video.
- A phone can use it on the same Wi-Fi with `python -m app.phone`: HTTPS with a self-signed certificate and an access token. Not yet tried on a physical phone.
- English and Chinese.
- Tests: `python -m pytest`; no key or network is needed. Evaluation: `python -m tests.evals.run_evals` makes real paid calls; results are in `docs/evals.md`. Quote the totals from the file shown above, saying what they are: fictional talks typed through the same code path, skipping speech recognition, scored by simple rules, measuring behaviour and not benefit.
- Known limits: it needs a quiet-enough place to talk aloud. Not tried by anyone except the author, so no effectiveness claims. It is a thinking tool, not a treatment for attention problems, and gives no health advice. The end-to-end browser flow has been run on Windows with Chrome. macOS and Linux run the automated tests in CI only. Physical phone untested. Speech output uses the browser's voice, whose quality varies by device. Text in a generated picture can still come out wrong despite the check, and it can be redrawn. Not built for public hosting: it would need per-visitor limits and data expiry. Multiple speakers are not told apart. Clearing browser cookies loses access to past sessions.
- The demo video was recorded live against the real API, with computer voices for the speaker and the AI.

## `README.md`
Order: title; one line, "Think it through without looking at a screen."; a two-sentence description; the image `app/static/how_it_works_en.jpg`; a line with the video link and the replay link; `## What it does`; `## What you get`, showing `app/static/sample/en.jpg` and a sentence saying it is real output from a fictional talk; `## Run it`, which must produce the anchor `#run-it`, with the commands in one code block; `## Your key and your words`; `## How it differs from a voice assistant`, in at most 4 bullets; `## Measured behaviour`; `## How it uses Meta models`; `## How it works`, at most 8 bullets naming the main files, including `app/conductor.py`, `app/realtime.py`, `app/summary.py`, `app/poster.py`, `app/keys.py`, `budget.py`; `## On a phone`; `## Limits`; `## Contributors and how this was built`; `## 中文说明`, 6 to 10 lines in Chinese with what it is and the four commands; `## License`: MIT. Keep it under 170 lines.

## `docs/submission.md`
Everything needed to fill in the submission form, so a person can copy from it. The form's fields are not known, so give these clearly separated, as plain text and not inside code fences:
- Project name.
- Tagline, under 100 characters.
- Short description, under 60 words.
- Description, 150 to 250 words: the problem, what it does, why it is different from a voice assistant.
- How it uses Meta's models, 100 to 150 words, emphasising what goes beyond a basic integration: strict structured decisions that keep silence as the default; realtime speech with text-based echo detection; every final item checked against numbered utterances on the server; Spark reading back Muse Image's picture to check its text; and Muse generating the project itself.
- Technical highlights, 5 bullets.
- Theme and track.
- Links: repository, video, replay.
- How to try it: the replay with no key, or run with your own key in the four commands.
- Contributors, and the disclosure of Claude Code's role, in the words of the facts above.
- Known limits, 4 bullets.
- A pre-submit checklist with these items: repo is public; video link works when logged out; everyone who contributed is listed; submitted through the Cerebral Valley platform before Nov 4, 9 PM ET; API credits claimed; eligibility confirmed against the official rules, which exclude some countries and regions; the official rules checked for anything these notes missed.
Do not write first-person stories about the author's life. Do not claim usage numbers.

## `docs/demo_script.md`
Short, under 60 lines. What the 3-minute video shows, scene by scene, using the beats and captions in `docs/demo_talk.json`. How it was made: a real run where a computer voice speaks `docs/demo_talk.json` into the app's microphone input, the app calling the real Meta API, and the screen captured and edited, with the summary wait shortened and said so on screen. How to re-record it with your own voice: read the same lines in the app with the star map window open, using any screen recorder, and keep your key page out of the recording.

## `docs/ci_tests.yml`
A GitHub Actions workflow named `tests`, to be copied to `.github/workflows/tests.yml`. On push and pull request. Matrix: `ubuntu-latest`, `macos-latest`, `windows-latest`, with Python `3.10` and `3.13`; `fail-fast: false`. Steps: `actions/checkout@v4`, `actions/setup-python@v5`, `pip install -r requirements.txt`, `python -m pytest -q`. `permissions: contents: read`. No secrets of any kind, and no step that calls a paid API.

## Final evaluation numbers to quote
From `docs/evals.md`, run 2026-11-02 on the final code with nothing else spending: 8 fictional talks, 124 lines. The AI spoke on 31 of them and made 0 unasked interruptions. Pull-backs 8 of 8. Changed facts asked about 7 of 8. Look-ups started 8 of 8. Decisions found 8 of 10, todos 8 of 8, open questions 6 of 8, parked items 8 of 8. Both talks that called for a draft got one, and 4 other talks with a writing todo also got an unasked draft. Median turn about 4.2 seconds. Average cost $0.12 per talk of 15 to 17 lines including search and draft, with no picture. A picture adds $0.01 plus a short check, and a longer talk costs more.
