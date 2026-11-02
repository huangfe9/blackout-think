Small fixes on the setup and example pages. Return the full content of exactly these files: `app/static/setup.html`, `app/static/example.html`, `app/static/js/example.js`, `app/static/app.css`. Change only what is listed.

1. `setup.html`: password managers ignore `autocomplete="off"` on password fields and may offer to save and sync the key. Use `autocomplete="new-password"`, and add `data-1p-ignore`, `data-lpignore="true"`, and `data-form-type="other"` to the key input.

2. `example.html`: in English the copy button shows "复制为 Markdown". Every button and label taken from the app's result page must carry the same `data-i18n` attribute as in `index.html`, and `example.js` must call `window.BlackoutI18n.apply(document)` after choosing the language and after every language toggle.

3. The replay's bottom note "No audio is played" is cut off by the window's bottom edge at 1280x720. Place it where it is fully visible, for example in the top banner after the first sentence, or above the counters. It must not overlap the caption.
