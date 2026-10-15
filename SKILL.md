---
name: review-page
description: "Dave's review loop for anything he should look at: a built site, a scroll-driven page, an HTML document, a PDF, a folder of deliverables, a dev server or a live URL. Replaced doc-review on 2026-10-15. Triggers: review page, i need a review page, review copy, reviewable, mark it up, click-to-comment, review notes, REVIEW-NOTES, feedback.json, feedback.md, ingest feedback, doc-review, review.html, let me review it. Starts a local review server (D:/WORK/tools/review-page/review.py) with the real pages in desktop + phone frames; Dave clicks elements, boxes areas or selects text and picks Remove / Rework / Comment / Discuss / Add; every note lands on disk at once with its scroll moment. This skill also defines how the follow-up turn reads, answers and closes the notes (notes.py), and the offline copy for sending to a client."
---

# review-page (replaced doc-review 2026-10-15)

Dave, 2026-10-15: *"i want doc-review replaced by what you built for mi-terkep as a general skill applicable to
documents and html files and sites"*. The base is the MI-Térkép click-to-comment tool (2026-08-29), generalised.
doc-review's static copy survives only as the **send-to-someone-else** mode (below).

Tool: `D:\WORK\tools\review-page\` (`review.py` server, `store.py` notes store, `notes.py` Claude's CLI,
`shots.mjs` per-note screenshots, `ui\` review screen + in-frame annotator, `test\e2e.mjs`, `README.md`).
Notes: `D:\WORK\.claude\reviews\<slug>\` (`REVIEW-NOTES.md` is what you read; `comments.json` is the data).

## 1. Start a review (every deliverable Dave should look at)

One command, any target. `--detach` keeps the server alive after this session ends; leave `--no-open` off when
Dave is at the keyboard so his browser opens on it.

```
python D:\WORK\tools\review-page\review.py <target> --name <slug> --detach
```

| Target | What Dave gets | Default frames |
|---|---|---|
| built site folder (`dist\` with `index.html`) | every page, with a page picker | Desktop 1440x900 + Phone 390x844 side by side |
| folder of deliverables (no `index.html`) | every PDF (first) and HTML in it | Fit |
| `<doc>.html` | the document; a same-name `<doc>.pdf` opens first, as pages | Fit |
| `<doc>.pdf` | the PDF as pages with a selectable text layer | Fit |
| `http://127.0.0.1:<port>/` (dev server) | the dev server through one origin, its real CSP kept | Desktop + Phone |
| `https://live-site/` | the live site, pages from its sitemap; POST/PUT/DELETE blocked | Desktop + Phone |

- `--name` = the store folder; reuse the same name for every round of the same deliverable so notes carry over.
- A once-per-session intro or cookie wall: `--session KEY=VALUE` / `--local KEY=VALUE` presets storage
  (MI-Térkép: `--session mt-film-seen=1`).
- Relaunch later: `python review.py --resume <slug> --detach`, or Dave double-clicks
  `D:\WORK\.claude\reviews\<slug>\open-review.cmd`. Stop: `python review.py --stop <slug>`.
