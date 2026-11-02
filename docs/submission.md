Project name
Blackout

Tagline
Think it through without looking at a screen.

Short description
Blackout lets you think out loud with the screen off. It stays quiet, tracks your points, parks drift, and returns a cited summary, mind map, decisions, todos, and a hand-drawn picture when you say Stop.

Description
Tools for thinking usually live on the same screen that distracts from thinking. Blackout removes the screen instead of reminding you to focus. You type or speak a goal, press Lights off, and the screen goes black. You think out loud, walking around, lying down, or sketching on paper, with no keys to press. The AI listens continuously and stays quiet by default, building a mind map against your goal. It speaks only when a point was left unfinished, a fact you stated has changed, you drifted off the goal, you asked it something, or you have gone silent for a long stretch. Drift is stored in a parking lot and you are brought back in one sentence. A request to look something up runs in the background while you keep talking, then reports one spoken sentence. When you say Stop, the light comes on at once. You get a summary read aloud, a clean mind map, decisions, todos, open questions, parked ideas, and a hand-drawn one-page picture. A voice assistant answers every sentence. Blackout's main behaviour is knowing when to say nothing, and tracking the whole line of thought instead of one exchange at a time.

How it uses Meta's models
Each turn, muse-spark-1.3 returns a strict structured decision: listen, follow up, pull back, continue, answer, summarise, or start background work. Listen is the default, so silence is enforced by the schema and by server rules, not left to chance. The model returns additions only, never a rewritten state, so nothing recorded can be lost. muse-voice-transcribe-1.0 runs over a realtime connection with cumulative partials. Because browser echo cancellation may not cover the system speech voice, the server tells the AI's echo from real speech by comparing recognised text with what was just spoken, so you can talk over the AI and be heard. At the end, Spark reads every utterance and must cite numbered utterances for each summary item. The server checks the citations and drops any item without a valid one. Spark then reads back the picture drawn by muse-image-1.0 to check its text. Muse Spark and Muse Wonder also generated the project itself.

Technical highlights
- Strict structured output each turn, with additions only and a server-side rule that keeps listen turns silent.
- Realtime speech over a WebSocket bridge, with text-based echo detection so the microphone stays on while the AI speaks.
- A deterministic mind map tree built on the server from additions, shown live in the star map window and tidied by the final pass.
- Citation checking on the server: final items without a matching numbered utterance are dropped, and a later statement replaces an earlier one rather than counting as a contradiction.
- Local spend control in budget.py, owner-only key storage outside the repository, and sessions scoped to the owning browser with no accounts.

Theme and track
Theme: Build for Your World. Track: Indie developer (solo-built).

Links
Repository: https://github.com/huangfe9/blackout-think
Demo video: https://github.com/huangfe9/blackout-think/releases/download/v1.0/blackout_demo.mp4
Replay, no key and no install: https://huangfe9.github.io/blackout-think/app/static/example.html

How to try it
Open the replay link above. It needs no key and no install. To run the real app, use your own Meta Model API key from https://dev.meta.ai/api-keys/ and run: git clone https://github.com/huangfe9/blackout-think ; cd blackout-think ; pip install -r requirements.txt ; python start.py . A browser opens and asks for the key. It costs about $0.12 per talk in the evaluation, and about $0.20 for a short talk with the picture, from your own Meta account.

Contributors
Only human contributor: huangfe9 (GitHub), who had the idea, made the product decisions, and tried it. Muse Spark and Muse Wonder, through the Meta Model API, generated the code, tests, and docs. Raw model output is in muse_runs/, prompts in spec/. Claude Code (Anthropic's coding agent) drafted the prompts from the author's idea, ran the generation, reviewed and tested the output, wrote throwaway test scripts that are not in this repository, assembled the demo video from a real recording, and made the commits. Security reviews by Claude Code produced findings that Muse then fixed. This public repository starts from a clean commit, and earlier development happened in a private repository during the event. Only muse-spark-1.3, muse-voice-transcribe-1.0, and muse-image-1.0 are used by the running product.

Known limits
- Not tried by anyone except the author, so no effectiveness claims are made. It needs a quiet-enough place to talk aloud, and multiple speakers are not told apart.
- The end-to-end browser flow has been run on Windows with Chrome. macOS and Linux run the automated tests in CI only, and a physical phone has not been tested.
- Speech output uses the browser's voice, whose quality varies by device. Text in a generated picture can still come out wrong despite the check, and it can be redrawn.
- Not built for public hosting: it would need per-visitor spending limits and data expiry. Clearing browser cookies loses access to past sessions.

Pre-submit checklist
- [ ] Repo is public.
- [ ] Video link works when logged out.
- [ ] Everyone who contributed is listed.
- [ ] Submitted through the Cerebral Valley platform before Nov 4, 9 PM ET.
- [ ] API credits claimed.
- [ ] Eligibility confirmed against the official rules, which exclude some countries and regions.
- [ ] The official rules checked for anything these notes missed.
