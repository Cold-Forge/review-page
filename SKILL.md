---
name: review-page
description: "Live click-to-comment review loop for anything the user should look at: a built site, a scroll-driven page, an HTML document, a PDF, a folder of deliverables, a dev server or a live URL. Triggers: review page, i need a review page, mark it up, click-to-comment, review notes, REVIEW-NOTES, let me review it, I want to comment on the page. Starts a local review server (review.py in this skill's folder) with the real pages in desktop and phone frames; the user clicks elements, boxes areas or selects text and picks Remove / Rework / Comment / Discuss / Add; every note lands on disk at once with its scroll moment. Also defines how the follow-up turn reads, answers and closes the notes (notes.py)."
---

# review-page

A live review loop. The user marks up the real page in a browser. Each note is on disk the moment it is saved.
You read the notes, act on them in the source, answer or close each one, and the open review shows your answer
within two seconds.

`<skill dir>` below is this skill's base directory (the folder holding this file). The tool lives there:
`review.py` (server), `store.py` (notes store), `notes.py` (your command line), `shots.mjs` (screenshots per
note), `ui/` (review screen and in-frame annotator), `test/` (e2e test and regression). `README.md` has the
full reference.

Reviews live in the reviews home: `--home`, else `$REVIEW_PAGE_HOME`, else `"home"` in
`<skill dir>/config.local.json`, else `~/.review-page/reviews`. Each review is one folder `<home>/<slug>/`;
`REVIEW-NOTES.md` is what you read, `comments.json` is the data.

## 1. Start a review

One command, any target. `--detach` keeps the server alive after this session ends. Leave `--no-open` off when
the user is at the keyboard, so their browser opens on it.

```
python <skill dir>/review.py <target> --name <slug> --detach
```

| Target | What the user gets | Default frames |
|---|---|---|
| built site folder (`dist/` with `index.html`) | every page, with a page picker | Desktop 1440x900 and Phone 390x844 side by side |
| folder of deliverables (no `index.html`) | every PDF (first) and HTML file in it | Fit |
| `<doc>.html` | the document; a same-name `<doc>.pdf` opens first, as pages | Fit |
| `<doc>.pdf` | the PDF as pages with a selectable text layer | Fit |
| `http://127.0.0.1:<port>/` (dev server) | the dev server through one origin, its real CSP kept | Desktop and Phone |
| `https://live-site/` | the live site, pages from its sitemap; POST/PUT/PATCH/DELETE blocked | Desktop and Phone |

- `--name` is the review's folder. Reuse the same name for every round of the same deliverable, so the notes
  carry over.
- A once-per-session intro or a cookie wall: `--session KEY=VALUE` or `--local KEY=VALUE` presets storage.
- Relaunch later: `python <skill dir>/review.py --resume <slug> --detach`, or run `open-review.cmd` (Windows) or
  `open-review.sh` in the review's folder. Stop: `python <skill dir>/review.py --stop <slug>`.
- `python <skill dir>/notes.py` lists every review, its open and done counts, and whether it is running.
- Use the dev-server URL instead of `dist/` when the page needs its real headers or functions (CSP, `_headers`,
  serverless functions). The static server ignores `_headers`.

Give the user the URL the command prints, and the slug. Say this once per new review, short:

> **C** click an element · **V** box any area · **T** select text · **B** browse normally. In the note:
> Enter saves, Shift+Enter new line, Alt+1-5 picks **1 Remove · 2 Rework · 3 Comment · 4 Discuss · 5 Add**.
> Every note is on disk the moment you save it, no export. Unmarked = OK. Tell me when you are done.

## 2. Read the notes (the follow-up turn)

```
python <skill dir>/notes.py <slug>            # the work list, grouped by action, DISCUSS first
python <skill dir>/notes.py <slug> shots      # one PNG per open note at its viewport and scroll moment
```

