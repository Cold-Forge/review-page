#!/usr/bin/env python3
"""review-page: click-to-comment review of a built site, an HTML file, a PDF, or any URL.

    python review.py <target> [--name SLUG] [--detach] [--no-open] [--port N]
                              [--session KEY=VALUE ...] [--local KEY=VALUE ...] [--allow-post]
    python review.py --resume <slug> [--detach]     relaunch a review with its saved settings
    python review.py --stop <slug>                  stop the server of a review

<target> is one of:
    a folder            a built site (dist/) or a folder of documents: every .html and .pdf in it
    a .html file        that file plus its siblings; a same-name .pdf opens first, as pages
    a .pdf file         the PDF as pages with a selectable text layer (plus a same-name .html)
    an http(s) URL      a dev server or a live site, passed through on one local origin

The server puts the reviewed pages at "/" and the tool at "/__review/" on ONE origin, so the tool
can reach into each preview frame and anchor notes to real elements. Notes land in
<reviews home>/<slug>/ (comments.json + REVIEW-NOTES.md) on every click; there is no export step.
The reviews home is $REVIEW_PAGE_HOME, else "home" in config.local.json, else ~/.review-page/reviews.
--detach starts the server in the background so it outlives this console; open-review.cmd
(Windows) or open-review.sh in the store folder relaunches it later.

--session / --local preset sessionStorage / localStorage on the review origin before the frames
load (e.g. --session mt-film-seen=1 skips a once-per-session intro). URL targets block POST, PUT,
PATCH and DELETE unless --allow-post, so reviewing a live site can never submit its forms.
"""
import argparse
import codecs
import gzip
import html as H
import http.client
import io
import json
import mimetypes
import os
import re
import socket
import ssl
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
import webbrowser
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOL_DIR)
import store as S  # noqa: E402

UI_DIR = os.path.join(TOOL_DIR, 'ui')
PORT_RANGE = range(8900, 9000)
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) review-page'   # Cloudflare refuses Python's default

MIME = {
    '.html': 'text/html; charset=utf-8', '.htm': 'text/html; charset=utf-8',
    '.js': 'text/javascript; charset=utf-8', '.mjs': 'text/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8', '.json': 'application/json; charset=utf-8',
    '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
    '.webp': 'image/webp', '.avif': 'image/avif', '.gif': 'image/gif', '.ico': 'image/x-icon',
    '.mp4': 'video/mp4', '.webm': 'video/webm', '.mp3': 'audio/mpeg', '.wav': 'audio/wav',
    '.woff2': 'font/woff2', '.woff': 'font/woff', '.ttf': 'font/ttf', '.otf': 'font/otf',
    '.pdf': 'application/pdf', '.txt': 'text/plain; charset=utf-8', '.xml': 'application/xml',
    '.xsl': 'text/xsl', '.webmanifest': 'application/manifest+json', '.wasm': 'application/wasm',
}


def mime_of(path):
    ext = os.path.splitext(path)[1].lower()
    return MIME.get(ext) or mimetypes.guess_type(path)[0] or 'application/octet-stream'


def slugify(s):
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')[:60] or 'review'


def review_url(port):
    return 'http://127.0.0.1:%d/__review/' % port


def path_and_query(parts):
    """'/path?query' of a urlsplit() result."""
    return (parts.path or '/') + ('?' + parts.query if parts.query else '')


def kv_list(pairs):
    out = {}
    for p in pairs or []:
        k, _, v = p.partition('=')
        if k:
            out[k] = v
    return out


def html_title(path):
    try:
        with io.open(path, encoding='utf-8', errors='ignore') as f:
            head = f.read(65536)
        m = re.search(r'<title[^>]*>(.*?)</title>', head, re.I | re.S)
        return H.unescape(re.sub(r'\s+', ' ', m.group(1))).strip()[:80] if m else ''
    except OSError:
        return ''


# ======================================================================= the target

