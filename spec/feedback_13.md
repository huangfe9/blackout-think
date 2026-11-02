`tests/test_conductor.py` line 326 has a syntax error, so no test in that file runs:

    assert "tracki」"" not in inner or inner.endswith("tracking")

There is a stray extra quote. Rewrite the assertion correctly. Return exactly `tests/test_conductor.py` with full content and change nothing else. Do not weaken any other test.