Read the shots (`<home>/<slug>/shots/n-<n>.png`) before you act on anything visual. Each note is reproduced at
the exact scroll position the user wrote it at, with the area outlined. For a pinned scroll scene the note also
carries the scene and its progress ("act--mirror at 47 %"), so "the mirror" means that moment, not the whole
section.

1. **DISCUSS first.** Ask about each Discuss note before you change anything, together with the judgment calls
   the other notes imply. Then act.
2. **REMOVE / REWORK / ADD** go into the source that builds the page, never by hand into generated HTML.
   Rebuild. The open review shows a "Page rebuilt: reload" button by itself when the reviewed file changes.
3. **COMMENT** gets a reply in the review, not only in chat: `notes.py <slug> reply <n> "answer"`. If the answer
   implies a change, treat the note as REWORK.
4. Close each note you handled, saying what changed:
   `notes.py <slug> done 3 5 8 --reply "Headline shortened to one line (commit abc123)"`.
   The user sees the reply in green under their note within two seconds, and the pin turns grey. They can
   reopen it.
5. Report back by note number (#n), grouped: what changed, what was answered, what was asked.

`notes.py` never deletes notes. The user's **Clear done** button does.

## 3. Gotchas

- **Start servers with `--detach`.** On Windows it creates the process through WMI (`Win32_Process.Create`),
  outside every shell and job object; servers started with a plain Popen from Git Bash died when a later
  pipeline in the same shell closed. `server.log` in the review folder says "not in a job" when the start is
  clean. WMI does not pass on your environment, so the tool hands the background server its reviews home
  explicitly.
- **Ports 8900-8999**, first free one. `server.json` in the review folder holds the live port. `notes.py`
  restarts a stopped server by itself before it takes shots.
- **CSP:** the annotator and its CSS load from `/__review/` on the page's own origin, so `script-src 'self'`
  allows them. For URL targets the proxy strips `X-Frame-Options`, `frame-ancestors` and
  `upgrade-insecure-requests`, and keeps the rest of the policy. A page whose CSP lacks `'self'` in
  `script-src` shows "the annotator did not start" in its frame.
- **Cloudflare refuses Python's default user agent** (403 on the sitemap). The server sends a browser user agent.
- **A noted element clicked again opens its note**; it does not add a second one. Notes inside a pinned scene
  are the exception: a click at another moment of the scene starts a new note.
- **The phone frame lays out at the full 390 px.** Desktop scrollbars took 15 px and the page laid out at 375 px
  until `ui/frame.css` hid them in that frame. Playwright hides scrollbars by default, which is why the e2e test
  launches with real ones.
- **Scroll-driven pages:** full-page screenshots freeze pinned scenes on their first state. Review them live in
  this tool, never as a stitched screenshot.
- Older stores: the store reads a bare-list `comments.json` and maps the old tags (copy, design, layout and bug
  to Rework; idea to Add).

## 4. Tests

After any change to the tool, run `python <skill dir>/test/regress.py`. It runs the e2e test on
`test/targets.local.json` when that file exists, else on the bundled fixtures. The fixtures are a site with a
pinned scene, a document folder, a single PDF, a dev server and a live URL. Each target runs in a fresh
`zz-test-*` review that is removed afterwards. `--fixtures` forces the bundled set.

One target by hand:

```
node <skill dir>/test/e2e.mjs --base http://127.0.0.1:<port> --store <home>/zz-test-x [--scene .act--mirror --scene-at 0.47] [--view fit --click-sel ".tl span" --text-sel ".tl"]
```

The e2e test needs an empty review (`zz-test-*`) and refuses one that already has notes.

## 5. Limits

- The review server is local. A reviewer on another machine cannot reach it. Send them a deployed preview or a
  PDF instead, and type their answers in as notes.
- PDFs need PyMuPDF (`pip install pymupdf`). Screenshots and tests need Node and `playwright-core`
  (`npm install` in `<skill dir>`) and Chrome or Playwright's Chromium.