class Target:
    """What is being reviewed: mounts, page list, and (for URLs) the upstream origin."""

    def __init__(self, raw, kind):
        self.raw = raw
        self.kind = kind            # site | docs (a folder without index.html) | html | pdf | url
        self.root = None            # folder served at "/" (site / html / pdf twin)
        self.pdfs = {}              # key -> absolute pdf path, served at /__pdf/<key>/
        self.upstream = None        # url targets: scheme://host[:port] after redirects
        self.hosts = set()          # upstream host names whose absolute URLs get rewritten
        self.start = '/'
        self.pages = []             # [{url, name, kind, view}]

    # ---- local files
    def add_pdf(self, path):
        rel = os.path.relpath(path, self.root) if self.root else os.path.basename(path)
        key = slugify(os.path.splitext(rel)[0])
        while key in self.pdfs and self.pdfs[key] != path:
            key += '-2'
        self.pdfs[key] = path
        return '/__pdf/%s/' % key

    def url_of(self, path):
        """The URL a file is served at, percent-encoded the way a browser reports location.pathname."""
        rel = os.path.relpath(path, self.root).replace('\\', '/')
        if rel == 'index.html':
            return '/'
        if rel.endswith('/index.html'):
            rel = rel[:-len('index.html')]
        return '/' + urllib.parse.quote(rel)

    def scan_folder(self, recursive, view, keep=None):
        """Pages under root. Generated review copies and .pre-* backups are skipped, except `keep`
        (the file named on the command line is always reviewable)."""
        pages, limit = [], 600
        keep = os.path.normcase(keep) if keep else None
        for dp, dns, fns in os.walk(self.root):
            dns[:] = sorted(d for d in dns if not d.startswith(('_', '.')) and d != 'node_modules')
            for fn in sorted(fns):
                low = fn.lower()
                full = os.path.join(dp, fn)
                skipped = low.endswith(('.review.html', '.pages.tmp.html')) or '.pre-' in low
                if skipped and os.path.normcase(full) != keep:
                    continue
                if low.endswith(('.html', '.htm')):
                    url = self.url_of(full)
                    pages.append({'url': url, 'name': html_title(full) or url, 'kind': 'html',
                                  'view': view, 'file': full})
                elif low.endswith('.pdf'):
                    pages.append({'url': self.add_pdf(full), 'name': fn, 'kind': 'pdf',
                                  'view': 'fit', 'file': full})
            if not recursive or len(pages) >= limit:
                break
        pages.sort(key=lambda p: (p['url'] != '/', p['url'].count('/'), p['url']))
        return pages[:limit]

    # ---- URLs
    def resolve_upstream(self):
        req = urllib.request.Request(self.raw, method='GET', headers={'User-Agent': UA})
        try:
            with urllib.request.urlopen(req, timeout=15, context=ssl.create_default_context()) as r:
                final = r.geturl()
        except Exception as e:
            sys.exit('review-page: cannot reach %s (%s)' % (self.raw, e))
        u = urllib.parse.urlsplit(final)
        self.upstream = '%s://%s' % (u.scheme, u.netloc)
        self.start = path_and_query(u)
        for h in (urllib.parse.urlsplit(self.raw).hostname, u.hostname):
            if h:
                self.hosts.add(h)
                self.hosts.add(h[4:] if h.startswith('www.') else 'www.' + h)

    def sitemap_pages(self):
        urls, seen = [], set()

        def fetch(path, depth=0):
            if depth > 2 or path in seen or len(urls) > 600:
                return
            seen.add(path)
            try:
                req = urllib.request.Request(self.upstream + path, headers={'User-Agent': UA})
                with urllib.request.urlopen(req, timeout=8, context=ssl.create_default_context()) as r:
                    xml = r.read(4_000_000).decode('utf-8', 'ignore')
            except Exception:
                return
            for loc in re.findall(r'<loc>\s*([^<\s]+)\s*</loc>', xml):
                u = urllib.parse.urlsplit(H.unescape(loc))
                if u.hostname and u.hostname not in self.hosts:
                    continue
                p = u.path or '/'
                if p.endswith('.xml'):
                    fetch(p, depth + 1)
                elif p not in urls:
                    urls.append(p)

        for p in ('/sitemap-index.xml', '/sitemap.xml', '/sitemap_index.xml'):
            fetch(p)
            if urls:
                break
        if self.start not in urls:
            urls.insert(0, self.start)
        return [{'url': u, 'name': u, 'kind': 'html', 'view': 'both'} for u in urls]

    def build(self):
        if self.kind == 'url':
            self.resolve_upstream()
            self.pages = self.sitemap_pages()
            return
        p = os.path.abspath(self.raw)
        if self.kind == 'site':
            self.root = p
            has_index = os.path.exists(os.path.join(p, 'index.html'))
            # a built site is reviewed like a site; a folder of deliverables like documents
            self.pages = self.scan_folder(recursive=True, view='both' if has_index else 'fit')
            if not self.pages:
                sys.exit('review-page: no .html or .pdf files in %s' % p)
            if not has_index:      # a folder of deliverables: the PDFs are what the reader gets
                self.kind = 'docs'
                self.pages.sort(key=lambda x: (x['kind'] != 'pdf', x['name'].lower()))
            self.start = '/' if has_index else self.pages[0]['url']
            return
        self.root = os.path.dirname(p)
        nc = os.path.normcase
        stem = nc(os.path.splitext(p)[0])
        self.pages = self.scan_folder(recursive=False, view='fit', keep=p)
        twin_pdf = next((x for x in self.pages if x['kind'] == 'pdf'
                         and nc(os.path.splitext(x['file'])[0]) == stem), None)
        mine = next((x for x in self.pages if nc(x['file']) == nc(p)), None)
        # a document reviews as its PDF pages first when it has one (Dave, 2026-09-06)
        first = twin_pdf or mine
        self.start = first['url'] if first else self.pages[0]['url']
        self.pages.sort(key=lambda x: (x is not first, x is not mine and x is not twin_pdf, x['url']))

    def page_file(self, url):
        """The file a page URL serves (for rebuild detection)."""
        path = urllib.parse.unquote(urllib.parse.urlsplit(url).path)
        m = re.match(r'^/__pdf/([^/]+)/', path)
        if m:
            return self.pdfs.get(m.group(1))
        if self.root:
            f = static_file(self.root, path)
            return f[0] if f else None
        return None

    def info(self):
        return {'kind': self.kind, 'target': self.raw, 'start': self.start,
                'upstream': self.upstream,
                'pages': [{k: v for k, v in p.items() if k != 'file'} for p in self.pages]}


