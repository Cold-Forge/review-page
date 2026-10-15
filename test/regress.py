#!/usr/bin/env python3
"""review-page regression: run test/e2e.mjs against every kind of target, each in a fresh zz-test-* review.

    python test/regress.py                 all targets whose source exists on this machine
    python test/regress.py rr pdf          only these

Each target gets a fresh store under D:/WORK/.claude/reviews/zz-test-<key>/, a background server, the e2e run,
then the server is stopped and the store removed (only zz-test-* stores are ever touched). URL targets that are
not reachable (a dev server that is not running) are skipped, not failed.
"""
import os
import shutil
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.dirname(HERE)
sys.path.insert(0, TOOL)
import store as S  # noqa: E402

PDF_ARGS = ['--view', 'fit', '--click-sel', '.tl span', '--text-sel', '.tl']
TARGETS = [
    ('rr', r'D:\WORK\rr-aesthetics\site-wt-beszelgetes\dist', [],
     ['--scene', '.act--mirror', '--scene-at', '0.47', '--text-sel', 'main p']),
    ('docs', r'D:\WORK\rr-aesthetics\as-sent', [], PDF_ARGS),
    ('pdf', r'D:\WORK\rr-aesthetics\as-sent\MI-Terkep_szerzodes-tervezet_RR-Aesthetics.pdf', [], PDF_ARGS),
    ('dev', 'http://127.0.0.1:8891/', [], ['--scene', '.act--mirror', '--scene-at', '0.30', '--text-sel', 'main p']),
    ('live', 'https://rrclinic.hu/', [], ['--text-sel', 'main p']),
    ('mt', r'D:\WORK\mi-terkep-site\_splitstage\site-src\dist', ['--session', 'mt-film-seen=1'], ['--text-sel', 'main p']),
]


def reachable(target):
    if not target.startswith('http'):
        return os.path.exists(target)
    try:
        req = urllib.request.Request(target, headers={'User-Agent': 'Mozilla/5.0 review-page-regress'})
        urllib.request.urlopen(req, timeout=8).close()
        return True
    except Exception:
        return False


def main():
    only = set(sys.argv[1:])
    results = []
    for key, target, review_args, e2e_args in TARGETS:
        if only and key not in only:
            continue
        if not reachable(target):
            results.append((key, 'SKIP', 'not reachable: %s' % target))
            continue
        slug = 'zz-test-%s' % key
        sdir = S.store_dir(slug)
        subprocess.run([sys.executable, os.path.join(TOOL, 'review.py'), '--stop', slug], capture_output=True)
        time.sleep(0.7)                    # let Windows release server.log before the folder goes
        shutil.rmtree(sdir, ignore_errors=True)
        start = subprocess.run([sys.executable, os.path.join(TOOL, 'review.py'), target, '--name', slug,
                                '--detach', '--no-open'] + review_args, capture_output=True, text=True)
        port = S.read_json(S.paths(sdir)['server'], {}).get('port')
        if start.returncode or not port:
            results.append((key, 'FAIL', 'server did not start: %s' % (start.stdout + start.stderr).strip()[-300:]))
            continue
        run = subprocess.run(['node', os.path.join(HERE, 'e2e.mjs'), '--base', 'http://127.0.0.1:%d' % port,
                              '--store', sdir] + e2e_args, capture_output=True, text=True, encoding='utf-8')
        fails = [l for l in run.stdout.splitlines() if l.startswith('FAIL')]
        passes = sum(1 for l in run.stdout.splitlines() if l.startswith('PASS'))
        status = 'PASS' if run.returncode == 0 else 'FAIL'
        detail = '%d checks passed' % passes if status == 'PASS' else '; '.join(fails)[:400] or run.stderr.strip()[-400:]
        results.append((key, status, detail))
        subprocess.run([sys.executable, os.path.join(TOOL, 'review.py'), '--stop', slug], capture_output=True)
        time.sleep(0.7)
        shutil.rmtree(sdir, ignore_errors=True)
        print('%-5s %s  %s' % (key, status, detail), flush=True)
    print('')
    for key, status, detail in results:
        if status == 'SKIP':
            print('%-5s %s  %s' % (key, status, detail))
    bad = [r for r in results if r[1] == 'FAIL']
    print('%d target(s) failed' % len(bad) if bad else 'all targets passed')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
