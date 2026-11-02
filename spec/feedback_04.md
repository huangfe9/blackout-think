A browser test found a privacy defect. Fix the following and keep everything else unchanged. Return only the files that change.

## app/static/index.html

1. CRITICAL, microphone left on after the session ends. If `endSession()` runs while `startRecording()` is waiting on `getUserMedia` or `audioWorklet.addModule`, recording setup continues afterwards: the stream is never stopped and `recording` becomes true on the result page. Checking `finishing` is not enough, because `finish()` resets it to false when the result page appears. In `startRecording()`, capture `var myStart=turnSeq` before the first await. After each await (the cue, `getUserMedia`, `addModule`), if `myStart!==turnSeq`, stop the stream's tracks if one was obtained, close the AudioContext if one was created, clear those variables, set `starting=false`, and return without setting `recording` or changing the status dot.

2. MEDIUM. `finish()` failure messages must say how to retry, because the screen stays black: use "生成成果失败，按 Esc 再试一次。" for the network failure path. In the `!r.ok` path, speak the server's message followed by "按 Esc 再试一次。".

3. LOW. In `endSession()`, replace `if(speechSynthesis.speaking||true)speechSynthesis.cancel();` with `speechSynthesis.cancel();`.

## app/main.py

4. LOW. In `api_finish`, the parse-failure and empty-markdown branches call `logger.exception` outside an except block, which logs a meaningless "NoneType: None". Use `logger.error` there.
