Implement stage 7, part A: every visitor is separate.

The person who owns this project opened the app and pointed out that anyone opening it should see a brand-new app, not someone else's things. A check confirmed something worse: `GET /api/sessions` lists every session on the server to anyone, including private goals, and any client with an id can read a session. That is acceptable on one person's own computer and unacceptable the moment it is shared.

There are no accounts. A browser is the unit of ownership.

Return the full content of exactly these files: `app/security.py`, `app/store.py`, `app/routes.py`, `app/realtime.py`. Keep lines under 120 characters, with one statement per line. Do not change anything else.

## `app/security.py`
After the existing checks, for HTTP and WebSocket scopes:
- Read the cookie `blackout_owner`. It is valid only if it matches `^[A-Za-z0-9_-]{20,64}$`.
- For HTTP with no valid cookie, create one with `secrets.token_urlsafe(24)`, and add to the response: `Set-Cookie: blackout_owner=<token>; Path=/; HttpOnly; SameSite=Lax; Max-Age=31536000`, plus `; Secure` when the scope's scheme is `https`.
- Put the owner in the scope as `scope["blackout_owner"]`: the SHA-256 hex digest of the token, so session files never hold a bearer token. For a WebSocket with no valid cookie, it is an empty string. Nothing logs it.
- Add `owner_of(connection) -> str`, returning `connection.scope.get("blackout_owner", "")`.

## `app/store.py`
- `create_session(goal, owner="", language="zh")`: the record stores `owner` and `language`.
- `can_access(record, owner) -> bool`: a record with no `owner`, such as an older session, can be reached by its exact id only, because the id is a 128-bit secret. A record with an `owner` needs an equal, non-empty owner, compared with `hmac.compare_digest`.
- `list_sessions(owner, limit=50)`: only records whose `owner` equals the given non-empty owner. An empty owner gets an empty list. Records with no owner are never listed.

## `app/routes.py`
- `POST /api/sessions` takes `{"goal", "language"}`. `language` is `zh` or `en`, default `zh`, and anything else is `zh`. It stores the requester as owner.
- `GET /api/sessions` lists only the requester's sessions.
- Every `/api/sessions/{id}...` route, including live, announcements, poster, sketches, finish, turns, text-turns, and delete, goes through one helper. If the session is missing, or `can_access` is false, it returns the same 404 in the error envelope, so a stranger cannot tell a foreign session from a missing one.
- Responses never include `owner`.
- `GET /api/status` reveals spending. Serve `spent_usd` and `limit_usd` only to a loopback client; others get only `ledger_ok` and `can_spend`.

## `app/realtime.py`
`handle_websocket` checks `can_access` with `owner_of(websocket)` before accepting. A stranger's socket closes with code 1008, and no upstream connection is opened and nothing is spent.
