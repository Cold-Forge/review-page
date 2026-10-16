# review-page

Click-to-comment review of a built site, a scroll-driven page, an HTML document, a PDF, a folder of
deliverables, a dev server or a live URL. The reviewer clicks elements, boxes areas or selects text
and writes a note. Each note is written to disk as soon as it is saved, so there is no export step.
Claude (or any script) reads the notes, answers them and closes them from the command line, and
the open review shows the answer within two seconds.

The repository is also a Claude Code skill: `SKILL.md` holds the review loop that Claude follows.

## Requirements

- Python 3.9 or later (tested on 3.11). The server uses only the standard library.
- PyMuPDF (`pip install pymupdf`), only when you review PDFs.
- Node 18 or later and `playwright-core`, only for the note screenshots and the tests
  (`npm install` in this folder).
- Google Chrome, or Playwright's own Chromium (`npx playwright install chromium`), for the same.

## Install

```
git clone https://github.com/Cold-Forge/review-page.git
cd review-page
npm install                  # screenshots and tests only
```

To use it as a Claude Code skill, clone it into your skills folder (for example
`~/.claude/skills/review-page`), or copy `SKILL.md` into a skill folder of its own and point its
paths at the clone.

## Start a review

```
python review.py <folder | file.html | file.pdf | http(s)://url> --name <slug> --detach
python review.py --resume <slug> --detach      # relaunch with the saved settings
python review.py --stop <slug>
```

| Target | What the reviewer gets | Default frames |
|---|---|---|
| built site folder (`dist/` with `index.html`) | every page, with a page picker | Desktop 1440x900 and Phone 390x844 |
| folder of documents (no `index.html`) | every PDF (first) and HTML file in it | Fit |
| `doc.html` | the document; a same-name `doc.pdf` opens first, as pages | Fit |
| `doc.pdf` | the PDF as page images with a selectable text layer | Fit |
| `http://127.0.0.1:<port>/` | a dev server through one origin, its CSP kept | Desktop and Phone |
| `https://site/` | a live site, pages from its sitemap; POST/PUT/PATCH/DELETE blocked | Desktop and Phone |

Options:

- `--detach` starts the server in the background, so it keeps running after the console closes.
- `--no-open` does not open the browser.
- `--port N` picks the port. The default is the first free port in 8900-8999.
- `--session KEY=VALUE` and `--local KEY=VALUE` preset sessionStorage or localStorage, for example
  to skip an intro that plays once per session.
- `--allow-post` lets a URL target submit forms. Without it, a review never submits a form on a
  real site.
- `--home DIR` sets the reviews home for this run.

The server serves the reviewed pages at `/` and the tool at `/__review/` on one origin, so the tool
can reach into each preview frame and anchor notes to real elements. URL targets go through a small
proxy. It rewrites absolute links to the site so they stay on the review origin. It drops
`X-Frame-Options`, `frame-ancestors` and `upgrade-insecure-requests`, and keeps the rest of the CSP.
PDFs render with PyMuPDF to page images with a transparent, selectable text layer, cached in the
store.

## Review (the reviewer)

- **C** Click: hover names each element; click it to write a note. Alt takes the parent block.
- **V** Box: drag over any area (a canvas moment, part of an image, a PDF region, a gap).
- **T** Text: select words; the note quotes them exactly.
- **B** Browse: the page works normally; the other frame follows the navigation.
- In the note: Enter saves, Shift+Enter starts a new line, Esc closes, and Alt+1-5 picks
  1 Remove, 2 Rework, 3 Comment, 4 Discuss, 5 Add.
- Frames: Both (Desktop 1440x900 and Phone 390x844, true sizes scaled to fit), Desktop, Mobile,
  and Fit (fills the stage at 1:1).
- Every note records the scroll position. Inside a pinned (sticky) scene, it also records how far
  through the scene the page was. Clicking a note in the list scrolls the page back to that moment.

## Notes (Claude)

```
python notes.py                         # every review: counts, running URL, target
python notes.py <slug>                  # the work list (REVIEW-NOTES.md, Discuss first)
python notes.py <slug> shots [n ...]    # a PNG per open note at its viewport and scroll moment
python notes.py <slug> reply <n> "answer"
python notes.py <slug> done <n> [n ...] --reply "what changed"
python notes.py <slug> reopen <n>
```

Each review is one folder in the reviews home: `comments.json`, `REVIEW-NOTES.md`, `target.json`,
`server.json`, `server.log`, `open-review.cmd` (Windows) or `open-review.sh`, `shots/` and `_pdf/`.
Every write goes through a lock file, so the browser and `notes.py` never overwrite each other.

## Configuration

Settings for one machine go in `config.local.json` next to `review.py`. Git ignores that file. All
keys are optional; `config.example.json` shows the format.

| Key | Environment variable | Default | Meaning |
|---|---|---|---|
| `home` | `REVIEW_PAGE_HOME` | `~/.review-page/reviews` | where the reviews are stored |
| `reviewer` | | `the reviewer` | the name REVIEW-NOTES.md uses for the person who marks |
| `chrome` | `REVIEW_PAGE_CHROME` | installed Chrome, then Playwright's Chromium | browser for screenshots and tests |

The order for the reviews home is: `--home`, then `REVIEW_PAGE_HOME`, then `home` in the file,
then the default. On Windows, `--detach` starts the server through WMI, and WMI does not pass on
your environment. The tool therefore gives the background server the home explicitly, and each
relaunch script carries it too.

## Tests

```
python test/regress.py              # test/targets.local.json if it exists, else the bundled fixtures
python test/regress.py --fixtures   # the bundled fixtures
python test/regress.py site pdf     # only these keys
```

`test/regress.py` runs `test/e2e.mjs` on each target in a fresh `zz-test-*` review, then stops the
server and removes that review. The e2e test drives the real review screen headless with a real
mouse. It clicks, boxes, selects text, notes a pinned scene at a set moment, closes a note from
`notes.py`, reloads, and browses.

The bundled fixtures in `test/fixtures/` cover each kind of target:

- a site with a pinned scene
- a folder of documents
- a single PDF
- the same site behind a local dev server
- a live URL: `info.cern.ch`, the first web page, unchanged since 1992

A target that cannot be reached is skipped, not failed. To test against your own projects, copy
`test/targets.example.json` to `test/targets.local.json` and edit it. `test/fixtures/make_pdf.py`
regenerates the PDF fixture.

## Files

| File | Job |
|---|---|
| `review.py` | target detection, static, PDF and proxy server, JSON API, background start |
| `store.py` | notes store: configuration, lock, upsert, status, the REVIEW-NOTES.md writer |
| `notes.py` | Claude's command line |
| `shots.mjs` | screenshots of notes at their scroll moment |
| `browser.mjs` | finds playwright-core and a browser for `shots.mjs` and the tests |
| `ui/review.html` | the review screen: frames, tools, notes list, polling |
| `ui/annotator.js`, `ui/annotator.css` | injected into each frame: hover, click, box, text, pins, scroll capture |
| `ui/frame.css` | frame layout fixes, such as the phone frame's full 390 px width |
| `test/e2e.mjs` | end-to-end test; needs an empty `zz-test-*` review |
| `test/regress.py` | runs `e2e.mjs` on every target |
| `SKILL.md` | the Claude Code skill: how Claude runs the review loop |
