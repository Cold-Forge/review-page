#!/usr/bin/env python3
"""review-page: the notes store, shared by the server (review.py) and the CLI (notes.py).

One review = one folder under REVIEWS_ROOT (default D:/WORK/.claude/reviews/<slug>/):

    comments.json     the notes; the server and notes.py both edit it under a file lock
    REVIEW-NOTES.md   regenerated on every change; this is what Claude reads
    target.json       what is being reviewed and how to relaunch it
    server.json       port + pid while a server is running for this review
    open-review.cmd   double-click to relaunch the server and open the browser
    shots/            screenshots made by shots.mjs (one per note)
    _pdf/<stem>/      rendered PDF pages (review.py)

Every write goes through mutate(), which re-reads the file under the lock, so a note Claude
closes with notes.py is never overwritten by a browser that still holds an older list.
"""
import hashlib
import io
import json
import os
import time
from contextlib import contextmanager
from datetime import datetime

REVIEWS_ROOT = os.environ.get('REVIEW_PAGE_HOME') or r'D:\WORK\.claude\reviews'

ACTIONS = ['discuss', 'remove', 'rework', 'add', 'comment']     # REVIEW-NOTES.md section order
ACTION_HINT = {
    'discuss': 'interview Dave before touching anything',
    'remove': 'take it out',
    'rework': 'change it as the note says',
    'add': 'something is missing here',
    'comment': 'answer in chat; edit only if the answer implies a change',
}
# marks from older tools: the mi-terkep review-tool tags, doc-review whitespace actions
LEGACY_ACTION = {'copy': 'rework', 'design': 'rework', 'layout': 'rework', 'bug': 'rework',
                 'idea': 'add', 'fill': 'add', 'tighten': 'rework', 'keep': 'comment'}


def store_dir(slug):
    return os.path.join(REVIEWS_ROOT, slug)


def paths(sdir):
    return {
        'comments': os.path.join(sdir, 'comments.json'),
        'notes': os.path.join(sdir, 'REVIEW-NOTES.md'),
        'target': os.path.join(sdir, 'target.json'),
        'server': os.path.join(sdir, 'server.json'),
        'lock': os.path.join(sdir, 'comments.lock'),
        'shots': os.path.join(sdir, 'shots'),
    }


# ---------------------------------------------------------------- locking + io

@contextmanager
def locked(sdir, timeout=8.0):
    """Cross-process lock: an exclusive-create lock file. A lock older than 15 s is stale."""
    lock = paths(sdir)['lock']
    t0 = time.time()
    fd = None
    while fd is None:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except (FileExistsError, PermissionError):   # Windows: a lock being deleted, or an AV scan
            try:
                if time.time() - os.path.getmtime(lock) > 15:
                    os.remove(lock)
                    continue
            except OSError:
                pass
            if time.time() - t0 > timeout:
                raise TimeoutError('review store is locked: %s' % lock)
            time.sleep(0.05)
    try:
        yield
    finally:
        os.close(fd)
        try:
            os.remove(lock)
        except OSError:
            pass


def read_json(path, default):
    try:
        with io.open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, obj):
    tmp = path + '.tmp'
    with io.open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    for attempt in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:         # Windows: a reader holds the file open for a moment
            if attempt == 19:
                raise
            time.sleep(0.05)


def normalise(item):
    act = item.get('action') or LEGACY_ACTION.get(item.get('tag'), item.get('tag'))
    item['action'] = act if act in ACTIONS else 'rework'
    item.setdefault('kind', 'element')
    item.setdefault('status', 'open')
    return item


