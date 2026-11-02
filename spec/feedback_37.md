Looking at the real pages after stage 8d found these. Fix them. Return the full content of exactly these files: `app/static/app.css`, `app/static/js/map.js`, `app/static/map.css`, `app/static/js/i18n.js`, `app/prompts.py`. Change nothing else. Keep every id, and keep all existing behaviour not mentioned here.

## 1. The start page was squeezed too hard
At 1280x720 the content is jammed against the top with an empty lower half. The picture is cropped at the bottom, cutting its captions, and the "API key" link sits on top of the picture.
- The two columns are centred vertically in the window, using a full-height flex container, with at least 56px clear at the top.
- The how-it-works picture always shows whole: `width: 100%; height: auto; max-height: 72vh; object-fit: contain`. Remove any fixed height, `overflow: hidden`, or `object-fit: cover` that crops it. It must never touch the top-right links.
- `.top-actions`, holding "API key" and the language toggle, is fixed to the top right of the window, at 18px from the top and 28px from the right, above everything, and it never overlaps the picture because of the 56px clearance.
- The page still needs no vertical scroll at 1280x720. Under 900px wide it stacks as one column and may scroll, and nothing overlaps.

## 2. Star map labels look broken when cut
Older leaf labels are cut mid-word with no mark, like "Keep your open" and "Ask Dana for c". Stop cutting labels in the night theme. Older leaf nodes keep their full text and only dim to about 55% opacity. Widen the layout if needed so they do not collide.

## 3. Lines run through text
- Connectors are drawn before and below every label and mark, in both themes, so no line crosses a label's text. Use one SVG group for connectors, placed first, and one for nodes. Keep the existing `paint-order: stroke` halo on labels in the page's background colour and make it wide enough, about 6 pixels at the rendered size, to separate a label from a line near it.
- The goal's label sits at the centre of the tree, and connectors stop at the edge of its box, in both themes.
- A branch label is placed on the outward side of its point, not across its connectors.

## 4. Wording
In `i18n.js`, the `contradictions` heading becomes "还没解决的矛盾" / "Unresolved tensions".

## 5. Better structure from the model (`app/prompts.py`)
- In `TURN_SYSTEM_PROMPT`: never add a top-level point that merely restates the goal, because the goal is already the centre of the map. For the goal "Figure out how to give my talk", "Offsite talk" is wrong, and "Opening story", "Format", and "Crash numbers" are right.
- In `FINAL_SYSTEM_PROMPT`, about `nodes`: group by topic, never by type, so there is no group called "Tasks", "待办", "Decisions", or "决定". Do not repeat every todo in the map, since todos have their own list on the page; keep only those that are key to a topic. When a topic has sub-parts, use the third level, for example "What went wrong" holding "Login crash lost reviews".
