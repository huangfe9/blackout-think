Implement part of stage 6: the star map window and map layout. The backend returns `map` and `poster` on the record's `result`, and `GET /api/sessions/{id}/poster` serves the picture; read `app/routes.py` below and match it.

Return the full content of exactly these files: `app/static/observer.html`, `app/static/observer.css`, `app/static/js/observer.js`, `app/static/js/map.js`. Keep lines under 120 characters, with one statement per line and descriptive names. No inline scripts or styles. Everything rendered uses `textContent`.

## Star map window: the ending is the picture
- During the session it shows the live map as now.
- When the session finishes, it first renders `result.map` in night theme, tweening from the raw map to the clean one. Keep polling; do not stop at finish.
- When `poster.status` is `done`, fade the map out and fade the picture in, centered and fully visible on black, as large as fits the window, with the line 灯亮了 · <title> above it. Hide the subtitles and the parking column at that point. Stop polling then, or when the poster has failed, or after 3 minutes. If it failed, stay on the clean map.

## `map.js`: labels must not overlap
With 25 nodes, labels overlap and become unreadable. Keep the radial layout, then add a separate, readable pass that resolves collisions: estimate each label's box, and repeatedly push the node that is farther from the center outward along its own direction until no boxes overlap, within a limit of about 40 passes. Connectors follow the new positions, and the bounding box and `viewBox` use them. This must not move the root.
