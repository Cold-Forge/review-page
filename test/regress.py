#!/usr/bin/env python3
"""review-page regression: run test/e2e.mjs against every kind of target, each in a fresh zz-test-* review.

    python test/regress.py                 every target
    python test/regress.py site pdf        only these keys
    python test/regress.py --fixtures      the bundled fixtures, even when targets.local.json exists

Targets come from test/targets.local.json when it exists (this machine's real projects, kept out of
git; the format is in test/targets.example.json), else from the bundled fixtures in test/fixtures/:
a site with a pinned scene, a folder of documents, a single PDF, the same site through a local dev
server, and a live URL. A target of "@dev-server" serves test/fixtures/site/ on a free local port.

Each target gets a fresh store <reviews home>/zz-test-<key>/, a background server, the e2e run, then
the server is stopped and the store removed (only zz-test-* stores are ever touched). Targets that
are not reachable (a dev server that is not running, no network, no PyMuPDF for a PDF) are skipped,
not failed.
"""
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.dirname(HERE)
sys.path.insert(0, TOOL)
import store as S  # noqa: E402

FIXTURES = os.path.join(HERE, 'fixtures')
LOCAL_TARGETS = os.path.join(HERE, 'targets.local.json')
PDF_ARGS = ['--view', 'fit', '--click-sel', '.tl span', '--text-sel', '.tl']
SCENE_ARGS = ['--scene', '.scene', '--scene-at', '0.47', '--text-sel', 'main p']
BUILTIN = [
    {'key': 'site', 'target': os.path.join(FIXTURES, 'site'), 'e2e_args': SCENE_ARGS},
    {'key': 'docs', 'target': os.path.join(FIXTURES, 'docs'), 'e2e_args': PDF_ARGS},
    {'key': 'pdf', 'target': os.path.join(FIXTURES, 'docs', 'brief.pdf'), 'e2e_args': PDF_ARGS},
    {'key': 'dev', 'target': '@dev-server', 'e2e_args': SCENE_ARGS},
    # the first web page: static since 1992, plain HTML, same-origin links to browse
    {'key': 'live', 'target': 'https://info.cern.ch/hypertext/WWW/TheProject.html', 'e2e_args': ['--text-sel', 'p']},
]


def load_targets(fixtures_only):
    if fixtures_only or not os.path.exists(LOCAL_TARGETS):
        return BUILTIN, 'bundled fixtures'
    with io.open(LOCAL_TARGETS, encoding='utf-8-sig') as f:
        targets = json.load(f)
    if not isinstance(targets, list) or not all(isinstance(t, dict) and t.get('key') and t.get('target')
                                                for t in targets):
        sys.exit('regress: %s must be a list of {"key", "target", "review_args", "e2e_args"}' % LOCAL_TARGETS)
    return targets, LOCAL_TARGETS


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def start_dev_server():
    """The fixture site behind a plain local HTTP server, reviewed as a URL target."""
    port = free_port()
    proc = subprocess.Popen([sys.executable, '-m', 'http.server', str(port), '--bind', '127.0.0.1',
                             '--directory', os.path.join(FIXTURES, 'site')],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = 'http://127.0.0.1:%d/' % port
    for _ in range(40):
        if reachable(url):
            break
        time.sleep(0.25)
    return proc, url


def has_pymupdf():
    try:
        import fitz  # noqa: F401
        return True
    except ImportError:
        return False


def reachable(target):
    if not target.startswith('http'):
        return os.path.exists(target)
    try:
        req = urllib.request.Request(target, headers={'User-Agent': 'Mozilla/5.0 review-page-regress'})
        urllib.request.urlopen(req, timeout=8).close()
        return True
    except Exception:
        return False


def needs_pdf(target, e2e_args):
    return target.lower().endswith('.pdf') or e2e_args == PDF_ARGS


def stop_and_clear(slug, sdir):
    subprocess.run([sys.executable, os.path.join(TOOL, 'review.py'), '--stop', slug], capture_output=True)
    time.sleep(0.7)                    # let Windows release server.log before the folder goes
    shutil.rmtree(sdir, ignore_errors=True)


def run_target(t, env):
    key, target = t['key'], t['target']
    review_args, e2e_args = t.get('review_args') or [], t.get('e2e_args') or []
    if needs_pdf(target, e2e_args) and not has_pymupdf():
        return 'SKIP', 'PyMuPDF is not installed (pip install pymupdf)'
    if not reachable(target):
        return 'SKIP', 'not reachable: %s' % target
    slug = 'zz-test-%s' % key
    sdir = S.store_dir(slug)
    stop_and_clear(slug, sdir)
    start = subprocess.run([sys.executable, os.path.join(TOOL, 'review.py'), target, '--name', slug,
                            '--detach', '--no-open'] + review_args, capture_output=True, text=True)
    port = S.read_json(S.paths(sdir)['server'], {}).get('port')
    if start.returncode or not port:      # the store stays, with its server.log, until the next run
        return 'FAIL', 'server did not start: %s' % (start.stdout + start.stderr).strip()[-300:]
    run = subprocess.run(['node', os.path.join(HERE, 'e2e.mjs'), '--base', 'http://127.0.0.1:%d' % port,
                          '--store', sdir] + e2e_args, capture_output=True, text=True, encoding='utf-8', env=env)
    fails = [ln for ln in run.stdout.splitlines() if ln.startswith('FAIL')]
    passes = sum(1 for ln in run.stdout.splitlines() if ln.startswith('PASS'))
    stop_and_clear(slug, sdir)
    if run.returncode == 0:
        return 'PASS', '%d checks passed' % passes
    return 'FAIL', '; '.join(fails)[:400] or run.stderr.strip()[-400:]


def main():
    args = sys.argv[1:]
    targets, source = load_targets('--fixtures' in args)
    only = set(a for a in args if not a.startswith('--'))
    print('targets: %s\nreviews home: %s\n' % (source, S.REVIEWS_ROOT), flush=True)
    env = dict(os.environ, REVIEW_PAGE_PYTHON=sys.executable)
    dev = None
    results = []
    try:
        for t in targets:
            if only and t['key'] not in only:
                continue
            if t['target'] == '@dev-server':
                if not dev:
                    dev = start_dev_server()
                t = dict(t, target=dev[1])
            status, detail = run_target(t, env)
            results.append((t['key'], status, detail))
            if status != 'SKIP':
                print('%-5s %s  %s' % (t['key'], status, detail), flush=True)
    finally:
        if dev:
            dev[0].terminate()
    print('')
    for key, status, detail in results:
        if status == 'SKIP':
            print('%-5s %s  %s' % (key, status, detail))
    bad = [r for r in results if r[1] == 'FAIL']
    print('%d target(s) failed' % len(bad) if bad else 'all targets passed')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