def inside(root, rel):
    """root/rel normalised, or None when rel climbs out of root (a sibling like dist-old/ included)."""
    root = os.path.normpath(root)
    full = os.path.normpath(os.path.join(root, rel))
    return full if full == root or full.startswith(root.rstrip(os.sep) + os.sep) else None


def static_file(root, path):
    """Map a URL path to (file, needs_redirect) like Cloudflare Pages: dir/index.html, name.html."""
    full = inside(root, path.lstrip('/'))
    if not full:
        return None
    if os.path.isdir(full):
        idx = os.path.join(full, 'index.html')
        if os.path.exists(idx):
            return idx, not path.endswith('/')
        return None
    if os.path.isfile(full):
        return full, False
    if os.path.isfile(full + '.html'):
        return full + '.html', False
    return None


# ======================================================================= PDF pages

PDF_PAGE_CSS = '''
html{background:#525659}body{margin:0;padding:22px 0 40px;font-family:system-ui,sans-serif}
main{display:flex;flex-direction:column;align-items:center;gap:22px}
.pg{position:relative;width:min(1000px,calc(100vw - 28px));container-type:inline-size;background:#fff;
box-shadow:0 2px 14px rgba(0,0,0,.45)}
.pg img{display:block;width:100%;height:auto;user-select:none;-webkit-user-drag:none}
.tl{position:absolute;inset:0;line-height:1}
.tl span{position:absolute;white-space:pre;color:transparent;transform-origin:0 0;cursor:text}
.tl span::selection{background:rgba(37,99,235,.32);color:transparent}
.pn{position:absolute;left:0;right:0;bottom:-19px;text-align:center;color:#d6d6d6;font-size:11px;
font-weight:600;letter-spacing:.04em}
'''

PDF_PAGE_JS = '''
(function(){function fit(){document.querySelectorAll('.tl span').forEach(function(s){
s.style.transform='none';var w=s.getBoundingClientRect().width,t=s.parentNode.getBoundingClientRect().width*
parseFloat(s.dataset.w)/100;if(w>0&&t>0)s.style.transform='scaleX('+(t/w).toFixed(4)+')';});}
addEventListener('load',fit);addEventListener('resize',function(){clearTimeout(fit.t);fit.t=setTimeout(fit,120);});
})();
'''

_pdf_locks = {}
_pdf_locks_guard = threading.Lock()


def render_pdf(pdf, out_dir, title):
    """PDF -> page JPEGs + an HTML page with a transparent, selectable text layer.
    Cached: re-rendered only when the PDF's size or mtime changes."""
    with _pdf_locks_guard:
        lock = _pdf_locks.setdefault(out_dir, threading.Lock())
    with lock:
        st = os.stat(pdf)
        stamp = '%d:%d' % (st.st_size, int(st.st_mtime))
        meta_path = os.path.join(out_dir, 'meta.json')
        if S.read_json(meta_path, {}).get('stamp') == stamp and os.path.exists(os.path.join(out_dir, 'index.html')):
            return
        import fitz  # PyMuPDF, only needed for PDFs
        os.makedirs(out_dir, exist_ok=True)
        for f in os.listdir(out_dir):
            if f.startswith('p-') and f.endswith('.jpg'):
                os.remove(os.path.join(out_dir, f))
        doc = fitz.open(pdf)
        total = len(doc)
        sections = []
        for i, page in enumerate(doc):
            pw, ph = page.rect.width, page.rect.height
            zoom = 1600.0 / pw                     # ~1600 px wide: crisp at 1000 css px on hi-dpi
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
            name = 'p-%03d.jpg' % (i + 1)
            with open(os.path.join(out_dir, name), 'wb') as f:
                f.write(pix.tobytes('jpeg', jpg_quality=84))
            spans = []
            for b in page.get_text('dict').get('blocks', []):
                for line in b.get('lines', []):
                    parts = [sp for sp in line.get('spans', []) if sp.get('text', '').strip()]
                    if not parts:
                        continue
                    text = ''.join(sp['text'] for sp in line['spans']).strip()
                    x0 = min(sp['bbox'][0] for sp in parts)
                    y0 = min(sp['bbox'][1] for sp in parts)
                    x1 = max(sp['bbox'][2] for sp in parts)
                    size = max(sp.get('size', 10) for sp in parts)
                    spans.append(
                        '<span data-w="%.3f" style="left:%.3f%%;top:%.3f%%;font-size:%.3fcqw">%s</span>'
                        % ((x1 - x0) / pw * 100, x0 / pw * 100, y0 / ph * 100, size / pw * 100, H.escape(text)))
            sections.append(
                '<section class="pg" id="page-%d" data-review-label="Page %d / %d" style="aspect-ratio:%.2f/%.2f">'
                '<img src="%s" alt="Page %d"><div class="tl">%s</div><div class="pn">%d / %d</div></section>'
                % (i + 1, i + 1, total, pw, ph, name, i + 1, ''.join(spans), i + 1, total))
        page_html = ('<!doctype html><html lang="hu"><head><meta charset="utf-8">'
                     '<meta name="viewport" content="width=device-width,initial-scale=1">'
                     '<title>%s</title><style>%s</style></head><body><main>%s</main>'
                     '<script>%s</script></body></html>'
                     % (H.escape(title), PDF_PAGE_CSS, ''.join(sections), PDF_PAGE_JS))
        with io.open(os.path.join(out_dir, 'index.html'), 'w', encoding='utf-8') as f:
            f.write(page_html)
        S.write_json(meta_path, {'stamp': stamp, 'pdf': pdf, 'pages': total})


