Return exactly one file with full content: `app/static/js/map.js`.

The code was compressed onto long lines, some over 1,200 characters, with one-letter names. This repository will be read by judges. Rewrite it for readers without changing what it does:
- One statement per line, with normal two-space indentation, and no line over 120 characters.
- Descriptive names, such as `leafCount`, `layoutTree`, `wrapLabel`, and `computeViewBox`. Small named functions, each under 50 lines.
- A brief comment on the layout approach and on why elements are reused between frames. Do not comment on obvious lines.

One visible fix: a label's background-colored stroke overlaps the node's mark, so a dot appears half covered. Draw the mark after the label so the mark is on top, and move labels about 3 px further from the mark.

Keep the public API (`BlackoutMap.render`, `BlackoutMap.renderOutline`), all behaviour, the class names used by `map.css`, and all rendering through `textContent`.