def load(sdir):
    """{'v': 2, 'rev': int, 'items': [...]}; accepts the mi-terkep tool's bare list."""
    data = read_json(paths(sdir)['comments'], None)
    if isinstance(data, list):
        data = {'v': 2, 'rev': 1, 'items': data}
    if not isinstance(data, dict):
        data = {'v': 2, 'rev': 0, 'items': []}
    data.setdefault('rev', 0)
    items = [normalise(i) for i in data.get('items') or [] if isinstance(i, dict)]
    # older files can lack id / n / viewport. Fill them deterministically (same answer on every
    # read) so the browser can address the note; the first write then stores them for good.
    top = max([int(i.get('n') or 0) for i in items] + [0])
    for i in items:
        if not i.get('id'):
            i['id'] = 'c' + hashlib.md5(json.dumps(i, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()[:16]
        if not i.get('n'):
            top += 1
            i['n'] = top
        i.setdefault('viewport', 'desktop')
    data['items'] = items
    return data


def mutate(sdir, fn):
    """Read, apply fn(data) under the lock, bump rev, write comments.json + REVIEW-NOTES.md."""
    with locked(sdir):
        data = load(sdir)
        result = fn(data)
        data['rev'] = int(data.get('rev') or 0) + 1
        write_json(paths(sdir)['comments'], data)
        write_notes(sdir, data)
        return data, result


def now():
    return datetime.now().astimezone().isoformat(timespec='seconds')


def new_id():
    return 'c' + format(int(time.time() * 1000), 'x') + os.urandom(2).hex()


def next_n(items):
    return max([int(i.get('n') or 0) for i in items] + [0]) + 1


# ---------------------------------------------------------------- operations

BROWSER_FIELDS = ('page', 'viewport', 'vw', 'vh', 'kind', 'action', 'comment', 'label', 'section',
                  'text', 'quote', 'raw', 'offset', 'sel', 'path', 'tagName', 'box', 'rel',
                  'scroll', 'title')


def upsert(sdir, payload):
    def fn(data):
        rec = None
        if payload.get('id'):
            rec = next((i for i in data['items'] if i['id'] == payload['id']), None)
        if rec is None:
            rec = {'id': new_id(), 'n': next_n(data['items']), 'status': 'open', 'ts': now()}
            data['items'].append(rec)
        for k in BROWSER_FIELDS:
            if k in payload:
                rec[k] = payload[k]
        rec['updated'] = now()
        normalise(rec)
        return rec
    return mutate(sdir, fn)


def remove(sdir, ids):
    ids = set(ids)
    def fn(data):
        before = len(data['items'])
        data['items'] = [i for i in data['items'] if i['id'] not in ids]
        return before - len(data['items'])
    return mutate(sdir, fn)


def set_status(sdir, sel, status, reply=None):
    """sel: ids or note numbers. Sets status (open/done) and, optionally, Claude's reply."""
    keys = set(str(s) for s in sel)
    def fn(data):
        hit = []
        for i in data['items']:
            if i['id'] in keys or str(i.get('n')) in keys:
                if status:
                    i['status'] = status
                    if status == 'done':
                        i['doneAt'] = now()
                if reply is not None:
                    i['reply'] = reply
                    i['repliedAt'] = now()
                i['updated'] = now()
                hit.append(i['n'])
        return hit
    return mutate(sdir, fn)


def clear_done(sdir):
    def fn(data):
        before = len(data['items'])
        data['items'] = [i for i in data['items'] if i.get('status') != 'done']
        return before - len(data['items'])
    return mutate(sdir, fn)


# ---------------------------------------------------------------- markdown brief

def where(i):
    """One line that tells a reader exactly where the note sits."""
    bits = ['page `%s`' % (i.get('page') or '/')]
    vp = i.get('viewport') or ''
    if vp and i.get('vw'):
        bits.append('%s %sx%s' % (vp, i['vw'], i.get('vh')))
    elif vp:
        bits.append(vp)
    if i.get('section'):
        bits.append(i['section'])
    sc = i.get('scroll') or {}
    tr = sc.get('track') or {}
    if tr.get('label') is not None and tr.get('progress') is not None:
        bits.append('%s at %d %%' % (tr['label'] or 'pinned scene', round(tr['progress'] * 100)))
    if sc.get('y') is not None:
        bits.append('scroll %d px (%d %% of page)' % (sc['y'], round((sc.get('progress') or 0) * 100)))
    return ' · '.join(b.strip() for b in bits if b and b.strip())


def item_lines(i, done=False):
    out = ['- [%s] **#%s** %s' % ('x' if done else ' ', i.get('n'), where(i))]
    kind = i.get('kind')
    if kind == 'text' and i.get('quote'):
        out.append('  - Selected text: "%s"' % i['quote'][:500])
    if kind == 'box':
        b = i.get('box') or {}
        out.append('  - Area: %d x %d px drawn on %s' % (b.get('w', 0), b.get('h', 0), i.get('label') or 'the page'))
    else:
        out.append('  - Element: %s' % (i.get('label') or '-'))
    if i.get('text') and kind != 'text':
        out.append('  - Element text: "%s"' % i['text'][:200])
    out.append('  - Note: %s' % ((i.get('comment') or '(no note)').replace('\n', '\n    ')))
    if i.get('reply'):
        out.append('  - Claude: %s' % i['reply'].replace('\n', '\n    '))
    if i.get('sel'):
        out.append('  - Selector: `%s`' % i['sel'])
    return out


def write_notes(sdir, data=None):
    data = data or load(sdir)
    target = read_json(paths(sdir)['target'], {})
    items = sorted(data['items'], key=lambda i: int(i.get('n') or 0))
    open_items = [i for i in items if i.get('status') != 'done']
    done_items = [i for i in items if i.get('status') == 'done']
    L = ['# Review notes: %s' % (target.get('name') or os.path.basename(sdir)), '']
    if target:
        L.append('Target: `%s` (%s)' % (target.get('target'), target.get('kind')))
        L.append('Relaunch: `%s`' % target.get('relaunch', ''))
    L.append('Generated %s by review-page. Do not hand-edit; use notes.py to close or answer notes.'
             % datetime.now().strftime('%Y-%m-%d %H:%M'))
    L.append('')
    L.append('**%d open / %d done.** Whatever Dave did not mark is OK.' % (len(open_items), len(done_items)))
    L.append('')
    for act in ACTIONS:
        rows = [i for i in open_items if i.get('action') == act]
        if not rows:
            continue
        L.append('## %s (%d): %s' % (act.upper(), len(rows), ACTION_HINT[act]))
        L.append('')
        for i in rows:
            L.extend(item_lines(i))
            L.append('')
    if done_items:
        L.append('## Done (%d)' % len(done_items))
        L.append('')
        for i in done_items:
            L.extend(item_lines(i, done=True))
            L.append('')
    with io.open(paths(sdir)['notes'], 'w', encoding='utf-8') as f:
        f.write('\n'.join(L))