# ======================================================================= proxy helpers

HOP = {'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization', 'te', 'trailers',
       'transfer-encoding', 'upgrade', 'content-length', 'host', 'accept-encoding'}
DROP_CSP = ('frame-ancestors', 'upgrade-insecure-requests', 'block-all-mixed-content', 'report-uri', 'report-to')


def patch_csp(value):
    keep = [d.strip() for d in value.split(';')
            if d.strip() and d.strip().split()[0].lower() not in DROP_CSP]
    return '; '.join(keep)


def rewrite_origins(text, hosts):
    """Absolute links to the reviewed site become root-relative, so clicks stay on the review origin.
    Only URLs that open an attribute value, a CSS url() or a srcset entry are touched; the same
    address written in body copy stays as the visitor reads it."""
    if not hosts:
        return text
    alt = '|'.join(re.escape(h) for h in sorted(hosts, key=len, reverse=True))
    lead = r'(?:(?<==")|(?<==\')|(?<==)|(?<=url\()|(?<=url\(")|(?<=url\(\')|(?<=, ))'
    pat = re.compile(lead + r'(?:https?:)?//(?:%s)(?::\d+)?(?=([/"\'\s?#<)]|$))' % alt, re.I)
    return pat.sub(lambda m: '' if m.group(1) == '/' else '/', text)


def decompress(raw, enc):
    """Undo a Content-Encoding (gzip, deflate, br). An encoding it cannot undo (zstd, or br without
    the optional brotli module) raises, so the caller passes the body through untouched."""
    if enc in ('', 'identity'):
        return raw
    if enc == 'gzip':
        return gzip.decompress(raw)
    if enc == 'deflate':
        return zlib.decompress(raw)
    if enc == 'br':
        import brotli  # optional
        return brotli.decompress(raw)
    raise ValueError('cannot decode Content-Encoding %s' % enc)


def charset_of(ctype, raw):
    """The page's charset: the Content-Type header, then a <meta charset>, then UTF-8."""
    m = re.search(r'charset=["\']?([\w.:-]+)', ctype or '', re.I)
    if not m:
        m = re.search(rb'<meta[^>]+charset=["\']?([\w.:-]+)', raw[:4096], re.I)
    name = m.group(1) if m else 'utf-8'
    name = name.decode('ascii', 'ignore') if isinstance(name, bytes) else name
    try:
        return codecs.lookup(name).name
    except LookupError:
        return 'utf-8'


def rewrite_html(raw, hosts, ctype=''):
    """A proxied page: absolute links to the site become root-relative, and a CSP meta tag is patched.
    Decoded and re-encoded in the page's own charset, so a windows-1250 site stays readable."""
    cs = charset_of(ctype, raw)
    text = rewrite_origins(raw.decode(cs, 'replace'), hosts)
    text = re.sub(r'(<meta[^>]+content-security-policy[^>]+content=")([^"]*)',
                  lambda m: m.group(1) + patch_csp(m.group(2)), text, flags=re.I)
    out = text.encode(cs, 'xmlcharrefreplace')
    # FRAME_CSS is ASCII bytes: in a UTF-16/32 page it would be garbage, and shift every character
    return out if cs.startswith(('utf_16', 'utf_32', 'utf-16', 'utf-32')) else add_frame_css(out)


# A phone has overlay scrollbars that take no width. The Mobile frame is an iframe in desktop Chrome,
# whose classic scrollbar took 15px, so the page laid out at 375px instead of 390 (2026-10-16: the RR
# hero headline wrapped from 58 to 294px tall, and Dave marked it as a regression it was not). The
# stylesheet is linked, not inlined, so a CSP that allows 'self' styles keeps it, and it is scoped to
# narrow frames by its media query, so it is in force from the first layout and the desktop frame
# keeps its real scrollbar.
FRAME_CSS = b'<link rel="stylesheet" media="(max-width: 600px)" href="/__review/frame.css">'


def add_frame_css(raw):
    """Link frame.css as early as possible: after <head>, else after <html>, else after the doctype
    (never before it, which would put the page in quirks mode). A response with none of the three is
    an HTML fragment that a page fetches and inserts (htmx, Turbo, fetch + innerHTML): it is left
    exactly as it is, since its page already has the link."""
    head = raw[:65536]
    for pat in (rb'<head(?:\s[^>]*)?>', rb'<html(?:\s[^>]*)?>', rb'<!doctype[^>]*>'):
        m = re.search(pat, head, re.I)
        if m:
            return raw[:m.end()] + FRAME_CSS + raw[m.end():]
    return raw


