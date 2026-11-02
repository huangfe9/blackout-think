A real run of the result page found these. Fix them. Return the full content of exactly these files: `app/static/js/result.js`, `app/static/app.css`. Change only what is listed.

## 1. The picture disappears
`showResult` moves the element `#posterFigure` into the new right column inside `#result`. When the page re-renders, for example when the background draft finishes and polling calls `showResult` again, `box.replaceChildren()` detaches that element along with the old columns. After that, `el("posterFigure")` returns null, because `getElementById` only finds elements in the document, so the picture is never put back and the right column stays empty. Every finished talk with a draft loses its picture.

Keep a module-level reference to the figure element, taken once when the script starts. `renderPoster` and `showResult` use that reference, never a fresh lookup by id. Do the same for any other element that is moved into `#result`. Also move the figure before calling `renderPoster`, so it renders into an attached element.

## 2. A long todo pushes its text below its mark
In the todo list, when the text plus "Your words" does not fit on one line, the empty square stays alone on the first line and the text starts on the next. List items with a mark use a hanging indent instead: the item has `padding-left` for the mark, and the mark is positioned in that space, so wrapped lines align with the text, not the mark. The same applies to decisions.

## 3. Spacing and scrolling
- Put 20px between the summary paragraph and the first section heading.
- The sticky action row at the top covers a section heading when a section is scrolled into view. Give `.sec` and the draft block `scroll-margin-top: 72px`. Give the sticky row the page background, so text does not show through it.
