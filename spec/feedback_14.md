Three tests fail because of how they are written. The application code is right. Return exactly `tests/test_realtime.py` and `tests/test_static.py`, each with full content. Do not change `app/`, and do not weaken what the tests check.

1. `tests/test_static.py`, `test_no_inline_script_style_or_handlers`: delete the stray first loop whose regular expression `r"<script\b([^>]*>"` has an unterminated group. The correct loop below it stays.

2. `tests/test_realtime.py`, the receive helpers: `expect_no_message` starts a thread blocked in `ws.receive_json()`. After its timeout that thread is still blocked and later consumes the next real message, so `recv_until` times out, as in `test_real_partial_during_playback_stop_speech_once_and_turn`. Use one reader per socket: a small wrapper that starts a single daemon thread on first use, which reads every message into one `queue.Queue`, recording a closed marker when the socket closes. `recv_json`, `recv_until`, `expect_no_message`, and `expect_socket_closed` all read from that queue. A timed-out wait must never lose a message.

3. `tests/test_realtime.py`, `test_5_reply_discarded_at_delivery_announcement_still_delivered`: it sends `tts_started` and then a bare `speechStart`. Under the echo rules, a turn starting during playback is suspect and does not count until confirmed, so the reply is correctly not discarded. Make the test confirm real speech: after `speechStart` for turn 1, send a partial with at least 4 characters that is not an echo, such as 我想换个话题说说. Then the reply must be discarded and the announcement delivered, as the test asserts. Send a `text` value with `tts_started`.

The whole of `tests/` must pass, and `tests/test_realtime.py` must stay under 30 seconds.