# ======================================================================= HTTP handler

class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'review-page'
    T = None          # Target
    SDIR = None       # store dir
    CONF = {}         # info extras

    def log_message(self, fmt, *args):
        if os.environ.get('REVIEW_PAGE_LOG'):
            sys.stderr.write('  %s\n' % (fmt % args))

    # ---- plumbing
    def send_bytes(self, code, body, ctype, extra=None):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def send_json(self, obj, code=200):
        self.send_bytes(code, json.dumps(obj, ensure_ascii=False).encode('utf-8'),
                        'application/json; charset=utf-8')

    def send_text(self, code, msg):
        self.send_bytes(code, msg.encode('utf-8'), 'text/plain; charset=utf-8')

    def redirect(self, loc):
        self.send_response(302)
        self.send_header('Location', loc)
        self.send_header('Content-Length', '0')
        self.end_headers()

    def body_json(self):
        n = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(n).decode('utf-8') if n else '{}'
        return json.loads(raw or '{}')

    def do_GET(self):
        self.route()

    def do_HEAD(self):
        self.route()

    def do_POST(self):
        self.route()

    do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_POST

    def route(self):
        try:
            path = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
            if path == '/__review':
                return self.redirect('/__review/')
            if path.startswith('/__review/api/'):
                return self.api(path[len('/__review/api/'):])
            if path.startswith('/__review/'):
                return self.serve_file(UI_DIR, path[len('/__review/'):] or 'review.html')
            if path.startswith('/__pdf/'):
                return self.serve_pdf(path)
            if self.T.kind == 'url':
                return self.proxy()
            return self.serve_static(path)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass

    # ---- API
    def api(self, name):
        sdir = self.SDIR
        if name == 'info' and self.command == 'GET':
            return self.send_json(dict(self.T.info(), **self.CONF))
        if name == 'comments' and self.command == 'GET':
            with S.locked(sdir):
                return self.send_json(S.load(sdir))
        if name == 'poll' and self.command == 'GET':
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            page = (q.get('page') or ['/'])[0]
            f = self.T.page_file(page)
            page_rev = int(os.path.getmtime(f)) if f and os.path.exists(f) else 0
            # the same rev /comments reports, so a fresh review does not refresh every poll
            return self.send_json({'rev': S.load(sdir)['rev'], 'pageRev': page_rev})
        if self.command != 'POST':
            return self.send_text(405, 'method not allowed')
        try:
            body = self.body_json()
        except ValueError as e:
            return self.send_text(400, 'bad json: %s' % e)
        if name == 'upsert':
            data, rec = S.upsert(sdir, body.get('item') or {})
            return self.send_json({'item': rec, 'rev': data['rev']})
        if name == 'delete':
            data, n = S.remove(sdir, body.get('ids') or [])
            return self.send_json({'removed': n, 'rev': data['rev']})
        if name == 'status':
            data, hit = S.set_status(sdir, body.get('ids') or [], body.get('status'))
            return self.send_json({'changed': hit, 'rev': data['rev']})
        if name == 'clear-done':
            data, n = S.clear_done(sdir)
            return self.send_json({'removed': n, 'rev': data['rev']})
        return self.send_text(404, 'unknown api')

    # ---- files
    def serve_file(self, root, rel):
        full = inside(root, rel.replace('/', os.sep))
        if not full or not os.path.isfile(full):
            return self.send_text(404, 'not found: %s' % rel)
        return self.send_path(full)

    def send_path(self, full, code=200):
        size = os.path.getsize(full)
        ctype = mime_of(full)
        rng = self.headers.get('Range')
        start, end = 0, size - 1
        if rng and code == 200:
            m = re.match(r'bytes=(\d*)-(\d*)', rng)
            if m and (m.group(1) or m.group(2)):
                if m.group(1):
                    start = int(m.group(1))
                    end = int(m.group(2)) if m.group(2) else size - 1
                else:
                    start = max(0, size - int(m.group(2)))
                end = min(end, size - 1)
                if start > end or start >= size:
                    self.send_response(416)
                    self.send_header('Content-Range', 'bytes */%d' % size)
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                    return
                code = 206
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(end - start + 1))
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Cache-Control', 'no-store')
        if code == 206:
            self.send_header('Content-Range', 'bytes %d-%d/%d' % (start, end, size))
        self.end_headers()
        if self.command == 'HEAD':
            return
        with open(full, 'rb') as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = f.read(min(262144, left))
                if not chunk:
                    break
                self.wfile.write(chunk)
                left -= len(chunk)

    def serve_static(self, path):
        if self.command not in ('GET', 'HEAD'):
            return self.send_text(405, 'static review server: %s not supported' % self.command)
        hit = static_file(self.T.root, path)
        if not hit:
            nf = os.path.join(self.T.root, '404.html')
            if os.path.exists(nf):
                return self.send_page(nf, 404)
            return self.send_text(404, 'not found: %s' % path)
        full, add_slash = hit
        if add_slash:
            q = urllib.parse.urlsplit(self.path).query
            return self.redirect(urllib.parse.quote(path) + '/' + ('?' + q if q else ''))
        return self.send_page(full)

    def send_page(self, full, code=200):
        """A reviewed file: HTML gets frame.css linked in (see FRAME_CSS); anything else goes as is."""
        ctype = mime_of(full)
        if not ctype.startswith('text/html'):
            return self.send_path(full, code)
        with open(full, 'rb') as f:
            return self.send_bytes(code, add_frame_css(f.read()), ctype)

    def serve_pdf(self, path):
        m = re.match(r'^/__pdf/([^/]+)(/.*)?$', path)
        key = m.group(1) if m else None
        pdf = self.T.pdfs.get(key)
        if not pdf:
            return self.send_text(404, 'unknown pdf: %s' % key)
        if not m.group(2):
            return self.redirect('/__pdf/%s/' % key)
        out_dir = os.path.join(self.SDIR, '_pdf', key)
        try:
            render_pdf(pdf, out_dir, os.path.basename(pdf))
        except Exception as e:
            return self.send_text(500, 'could not render %s: %s' % (pdf, e))
        full = inside(out_dir, (m.group(2).lstrip('/') or 'index.html').replace('/', os.sep))
        if not full or not os.path.isfile(full):
            return self.send_text(404, 'not found: %s' % m.group(2))
        return self.send_page(full)

    # ---- proxy (URL targets)
    def proxy(self):
        T = self.T
        if self.command not in ('GET', 'HEAD', 'OPTIONS') and not self.CONF.get('allowPost'):
            return self.send_text(403, 'review-page blocks %s to %s so reviewing can never submit a '
                                       'form on the real site. Relaunch with --allow-post to allow it.'
                                  % (self.command, T.upstream))
        up = urllib.parse.urlsplit(T.upstream)
        port = up.port or (443 if up.scheme == 'https' else 80)
        if up.scheme == 'https':
            conn = http.client.HTTPSConnection(up.hostname, port, timeout=30,
                                               context=ssl.create_default_context())
        else:
            conn = http.client.HTTPConnection(up.hostname, port, timeout=30)
        here = 'http://%s' % self.headers.get('Host', '')
        headers = {}
        for k, v in self.headers.items():
            lk = k.lower()
            if lk in HOP:
                continue
            if lk in ('origin', 'referer'):
                v = v.replace(here, T.upstream)
            headers[k] = v
        headers['Host'] = up.netloc
        headers['Accept-Encoding'] = 'identity'
        n = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(n) if n else None
        try:
            conn.request(self.command, self.path, body=body, headers=headers)
            resp = conn.getresponse()
        except Exception as e:
            return self.send_text(502, 'upstream %s failed: %s' % (T.upstream, e))
        ctype = resp.getheader('Content-Type', '')
        is_html = 'text/html' in ctype.lower()
        out_headers = []
        for k, v in resp.getheaders():
            lk = k.lower()
            if lk in HOP or lk in ('x-frame-options', 'strict-transport-security', 'alt-svc'):
                continue
            if lk in ('content-security-policy', 'content-security-policy-report-only'):
                v = patch_csp(v)
            elif lk == 'location':
                lu = urllib.parse.urlsplit(v)
                if lu.hostname in T.hosts:
                    v = path_and_query(lu)
            elif lk == 'set-cookie':
                v = re.sub(r';\s*domain=[^;]*', '', v, flags=re.I)
            elif lk == 'content-encoding' and is_html:
                continue
            out_headers.append((k, v))
        length = resp.getheader('Content-Length')
        whole = None      # the body when it is sent in one piece; None streams it through
        if is_html and self.command != 'HEAD':
            whole = resp.read()
            enc = (resp.getheader('Content-Encoding') or '').lower()
            try:
                whole = decompress(whole, enc)
            except Exception:
                out_headers.append(('Content-Encoding', enc))   # leave it as it came
            else:
                whole = rewrite_html(whole, T.hosts, ctype)
        elif length is None:
            whole = resp.read() if self.command != 'HEAD' else b''
        self.send_response(resp.status)
        for k, v in out_headers:
            self.send_header(k, v)
        if whole is None:
            self.send_header('Content-Length', length)
            self.end_headers()
            if self.command != 'HEAD':
                while True:
                    chunk = resp.read(262144)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        else:
            self.send_header('Content-Length', str(len(whole)))
            self.end_headers()
            self.wfile.write(whole)
        conn.close()


