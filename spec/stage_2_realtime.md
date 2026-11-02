Implement stage 2 of the v2 spec above: the realtime bridge and the security layer. Return the full content of every changed or new file. Do not change the conductor's behaviour.

## Implement now
- `app/realtime.py` exactly as the "Realtime bridge" section specifies, and the `WS /ws/sessions/{id}` route.
- `app/security.py` exactly as the "Security" section specifies, wired into `app/main.py`, covering HTTP and WebSocket.
- Keep the blocking conductor. The bridge must not block the event loop: all conductor calls, store access, and budget access go through `asyncio.to_thread`.
- `live` values update from the bridge: mic state, partial, last user text, last reply, action, and reason.

## Details to get right
- `turnId` can be 0. Any check for a turn must compare with `None`.
- Ignore an empty `speechComplete` transcript and the empty `final: true` transcript sent after `endStream`.
- A partial never triggers a turn. Only `speechComplete` does.
- `user_speaking` must clear on `speechEnd`, and also when a matching `speechComplete` arrives without an earlier `speechEnd`, so a lost event cannot block delivery forever. Clear it after 30 seconds regardless.
- Delivery: after a `say` is sent, nothing else is delivered until `tts_finished` or a 20-second timeout.
- While paused: audio keeps flowing to keep the stream alive, but `speechComplete` text is discarded, partials are discarded, and no nudges fire. The browser sends zeroed frames then, so this is a safety net.
- While the AI is speaking the browser also sends zeroes, but echo can still leak through. Discard a `speechComplete` when its speech started during playback and it arrived within 1.5 seconds of `tts_finished` only if its text exactly equals the text just spoken, after removing punctuation and spaces.
- On `end`, send it once only, then stop reading audio. The browser calls `/finish`. The bridge does not.
- Audio accounting: count only bytes actually forwarded upstream. Divide by 48,000 for seconds. Record at most every 30 seconds and always in a `finally` block, so a crash cannot lose usage.
- The API key is sent only in the handshake to the upstream URL. Refuse to send it unless the upstream URL is the default real URL, or its host is `127.0.0.1` or `localhost` for tests.
- Reject a browser frame larger than 64 KB, and close the socket with 1009 if that happens repeatedly. Audio frames faster than real time must not be forwarded: drop anything that would put the stream more than 3 seconds ahead of the wall clock, so a misbehaving client cannot trigger a pacing rejection or spend faster than real time.
- Replacing a bridge: a new connection for the same session closes the old one with code 4000, and the old one's cleanup must not touch the new bridge's state.

## Tests
`tests/fake_asr.py`: a local fake speech server using `websockets.serve` on an ephemeral port. It validates the handshake, acknowledges with `sessionId`, records received bytes, and plays a scripted event list. It can be told to close with a given code.

`tests/test_realtime.py`, using `BLACKOUT_ASR_URL` and a fake conductor where convenient:
- a handshake failure sends `fallback`
- `turnId` 0 works end to end, from `speechComplete` to the conductor to `say`
- `tick` on a `listen` turn
- partials never trigger a turn and update `live.partial`
- two `speechComplete` events arriving while the model is thinking are joined into one next turn
- a reply is discarded if `speechStart` arrived during the model call, while its state is still saved
- nothing is delivered while the user is speaking; an announcement is delivered afterward
- only one `say` is outstanding until `tts_finished`, and the 20-second timeout works, using an injectable clock or a short configured timeout
- nudges fire after the configured time and not while paused
- budget: `can_spend` false before connect sends `end` with reason `budget`
- audio is recorded in the ledger at close and is proportional to bytes forwarded
- faster-than-real-time audio is not forwarded past the allowance
- close 1011 reconnects and the session continues; 1008 sends `fallback`; retries exhausted sends `fallback`
- a browser disconnect sends `endStream` and closes upstream
- replacing a bridge closes the old socket with 4000
- end phrase over the socket sends `end` with reason `phrase` once
- the real key never appears in any message sent to the browser or in captured logs

`tests/test_security.py`:
- bad `Host` rejected; `localhost`, `127.0.0.1`, and `BLACKOUT_ALLOWED_HOSTS` accepted
- a POST with a foreign `Origin` returns 403 including multipart; same-origin and absent `Origin` pass
- WebSocket with a foreign `Origin` is refused
- with `BLACKOUT_ACCESS_TOKEN` set: no token returns 401; `?token=` sets a cookie with HttpOnly, Secure, and SameSite=Strict and redirects without the token; the cookie then works; a wrong token returns 401; WebSocket requires it
- with no token configured, requests pass
- rate limit returns 429 in the error envelope and resets after the window
- security headers are present on `/`
- `Content-Length` over the limit is refused before the body is read
