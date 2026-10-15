# review-page

Click-to-comment review of a built site, a scroll-driven page, an HTML document, a PDF, a folder of
deliverables, a dev server or a live URL. Notes land on disk the moment they are saved; Claude reads them,
answers them and closes them from the command line, and the open review shows that within two seconds.

It replaced doc-review on 2026-10-15. It grew out of the MI-Térkép click-to-comment tool
(`D:\WORK\mi-terkep-site\review-tool\`, 2026-08-29), which stays where it is for that project.
The procedure lives in the skill: `D:\.claude\skills\review-page\SKILL.md`.

## Start

```
python D:\WORK\tools\review-page\review.py <folder | file.html | file.pdf | http(s)://url> --name <slug> --detach
python D:\WORK\tools\review-page\review.py --resume <slug> --detach      # relaunch with the saved settings
python D:\WORK\tools\review-page\review.py --stop <slug>
```

Options: `--no-open` (no browser), `--port N`, `--session KEY=VALUE` / `--local KEY=VALUE` (storage presets,
e.g. to skip a once-per-session intro), `--allow-post` (URL targets only; POST/PUT/PATCH/DELETE are blocked by
default so a review never submits a form on a real site).

The server serves the reviewed pages at `/` and the tool at `/__review/` on one origin (ports 8900-8999), so
the tool reaches into each preview frame and anchors notes to real elements. URL targets go through a small
proxy: absolute links to the site are rewritten to stay on the review origin, `X-Frame-Options`,
`frame-ancestors` and `upgrade-insecure-requests` are dropped, and the rest of the CSP is kept. PDFs are
rendered with PyMuPDF to page images plus a transparent, selectable text layer, cached in the store.

## Review (Dave)

- **C** Click: hover names each element, click it to write a note. Alt takes the parent block.
- **V** Box: drag over any area (a canvas moment, part of an image, a PDF region, a gap).
- **T** Text: select words; the note quotes them exactly.
- **B** Browse: the page works normally; the other frame follows the navigation.
- In the note: Enter saves, Shift+Enter new line, Esc closes, Alt+1-5 picks
  1 Remove · 2 Rework · 3 Comment · 4 Discuss · 5 Add.
- Frames: Both (Desktop 1440x900 + Phone 390x844, true sizes scaled to fit), Desktop, Mobile, Fit (fills the stage, 1:1).
- Every note records the scroll position and, inside a pinned (sticky) scene, how far through it. Clicking a
  note in the list scrolls the page back to that moment.

## Notes (Claude)

```
python D:\WORK\tools\review-page\notes.py                         # every review: counts, running URL, target
python D:\WORK\tools\review-page\notes.py <slug>                  # work list (REVIEW-NOTES.md)
python D:\WORK\tools\review-page\notes.py <slug> shots [n ...]    # PNG per open note at its scroll moment
python D:\WORK\tools\review-page\notes.py <slug> reply <n> "answer"
python D:\WORK\tools\review-page\notes.py <slug> done <n> [n ...] --reply "what changed"
python D:\WORK\tools\review-page\notes.py <slug> reopen <n>
```

Store: `D:\WORK\.claude\reviews\<slug>\` (`comments.json`, `REVIEW-NOTES.md`, `target.json`, `server.json`,
`server.log`, `open-review.cmd`, `shots\`, `_pdf\`). Writes go through a lock file, so the browser and
`notes.py` never overwrite each other.

## Files

| File | Job |
|---|---|
| `review.py` | target detection, static + PDF + proxy server, JSON API, WMI background start |
| `store.py` | notes store: lock, upsert, status, the REVIEW-NOTES.md writer |
| `notes.py` | Claude's CLI |
| `shots.mjs` | Playwright screenshots of notes (playwright-core from `D:\WORK\package.json`, installed Chrome) |
| `ui\review.html` | the review screen (frames, tools, notes list, polling) |
| `ui\annotator.js`, `ui\annotator.css` | injected into each frame: hover, click, box, text, pins, scroll capture |
| `test\e2e.mjs` | end-to-end test with a real mouse; needs an empty `zz-test-*` store |
| `test\regress.py` | runs `e2e.mjs` on all six target kinds, each in a fresh `zz-test-*` review, then cleans up |

## Tested 2026-10-15

`python D:\WORK\tools\review-page\test\regress.py` (about 4 minutes) after any change.

All checks of `test\e2e.mjs` pass on: the RR concept build (`dist\`, pinned mirror noted at 47 % and restored
to the pixel), the RR `as-sent` document folder, a single PDF, the RR dev server under its real CSP, the live
rrclinic.hu (38 pages from the sitemap, POST blocked with 403), and the MI-Térkép split-stage build with
`--session mt-film-seen=1`. A 40-page PDF renders in 5.6 s.
