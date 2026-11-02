Fix docs/submission.md only. Return only that file.

1. Replace the "Indie scope" paragraph. "Designed, built, and tested solo in a weekend" is unsupported. State instead: one person defined the idea and reviewed the result; Muse Spark generated the application, tests, and docs from `spec/`; budget.py and muse_client.py are hand-written infrastructure.
2. "AudioWorklet PCM captured at 16 kHz" is wrong. Say PCM is captured by an AudioWorklet and resampled to 16 kHz mono in the browser.
3. Under "How it works", name the models: muse-spark-1.3 for conversation state and summaries, muse-voice-transcribe-1.0 for speech to text. Speech output is the browser's speechSynthesis, not a Meta model.
4. In "The problem in my world", remove the claim about notifications and do not add invented anecdotes or metrics. Keep to: the tool you work with and the thing that distracts you are the same screen.
5. Set the demo video link to a clear TODO placeholder.
