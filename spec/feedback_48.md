Accuracy fixes in the documents, and one page fix. Return the full content of exactly these files: `README.md`, `docs/submission.md`, `app/static/example.html`. Change only what is listed.

## `README.md`
1. The line with the video and replay links: after the video link add "(recorded live against the real API; the voices are computer speech)".
2. `## What you get`: the image is the hand-drawn picture, so its alt text becomes "Picture drawn by Muse Image from a fictional talk". The paragraph lists what the page shows. Good results no longer have an "unfinished points" section, and the contradictions section is now titled "Unresolved tensions". Make the list "a short summary, a clean mind map, decisions, todos, open questions, parked ideas, and unresolved tensions". "Every summary item can be opened" becomes "Every decision, todo, and question can be opened".
3. `## Run it`: after "A key in `.env` or in the environment also works. See `.env.example`." add: "If you use `.env`, keep the project out of cloud-synced folders such as OneDrive or Dropbox, because the key would be uploaded with it. The page stores the key outside the project instead."
4. `## Your key and your words`: add a bullet: "Anyone who can run programs as you on this computer can use the running app, as with any local tool, but cannot read the key back from it."

## `docs/submission.md`
In "How it uses Meta's models", "Because browser echo cancellation does not cover speechSynthesis" becomes "Because browser echo cancellation may not cover the system speech voice". Also add "about $0.12 per talk in the evaluation, and about $0.20 for a short talk with the picture" where the cost is mentioned under "How to try it", replacing the current cost sentence.

## `app/static/example.html`
Browsers request `/favicon.ico` when a page names no icon, which gives a 404 on static hosting. Add `<link rel="icon" href="data:,">` in the head, as `index.html` does.