class QuietServer(ThreadingHTTPServer):
    """Browsers drop keep-alive sockets all the time; that is not worth a traceback in server.log."""
    def handle_error(self, request, client_address):
        if not isinstance(sys.exc_info()[1], (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            ThreadingHTTPServer.handle_error(self, request, client_address)


# ======================================================================= lifecycle

def health(port, slug, timeout=1.5):
    try:
        with urllib.request.urlopen('http://127.0.0.1:%d/__review/api/info' % port, timeout=timeout) as r:
            return json.loads(r.read().decode('utf-8')).get('slug') == slug
    except Exception:
        return False


def running_port(sdir, slug):
    srv = S.read_json(S.paths(sdir)['server'], {})
    port = srv.get('port')
    return port if port and health(port, slug) else None


def free_port(preferred=None):
    for port in ([preferred] if preferred else []) + list(PORT_RANGE):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(('127.0.0.1', port))
            return port
        except OSError:
            continue
        finally:
            s.close()
    sys.exit('review-page: no free port in %d-%d' % (PORT_RANGE[0], PORT_RANGE[-1]))


def detach(argv, sdir, slug):
    """Start this script again in the background, so the server outlives this console and the
    Claude session. On Windows the process is created through WMI (Win32_Process.Create): its
    parent is the WMI service, so no shell, pipeline or job object of the caller can take it
    down when that caller ends. Popen with DETACHED_PROCESS was not enough: servers started from
    Git Bash died when a later pipeline in the same shell closed (2026-10-15)."""
    log = os.path.join(sdir, 'server.log')
    args = [a for a in argv if a != '--detach'] + ['--no-open', '--log', log]
    script = os.path.abspath(__file__)
    started = False
    if os.name == 'nt':
        exe = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')
        if not os.path.exists(exe):
            exe = sys.executable
        ps = ('$si = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly -Property @{ShowWindow=[uint16]0}; '
              '$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments '
              '@{CommandLine=$env:RP_CMD; CurrentDirectory=$env:RP_DIR; ProcessStartupInformation=$si}; '
              'exit $r.ReturnValue')
        env = dict(os.environ, RP_CMD=subprocess.list2cmdline([exe, script] + args), RP_DIR=TOOL_DIR)
        try:
            r = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', ps], env=env,
                               capture_output=True, text=True, timeout=90)
            started = r.returncode == 0
            if not started:
                print('review-page: WMI start failed (%s), falling back' % (r.stderr.strip() or r.returncode))
        except (OSError, subprocess.TimeoutExpired) as e:
            print('review-page: WMI start failed (%s), falling back' % e)
    if not started:
        flags = 0x00000008 | 0x00000200 | 0x08000000 if os.name == 'nt' else 0   # DETACHED | NEW_GROUP | NO_WINDOW
        subprocess.Popen([sys.executable, script] + args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True, creationflags=flags,
                         start_new_session=os.name != 'nt')
    for _ in range(160):
        time.sleep(0.25)
        port = running_port(sdir, slug)
        if port:
            return port
    sys.exit('review-page: the background server did not come up; see %s' % log)


def job_note():
    """Windows: a process inside the starter's job object dies when that job closes."""
    if os.name != 'nt':
        return ''
    try:
        import ctypes
        res = ctypes.c_int(0)
        ctypes.windll.kernel32.IsProcessInJob(ctypes.windll.kernel32.GetCurrentProcess(), None, ctypes.byref(res))
        return ', inside a job object' if res.value else ', not in a job'
    except Exception:
        return ''


def relaunch_line(sdir):
    py = 'python' if os.name == 'nt' else 'python3'
    return '%s "%s" --resume %s --home "%s" --detach' % (py, os.path.abspath(__file__), os.path.basename(sdir),
                                                       os.path.dirname(os.path.abspath(sdir)))


def main():
    ap = argparse.ArgumentParser(description='click-to-comment review of a site, HTML file, PDF or URL')
    ap.add_argument('target', nargs='?')
    ap.add_argument('--name', help='review slug (store folder name); default from the target')
    ap.add_argument('--port', type=int)
    ap.add_argument('--no-open', action='store_true')
    ap.add_argument('--detach', action='store_true', help='run in the background, outliving this console')
    ap.add_argument('--session', action='append', default=[], metavar='KEY=VALUE')
    ap.add_argument('--local', action='append', default=[], metavar='KEY=VALUE')
    ap.add_argument('--allow-post', action='store_true')
    ap.add_argument('--resume', metavar='SLUG', help='relaunch a saved review')
    ap.add_argument('--stop', metavar='SLUG', help='stop the server of a review')
    ap.add_argument('--home', metavar='DIR', help='reviews home for this run (default: $REVIEW_PAGE_HOME, '
                    'else "home" in config.local.json, else ~/.review-page/reviews)')
    ap.add_argument('--log', help=argparse.SUPPRESS)      # set by --detach: write output here
    a = ap.parse_args()
    if a.log:
        sys.stdout = sys.stderr = io.open(a.log, 'a', encoding='utf-8', buffering=1)
    if a.home:
        S.REVIEWS_ROOT = os.path.abspath(a.home)

    if a.stop:
        sdir = S.store_dir(a.stop)
        srv = S.read_json(S.paths(sdir)['server'], {})
        if not srv.get('pid'):
            sys.exit('review-page: no server recorded for %s' % a.stop)
        # only kill a pid that still answers as this review: after a crash or reboot Windows
        # may have handed the recorded pid to an unrelated process
        if running_port(sdir, a.stop):
            try:
                os.kill(srv['pid'], 15)
                print('stopped %s' % a.stop)
            except OSError as e:
                print('could not stop pid %s: %s' % (srv['pid'], e))
        else:
            print('%s was not running (stale server.json removed)' % a.stop)
        try:
            os.remove(S.paths(sdir)['server'])
        except OSError:
            pass
        return

    if a.resume:
        saved = S.read_json(S.paths(S.store_dir(a.resume))['target'], None)
        if not saved:
            sys.exit('review-page: no saved review called %s under %s' % (a.resume, S.REVIEWS_ROOT))
        a.target = saved['target']
        a.name = saved['slug']
        a.session = a.session or ['%s=%s' % kv for kv in saved.get('session', {}).items()]
        a.local = a.local or ['%s=%s' % kv for kv in saved.get('local', {}).items()]
        a.allow_post = a.allow_post or saved.get('allowPost', False)

    if not a.target:
        ap.error('a target is required (folder, .html, .pdf or URL), or --resume SLUG')

    raw = a.target
    if re.match(r'^https?://', raw, re.I):
        kind = 'url'
    else:
        raw = os.path.abspath(raw)
        if os.path.isdir(raw):
            kind = 'site'
        elif raw.lower().endswith(('.html', '.htm')) and os.path.isfile(raw):
            kind = 'html'
        elif raw.lower().endswith('.pdf') and os.path.isfile(raw):
            kind = 'pdf'
        else:
            sys.exit('review-page: %s is not a folder, .html, .pdf or http(s) URL' % a.target)

    if a.name:
        slug = slugify(a.name)
    elif kind == 'url':
        u = urllib.parse.urlsplit(raw)
        slug = slugify('%s%s%s' % (u.hostname, '-%d' % u.port if u.port else '', u.path.rstrip('/')))
    else:
        base = os.path.basename(raw.rstrip('\\/'))
        base = os.path.splitext(base)[0] if kind != 'site' else base
        if kind == 'site' and base.lower() in ('dist', 'build', 'out', 'public', '_site', 'site', 'output'):
            base = os.path.basename(os.path.dirname(raw.rstrip('\\/'))) + '-' + base
        slug = slugify(base)
    sdir = S.store_dir(slug)
    files = S.paths(sdir)
    os.makedirs(sdir, exist_ok=True)

    session, local = kv_list(a.session), kv_list(a.local)
    relaunch = relaunch_line(sdir)
    target_rec = {'slug': slug, 'name': slug, 'target': raw, 'kind': kind, 'session': session,
                  'local': local, 'allowPost': a.allow_post, 'relaunch': relaunch,
                  'updated': S.now()}
    S.write_json(files['target'], target_rec)
    if os.name == 'nt':
        with io.open(os.path.join(sdir, 'open-review.cmd'), 'w', encoding='utf-8') as f:
            f.write('@echo off\r\nrem Relaunch the review "%s" and open it in the browser.\r\n%s\r\n'
                    % (slug, relaunch))
    else:
        sh = os.path.join(sdir, 'open-review.sh')
        with io.open(sh, 'w', encoding='utf-8', newline='\n') as f:
            f.write('#!/bin/sh\n# Relaunch the review "%s" and open it in the browser.\n%s\n' % (slug, relaunch))
        os.chmod(sh, 0o755)
    if not os.path.exists(files['notes']):
        S.write_notes(sdir)

    port = running_port(sdir, slug)
    if port:
        url = review_url(port)
        print('review-page: already running at %s' % url)
        print('  notes: %s' % files['notes'])
        if not a.no_open:
            webbrowser.open(url)
        return

    if a.detach:
        # the child resumes from target.json (written above, absolute target path), because the
        # WMI-started child runs in the tool folder where a relative target would not resolve.
        # It gets the reviews home explicitly: a WMI-started process does not inherit our environment.
        port = detach(['--resume', slug, '--home', S.REVIEWS_ROOT] + (['--port', str(a.port)] if a.port else []),
                      sdir, slug)
        url = review_url(port)
        print('review-page: %s' % url)
        print('  target: %s (%s)' % (raw, kind))
        print('  notes : %s' % files['notes'])
        print('  stop  : python "%s" --stop %s' % (os.path.abspath(__file__), slug))
        if not a.no_open:
            webbrowser.open(url)
        return

    T = Target(raw, kind)
    T.build()
    port = free_port(a.port)
    url = review_url(port)
    Handler.T = T
    Handler.SDIR = sdir
    Handler.CONF = {'slug': slug, 'name': slug, 'store': sdir, 'notes': files['notes'],
                    'session': session, 'local': local, 'allowPost': a.allow_post}
    srv = QuietServer(('127.0.0.1', port), Handler)
    srv.daemon_threads = True
    S.write_json(files['server'], {'port': port, 'pid': os.getpid(), 'started': S.now(), 'url': url})
    print('review-page: %s' % url)
    print('  started %s, pid %d%s' % (S.now(), os.getpid(), job_note()))
    print('  target: %s (%s, %d pages)' % (raw, kind, len(T.pages)))
    print('  notes : %s' % files['notes'])
    sys.stdout.flush()
    if not a.no_open:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
        if S.read_json(files['server'], {}).get('pid') == os.getpid():
            try:
                os.remove(files['server'])
            except OSError:
                pass


if __name__ == '__main__':
    main()
