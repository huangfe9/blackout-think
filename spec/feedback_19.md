Screenshots and a live run found the items below. Return exactly these files, each with full content: `app/static/js/map.js`, `app/static/map.css`, `app/prompts.py`, `budget.py`. Do not return anything else. Keep everything else the same.

## `budget.py`: the cap can be bypassed by changing a directory
The ledger path honours `BLACKOUT_DATA_DIR`. A live run with a temporary data directory spent real money, and the real total did not change, because that spend went to a ledger in the temporary folder. Worse, the import-time copy made a second independent ledger. The cap must count all spending on this machine.
- The default ledger is always `%LOCALAPPDATA%\Blackout\spend.jsonl` on Windows and `~/.blackout/spend.jsonl` elsewhere. `BLACKOUT_DATA_DIR` must not affect it.
- The only override is an explicit `BLACKOUT_LEDGER_FILE` environment variable, which also disables the migration copy from the old repository file.
- The migration from `<repo>/.muse_spend.jsonl` still happens once, only when the default ledger does not exist. The default ledger exists now, so it must not be overwritten or copied again.

## `app/prompts.py`: spoken conclusions lost the answer
A live search reported "找到了比赛 demo 可用的语音转写价格信息。" The spoken sentence says something was found and omits the answer. The user cannot see the screen, so this sentence is the whole result. Rewrite `SEARCH_SYSTEM_PROMPT`: the first sentence must state the answer itself, with the specific figure, name, or fact, and at most 40 characters. Never describe the act of searching, and never say 找到了, 查到了, or 信息 as the content. Example: asked how much Muse Voice Transcribe costs per hour, the first sentence is "每小时 0.18 美元。". If the search does not give an answer, the first sentence says so plainly, such as "没查到确切价格。". Keep Arabic numerals and units. Details follow as plain sentences with no label such as 细节是.

## `app/static/js/map.js`
1. **Words are split.** "想清楚比赛 de/mo 的技术方案" and "Transc/ribe" break inside Latin words. Wrap on token boundaries: a run of Latin letters, digits, and hyphens is one unbreakable token, and each Chinese character is its own token. Only split a Latin token if it alone is wider than a whole line. Apply this to both goal wrapping and label wrapping.
2. **Larger type for video.** Base label 19 px, goal 26 px. Keep the rest of the layout logic, including the room guarantee.
3. **The outline duplicates its root.** `renderOutline` repeats the goal as the first item, but the page title already shows it. Start from the root's children, so the top level is the goal's branches. If there are no children, render nothing.

## `app/static/map.css`
1. **Double bullets in the outline.** The nested list shows browser bullets and the custom marks together. Set `list-style: none` and tidy the indentation, so each row has only its mark. Long text wraps aligned with the start of its text, not under the mark.
2. **Glow too heavy on the goal.** The goal's drop shadow makes the text look blurred and doubled. On night, use a subtle shadow on the goal only, at most `0 0 10px rgba(244,239,230,.35)`. Keep the stronger glow only for the point dots.
