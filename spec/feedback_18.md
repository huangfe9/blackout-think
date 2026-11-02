Finish wiring the new map into the pages. `app/static/map.css` and the new `app/static/js/map.js` are already in place. Return exactly these files, each with full content: `app/static/js/result.js`, `app/static/js/observer.js`, `app/static/js/black.js`, `app/static/observer.css`, `app/static/app.css`. Do not return anything else.

1. `result.js`: use `BlackoutMap.renderOutline` when the page is narrower than 640 px and the SVG `BlackoutMap.render` otherwise. Re-choose on `resize`, debounced, and only when crossing that width. Do not show the map at all when there are no nodes beyond the goal.

2. `observer.css` and `observer.js`: the bottom subtitles must never overlap the map. The map has its own area: top about 44 px, bottom about 150 px, right about 250 px. The SVG fills that area with `preserveAspectRatio="xMidYMid meet"`. Pin the parking column to the top of the right edge, under the mic state. `observer.js` must call `BlackoutMap.render` with the class names `map.css` expects, and must not call `/api/status`.

3. `black.js`: `/api/sessions/{id}/announcements` is now `POST`. Update the poll in push-to-talk mode.

4. `app.css`: add any styles needed for the outline used on phones, matching the paper theme, unless `map.css` already covers them. Remove anything now unused.

Everything rendered uses `textContent`, with no inline scripts or styles.