- `python D:\WORK\tools\review-page\notes.py` lists every review, its open/done counts and whether it is running.
- Use the dev-server URL instead of `dist\` when the page needs its real headers or functions (CSP, `_headers`,
  Pages Functions). The static server ignores `_headers`.

Hand Dave the URL the command prints (and the slug). Say this once per new review, short:

> **C** click an element · **V** box any area · **T** select text · **B** browse normally. In the note:
> Enter saves, Shift+Enter new line, Alt+1-5 picks **1 Remove · 2 Rework · 3 Comment · 4 Discuss · 5 Add**.
> Every note is on disk the moment you save it, no export. Unmarked = OK. Tell me when you are done.

## 2. Read the notes (the follow-up turn)

```
python D:\WORK\tools\review-page\notes.py <slug>            # the work list, grouped by action, DISCUSS first
python D:\WORK\tools\review-page\notes.py <slug> shots      # one PNG per open note at its viewport + scroll moment
```

Read the shots (`<store>\shots\n-<n>.png`) before acting on anything visual: each note is reproduced at the exact
scroll position Dave wrote it, with the area outlined. For a pinned scroll scene the note also carries the scene
and its progress ("act--mirror at 47 %"), so "the mirror" means that moment, not the section.

1. **DISCUSS first.** Ask each Discuss note with AskUserQuestion (up to 4 per block, recommended option first),
   plus the judgment calls the notes imply. Then act.
2. **REMOVE / REWORK / ADD** go into the builder source, never by hand into generated HTML. Rebuild. The open
   review shows a "Page rebuilt: reload" button by itself when the reviewed file changes.
3. **COMMENT** is answered with a reply, not in chat only: `notes.py <slug> reply <n> "answer"`. If the answer
   implies a change, treat it as REWORK.
4. Close each note you handled, with what changed:
   `notes.py <slug> done 3 5 8 --reply "Headline shortened to one line (commit abc123)"`.
   Dave sees the reply in green under his note within two seconds and the pin turns grey; he can reopen it.
5. Hungarian client copy: follow the `hungarian-content` skill and the GPT-6 Sol flag check on changed strings.
6. Report back by note number (#n), grouped: what changed, what was answered, what was asked.

`notes.py` never deletes notes; Dave's **Clear done** button does.

## 3. Sending a review to someone else (client, colleague)

The live tool needs the local server, so it cannot be mailed. For a reviewer outside this machine, build the
offline copy with the old static generator (still maintained, used by the audit and RR build scripts):

```
python D:/WORK/tools/doc-review/pages.py <doc>.html <doc>.pdf      # -> <doc>.review.html, works from file://
```

They mark with V / T / S and the four pointers, then press **E** to export `<doc>.feedback.json` + `.md`
(verify the export exists before reading "no marks" as "no feedback": a client once forgot to press E).
Ingest with `python D:/WORK/tools/doc-review/ingest.py <doc>.feedback.json`, then follow section 2.
The review copy is generated: never commit it.

## 4. Gotchas (all hit while building it)

- **Start servers with `--detach`.** It creates the process through WMI (`Win32_Process.Create`), outside every
  shell and job. Servers started with plain Popen from Git Bash died when a later pipeline in the same shell
  closed. `server.log` in the store says "not in a job" when the start is clean.
- **Ports 8900-8999**, first free one. `server.json` in the store holds the live port; `notes.py` restarts a
  stopped server by itself before taking shots.
- **CSP:** the annotator and its CSS load from `/__review/` on the page's own origin, so `script-src 'self'`
  allows them. For URL targets the proxy strips `X-Frame-Options`, `frame-ancestors` and
  `upgrade-insecure-requests`, and keeps the rest of the policy. A page whose CSP lacks `'self'` in
  `script-src` shows "the annotator did not start" in its frame.
- **Cloudflare refuses Python's default user agent** (403 on the sitemap). The server sends a browser UA.
- **A noted element clicked again opens its note**, it does not add a second one. Scroll-bound notes (inside a
  pinned scene) are the exception: a click at another moment of the scene starts a new note.
- **The e2e test needs an empty store** (`zz-test-*`), and refuses a store that already has notes.
- Old exports: the store reads the MI-Térkép tool's bare-list `comments.json` and maps its tags
  (copy/design/layout/bug to Rework, idea to Add).

Regression after any change to the tool: `python D:\WORK\tools\review-page\test\regress.py` runs the e2e test
on all six target kinds (site with a pinned scene, document folder, single PDF, dev server, live URL, MI-Térkép
with a storage preset), each in a fresh `zz-test-*` review, and cleans up after itself. One target by hand:

```
node D:\WORK\tools\review-page\test\e2e.mjs --base http://127.0.0.1:<port> --store D:\WORK\.claude\reviews\zz-test-x [--scene .act--mirror --scene-at 0.47] [--view fit --click-sel ".tl span" --text-sel ".tl"]
```

## 5. What Dave's marks taught (documents; apply before he has to mark it again)

- No version marks in client documents ("3. változat", "v3", "melléklet a … tervhez"): the client sees one document; versioning is local only.
- Never mention the consultant's fee, effort, weeks or "my price" in a client plan; only the client's own costs.
- One name per thing, everywhere ("Kapocs", never "gerinc"); no "csoportrekord"-style calques; "nyolc óra" reads as hours, write "nyolc határidő".
- Every idea page in the same structure: title · pain · category (fixed set) · tools · technology in one sentence · cost to them · value ·
  sketch · how it works, ELI5 · numbered questions (K1…), collected again at the end (Google Form later).
- Do not pitch what the client just bought and has not received; do not touch the site vendor's or a friend's bread; do not "sell" a course
  the client has not been told about; no quotes from the workshop as section hooks.
- The running head must not sit on the cover; the closing dark band must reach the physical page bottom (3-pass render:
  cover / body / end page, footer + page numbers drawn by PyMuPDF; see `followup/terv/render_terv.py`).
- A page that holds only a question box or a caption is a defect: float the sketch (`fig.half`) or trim, then re-check page fill
  (`followup/terv/pagecheck.py` pattern: lowest body-text y per page, footer excluded, flag < 45 %).
- **No person names at all** in a client document; roles only ("a képzésszervező", "ti"). **Never assume adoption**:
  every idea's question list opens with "kell-e ez nektek egyáltalán?", questions never presuppose a yes ("Ha ezt az irányt választjátok…"),
  the intro says it is an idea list, not a plan. **Every number about the client carries its source** (headcount, pages, volumes): if the
  only source is a website crawl or a misread workshop line, say so or ask. **No spoilers into a partner's domain** (the site vendor's, a
  friend's). A label-only category chip ("Alap") with no legend reads as noise: put a reading guide before the first idea page. A crowded
  3-column meta grid reads worse than full-width label rows. **Dave asks for the maximum automation with modularity** when a step is left
  manual ("cant we automate this?"): design the full round trip with a swappable connector and say which mode runs today.
- Scroll-driven pages: full-page screenshots freeze pinned scenes on their first state. Review them live in this tool, never as a
  stitched screenshot (2026-10-15, the RR „Beszélgetés" mirror).
