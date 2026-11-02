A fresh install on GitHub Actions failed 17 budget tests on every platform. `requirements.txt` says `openai>=2.21.0`, so pip installed `openai` 3.42.1, a new major version built on a different HTTP library, `httpx2`. `budget.py` subclasses `openai.DefaultHttpxClient` and builds `httpx` responses, which no longer fit. Everything here was built and tested with `openai` 2.21.0, `httpx` 0.28.1, `fastapi` 0.162, `uvicorn` 0.48, `websockets` 16.0. Anyone installing today would get the untested major version, and the spending cap might not hold.

Return the full content of exactly `requirements.txt`. Keep the same packages, and give each an upper bound below the next major version, while keeping the existing lower bounds where they are compatible:
- `openai>=2.21.0,<3`
- `fastapi>=0.115,<1`
- `uvicorn>=0.30,<1`
- `python-multipart>=0.0.20,<1`
- `httpx>=0.27,<1`
- `pytest>=8,<10`
- `websockets>=14,<17`, raised from 12, because the code uses the asyncio client and `ws.request`, the default only from version 14
- `cryptography>=42,<47`
- `segno>=1.6,<2`
