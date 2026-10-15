#!/usr/bin/env python3
"""review-page: Claude's side of a review. Read the notes, answer them, close them, see them.

    python notes.py                              every review: open/done counts, running URL, target
    python notes.py <slug>                       the work list (REVIEW-NOTES.md, rebuilt fresh)
    python notes.py <slug> done <n> [<n> ...] [--reply "what changed"]
    python notes.py <slug> reply <n> "answer"    answer a note without closing it
    python notes.py <slug> reopen <n> [<n> ...]
    python notes.py <slug> shots [<n> ...]       screenshot each open note (or the given ones) at its
                                                 viewport and scroll moment, outlined, into <store>/shots/
    python notes.py <slug> url                   the running review URL, or start it in the background

<slug> is the review's folder name under D:/WORK/.claude/reviews/ (a unique part of it is enough),
or a path to a review folder. Replies and closed notes show up in Dave's open review within two
seconds; he sees "Claude: ..." under his note and the pin turns grey.
"""
import io
import os
import subprocess
import sys

TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOL_DIR)
import store as S  # noqa: E402
from review import review_url, running_port  # noqa: E402


def find(arg):
    if os.path.isfile(os.path.join(arg, 'target.json')):
        return os.path.abspath(arg)
    exact = S.store_dir(arg)
    if os.path.isdir(exact):
        return exact
    if os.path.isdir(S.REVIEWS_ROOT):
        hits = [d for d in os.listdir(S.REVIEWS_ROOT) if arg.lower() in d.lower()
                and os.path.isdir(os.path.join(S.REVIEWS_ROOT, d))]
        if len(hits) == 1:
            return S.store_dir(hits[0])
        if hits:
            sys.exit('notes.py: "%s" matches several reviews: %s' % (arg, ', '.join(sorted(hits))))
    sys.exit('notes.py: no review called "%s" under %s' % (arg, S.REVIEWS_ROOT))


def slug_of(sdir):
    return os.path.basename(sdir.rstrip('\\/'))


def ensure_server(sdir):
    slug = slug_of(sdir)
    port = running_port(sdir, slug)
    if port:
        return port
    subprocess.run([sys.executable, os.path.join(TOOL_DIR, 'review.py'), '--resume', slug, '--detach', '--no-open'],
                   check=True)
    port = running_port(sdir, slug)
    if not port:
        sys.exit('notes.py: could not start the review server for %s' % slug)
    return port


def list_reviews():
    if not os.path.isdir(S.REVIEWS_ROOT):
        print('no reviews yet (%s)' % S.REVIEWS_ROOT)
        return
    rows = []
    for d in sorted(os.listdir(S.REVIEWS_ROOT)):
        sdir = S.store_dir(d)
        t = S.read_json(S.paths(sdir)['target'], None)
        if not t:
            continue
        items = S.load(sdir)['items']
        op = sum(1 for i in items if i.get('status') != 'done')
        port = running_port(sdir, d)
        rows.append((t.get('updated', ''), d, op, len(items) - op, port, t.get('target')))
    for upd, d, op, dn, port, tgt in sorted(rows, reverse=True):
        run = review_url(port) if port else 'stopped'
        print('%-34s %3d open %3d done  %-34s %s' % (d, op, dn, run, tgt))


def report(verb, hit):
    print('%s: %s' % (verb, ', '.join('#%s' % n for n in hit) or 'nothing matched'))


def main():
    a = sys.argv[1:]
    if not a:
        list_reviews()
        return
    if a[0] in ('-h', '--help'):
        print(__doc__)
        return
    sdir = find(a[0])
    cmd = a[1] if len(a) > 1 else 'show'
    rest = a[2:]
    reply = None
    if '--reply' in rest:
        k = rest.index('--reply')
        reply = rest[k + 1] if k + 1 < len(rest) else ''
        rest = rest[:k] + rest[k + 2:]

    if cmd == 'show':
        with S.locked(sdir):        # a browser save may be writing the same files right now
            S.write_notes(sdir)
            with io.open(S.paths(sdir)['notes'], encoding='utf-8') as f:
                print(f.read())
    elif cmd == 'done':
        _, hit = S.set_status(sdir, rest, 'done', reply)
        report('done', hit)
    elif cmd == 'reopen':
        _, hit = S.set_status(sdir, rest, 'open', reply)
        report('reopened', hit)
    elif cmd == 'reply':
        if len(rest) < 2:
            sys.exit('usage: notes.py <slug> reply <n> "answer"')
        _, hit = S.set_status(sdir, [rest[0]], None, ' '.join(rest[1:]))
        report('answered', hit)
    elif cmd == 'url':
        print(review_url(ensure_server(sdir)))
    elif cmd == 'shots':
        port = ensure_server(sdir)
        args = ['node', os.path.join(TOOL_DIR, 'shots.mjs'), '--base', 'http://127.0.0.1:%d' % port, '--store', sdir]
        if rest:
            args += ['--n', ','.join(rest)]
        sys.exit(subprocess.run(args).returncode)
    else:
        sys.exit('notes.py: unknown command "%s" (show, done, reply, reopen, shots, url)' % cmd)


if __name__ == '__main__':
    main()
