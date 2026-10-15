/* ============================================================================
   review-page annotator: injected by the review tool INTO each preview frame.

   The review server serves the reviewed pages and the tool from one origin, so this runs inside
   the page's own document: it outlines real elements, reads their text, and anchors notes to
   them. It talks to the tool through window.parent.RVHost (direct calls, same origin).

   Tools (set by the tool bar, or keys C / V / T / B inside the frame):
     click  hover names an element, click it to write a note (Alt = the parent block)
     box    drag a rectangle over any area: a canvas moment, part of an image, a PDF region, a gap
     text   select text, then note it (the exact words are quoted back to Claude)
     browse the page behaves normally; links and forms work
   Every note also records where the page was scrolled, and for a pinned (sticky) scene how far
   through it, so "the mirror at 47 %" comes back as exactly that moment.

   Loaded with window.__REVIEW_SHOT__ set (by shots.mjs) it builds no UI and only exposes
   window.__review = { restore, rects } for screenshots.
   ========================================================================== */
(function () {
  'use strict';
  if (window.__rvAnnotator) return;
  window.__rvAnnotator = true;

  var doc = document;
  var HOST = null;
  try { HOST = window.parent !== window ? window.parent.RVHost : null; } catch (e) { HOST = null; }
  var SHOT = !!window.__REVIEW_SHOT__;
  if (!HOST && !SHOT) return;

  var ACTIONS = [
    { id: 'remove', label: 'Remove', color: '#e5484d', key: '1' },
    { id: 'rework', label: 'Rework', color: '#f5a524', key: '2' },
    { id: 'comment', label: 'Comment', color: '#4c8dff', key: '3' },
    { id: 'discuss', label: 'Discuss', color: '#a06bff', key: '4' },
    { id: 'add', label: 'Add', color: '#27a644', key: '5' }
  ];
  function actionOf(id) {
    for (var i = 0; i < ACTIONS.length; i++) if (ACTIONS[i].id === id) return ACTIONS[i];
    return ACTIONS[1];
  }
  var NEEDS_TEXT = { comment: 1, discuss: 1, add: 1 };

  var SEL = [
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'li', 'dt', 'dd', 'a', 'button', 'img', 'picture', 'figure',
    'figcaption', 'label', 'input', 'textarea', 'select', 'blockquote', 'table', 'th', 'td', 'video',
    'canvas', 'svg', 'form', 'section', 'header', 'footer', 'nav', 'aside', 'article', 'summary',
    'details', '[role="button"]', '[data-review-label]', '.tl span',
    '[class*="card"]', '[class*="btn"]', '[class*="badge"]', '[class*="hero"]', '[class*="stat"]',
    '[class*="price"]', '[class*="step"]', '[class*="cta"]'
  ].join(',');

  /* ---------- element identification ------------------------------------ */
  var OVID = '__rv';
  function inOverlay(el) { return !!(el && el.closest && el.closest('#' + OVID)); }

  function pick(node, widen) {
    var el = node;
    while (el && el.nodeType !== 1) el = el.parentNode;
    if (!el || inOverlay(el) || el === doc.body || el === doc.documentElement) return null;
    var hit = el.matches(SEL) ? el : (el.closest(SEL) || el);
    if (widen && hit.parentElement && hit.parentElement !== doc.body) {
      hit = hit.parentElement.closest(SEL) || hit.parentElement;
    }
    return hit;
  }

  function short(s, n) {
    s = (s || '').replace(/\s+/g, ' ').trim();
    return s.length > n ? s.slice(0, n - 1) + '…' : s;
  }
  function cls(el) {
    var c = el.getAttribute && el.getAttribute('class');
    return (typeof c === 'string' ? c : '').trim().split(/\s+/).filter(Boolean);
  }

  /* the most telling class: a BEM modifier ("act--mirror") beats the block ("act") */
  function bestClass(el) {
    var c = cls(el).filter(function (x) { return !/^(astro-|svelte-|is-|js-|has-)/.test(x); });
    var mod = c.filter(function (x) { return x.indexOf('--') > 0; });
    return mod[0] || c[0] || '';
  }

  function blockName(s) {
    var lab = s.getAttribute('data-review-label') || s.getAttribute('aria-label');
    if (lab) return short(lab, 48);
    var h = s.querySelector('h1,h2,h3');
    var heading = h ? short(h.textContent, 48) : '';
    if (heading) return heading;
    if (s.id) return '#' + s.id;
    var c = bestClass(s);
    return c ? '.' + c : s.tagName.toLowerCase();
  }

  function sectionOf(el) {
    var lab = el.closest('[data-review-label]');
    if (lab) return lab.getAttribute('data-review-label');
    var s = el.closest('section,header,footer,nav,main > *,article');
    if (!s) return '';
    var all = [].slice.call(doc.querySelectorAll('body section, body > header, body > footer, main > header, main > footer'));
    var idx = all.indexOf(s);
    return (idx >= 0 ? 'Section ' + (idx + 1) + ': ' : '') + blockName(s);
  }

  function labelOf(el) {
    if (!el || !el.tagName) return 'the page';
    var tag = el.tagName.toLowerCase();
    var t = short(el.innerText || el.textContent || '', 56);
    if (el.hasAttribute('data-review-label')) return el.getAttribute('data-review-label');
    if (tag === 'img') return 'Image: ' + (el.getAttribute('alt') || (el.currentSrc || el.src || '').split('/').pop() || '');
    if (tag === 'video') return 'Video: ' + ((el.currentSrc || el.src || '').split('/').pop() || 'element');
    if (tag === 'canvas') return 'Canvas' + (bestClass(el) ? ' .' + bestClass(el) : '') + (el.getAttribute('aria-label') ? ': ' + el.getAttribute('aria-label') : '');
    if (tag === 'svg') return 'Graphic (svg)' + (el.getAttribute('aria-label') ? ': ' + el.getAttribute('aria-label') : '');
    if (/^h[1-6]$/.test(tag)) return tag.toUpperCase() + ': ' + t;
    if (tag === 'a') return 'Link: ' + (t || el.getAttribute('href') || '');
    if (tag === 'button' || el.getAttribute('role') === 'button') return 'Button: ' + t;
    if (tag === 'input' || tag === 'textarea' || tag === 'select') {
      return 'Field: ' + (el.getAttribute('aria-label') || el.getAttribute('name') || el.getAttribute('placeholder') || tag);
    }
    if (tag === 'form') return 'Form';
    if (tag === 'section' || tag === 'header' || tag === 'footer' || tag === 'nav' || tag === 'article' || tag === 'aside') {
      return 'Block <' + tag + '>: ' + blockName(el);
    }
    if (tag === 'li') return 'List item: ' + t;
    if (tag === 'p' || tag === 'span') return 'Text: ' + t;
    var c = bestClass(el);
    return (c ? '.' + c : '<' + tag + '>') + (t ? ': ' + t : '');
  }

  function cssPath(el) {
    var parts = [];
    var n = el;
    while (n && n.nodeType === 1 && n !== doc.body && n !== doc.documentElement) {
      if (n.id && /^[A-Za-z][\w-]*$/.test(n.id)) { parts.unshift('#' + CSS.escape(n.id)); break; }
      var s = n.tagName.toLowerCase();
      var c = cls(n).filter(function (x) {
        return !/^(on|is-|js-|has-|active|open|show|hidden|visible|in-view|landed|astro-|svelte-|css-|sc-|rvx)/.test(x) && x.length < 40;
      }).slice(0, 2);
      if (c.length) s += '.' + c.map(function (x) { return CSS.escape(x); }).join('.');
      var p = n.parentElement;
      if (p) {
        var same = [].filter.call(p.children, function (k) { return k.tagName === n.tagName; });
        if (same.length > 1) s += ':nth-of-type(' + (same.indexOf(n) + 1) + ')';
      }
      parts.unshift(s);
      n = n.parentElement;
    }
    return parts.join(' > ');
  }

  function idxPath(el) {
    var parts = [];
    var n = el;
    while (n && n.nodeType === 1 && n !== doc.body && n.parentElement) {
      parts.unshift([].indexOf.call(n.parentElement.children, n));
      n = n.parentElement;
    }
    return parts.join('/');
  }

  function resolve(rec) {
    var el = null;
    if (rec.sel) { try { el = doc.querySelector(rec.sel); } catch (e) { el = null; } }
    if (!el && rec.path) {
      el = doc.body;
      var idx = String(rec.path).split('/');
      for (var i = 0; i < idx.length && el; i++) el = el.children[+idx[i]];
      if (el && rec.tagName && el.tagName.toLowerCase() !== rec.tagName) el = null;
    }
    if (!el && rec.tagName && rec.text) {
      var c = doc.getElementsByTagName(rec.tagName);
      for (var j = 0; j < c.length; j++) {
        if (short(c[j].innerText || c[j].textContent || '', 200) === rec.text) { el = c[j]; break; }
      }
    }
    return el || null;
  }

  function describe(el) {
    return {
      sel: cssPath(el), path: idxPath(el), label: labelOf(el), section: sectionOf(el),
      text: short(el.innerText || el.textContent || '', 200), tagName: el.tagName.toLowerCase()
    };
  }

  /* ---------- scrolling --------------------------------------------------- */
  var container = null;
  function scroller() {
    var se = doc.scrollingElement || doc.documentElement;
    if (container && doc.contains(container)) return container;
    if (se.scrollHeight > innerHeight + 4) return se;
    var best = null, bh = 0, all = doc.body ? doc.body.getElementsByTagName('*') : [];
    for (var i = 0; i < all.length && i < 5000; i++) {
      var e = all[i];
      if (e.scrollHeight > e.clientHeight + 40 && e.clientHeight > innerHeight * 0.5 && e.scrollHeight > bh) {
        var oy = getComputedStyle(e).overflowY;
        if (oy === 'auto' || oy === 'scroll') { best = e; bh = e.scrollHeight; }
      }
    }
    if (best) container = best;
    return best || se;
  }
  function isRoot(sc) { return sc === doc.scrollingElement || sc === doc.documentElement || sc === doc.body; }
  function getY() { var sc = scroller(); return isRoot(sc) ? (window.pageYOffset || sc.scrollTop) : sc.scrollTop; }
  function viewH() { var sc = scroller(); return isRoot(sc) ? innerHeight : sc.clientHeight; }
  function docH() { return scroller().scrollHeight; }
  function setY(y, smooth) {
    var sc = scroller();
    var opt = { top: Math.max(0, Math.round(y)), behavior: smooth ? 'smooth' : 'instant' };
    try { (isRoot(sc) ? window : sc).scrollTo(opt); }
    catch (e) { if (isRoot(sc)) window.scrollTo(0, opt.top); else sc.scrollTop = opt.top; }
  }
  function absTop(el) {
    var sc = scroller(), r = el.getBoundingClientRect();
    return isRoot(sc) ? r.top + getY() : r.top - sc.getBoundingClientRect().top + sc.scrollTop;
  }

  /* The nearest sticky ancestor that pins inside a real scroll track (a pinned scene). A sticky
     site header whose track is the whole page is not a scene. */
  function pinOf(el) {
    var n = el;
    while (n && n.nodeType === 1 && n !== doc.documentElement) {
      if (getComputedStyle(n).position === 'sticky') {
        var track = n.parentElement;
        if (!track) return null;
        var travel = track.offsetHeight - n.offsetHeight;
        if (travel > 20 && track.offsetHeight < docH() * 0.8) return { sticky: n, track: track, travel: travel };
        return null;
      }
      n = n.parentElement;
    }
    return null;
  }

  function scrollCtx(el) {
    var y = getY(), dh = docH(), max = Math.max(0, dh - viewH());
    var ctx = { y: Math.round(y), docH: Math.round(dh), progress: max ? +(y / max).toFixed(4) : 0, bound: false };
    var pin = el ? pinOf(el) : null;
    if (pin) {
      var p = (y - absTop(pin.track)) / pin.travel;
      ctx.bound = true;
      ctx.track = {
        label: blockName(pin.track.closest('section,article,[data-review-label]') || pin.track),
        progress: +Math.min(1, Math.max(0, p)).toFixed(4),
        sel: cssPath(pin.track)
      };
    }
    return ctx;
  }

  /* where the page has to be scrolled to show a note as it was written */
  function targetY(rec, el) {
    var sc = rec.scroll || {};
    if (sc.y != null && sc.docH && Math.abs(docH() - sc.docH) / sc.docH < 0.03) return sc.y;
    if (sc.track && sc.track.sel) {
      var tr = null;
      try { tr = doc.querySelector(sc.track.sel); } catch (e) { tr = null; }
      if (tr) {
        var pin = el ? pinOf(el) : null;
        var travel = pin ? pin.travel : tr.offsetHeight - viewH();
        return absTop(tr) + sc.track.progress * travel;
      }
    }
    if (sc.y != null && sc.docH) return sc.progress * Math.max(0, docH() - viewH());
    return null;
  }

  /* ---------- text quotes --------------------------------------------------- */
  function findQuote(root, raw, offset) {
    if (!root || !raw) return null;
    var full = root.textContent || '';
    var start = (offset != null && full.substr(offset, raw.length) === raw) ? offset : full.indexOf(raw);
    if (start < 0) return null;
    var end = start + raw.length, pos = 0, started = false, n;
    var range = doc.createRange();
    var tw = doc.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
    while ((n = tw.nextNode())) {
      var len = n.data.length;
      if (!started && start <= pos + len) { range.setStart(n, start - pos); started = true; }
      if (started && end <= pos + len) { range.setEnd(n, end - pos); return range; }
      pos += len;
    }
    return null;
  }

  /* ---------- the area a note covers, in viewport px --------------------------- */
  function plain(r) { return { left: r.left, top: r.top, width: r.width, height: r.height }; }
  function rectsFor(rec, cache) {
    cache = cache || {};
    var el = cache.el !== undefined ? cache.el : resolve(rec);
    if (rec.kind === 'box') {
      if (el && rec.rel) {
        var r = el.getBoundingClientRect();
        return [{ left: r.left + rec.rel.x * r.width, top: r.top + rec.rel.y * r.height,
          width: rec.rel.w * r.width, height: rec.rel.h * r.height }];
      }
      if (rec.box) return [{ left: rec.box.x - window.pageXOffset, top: rec.box.y - getY(), width: rec.box.w, height: rec.box.h }];
      return [];
    }
    if (!el) return [];
    if (rec.kind === 'text') {
      var range = cache.range !== undefined ? cache.range : findQuote(el, rec.raw || rec.quote, rec.offset);
      if (range) {
        var out = [].slice.call(range.getClientRects()).filter(function (q) { return q.width > 0.5 && q.height > 0.5; }).map(plain);
        if (out.length) return out;
      }
    }
    return [plain(el.getBoundingClientRect())];
  }
  function union(rs) {
    if (!rs || !rs.length) return null;
    var l = Infinity, t = Infinity, r = -Infinity, b = -Infinity;
    rs.forEach(function (q) { l = Math.min(l, q.left); t = Math.min(t, q.top); r = Math.max(r, q.left + q.width); b = Math.max(b, q.top + q.height); });
    return { left: l, top: t, width: r - l, height: b - t, right: r, bottom: b };
  }

  function restore(rec, smooth) {
    var el = resolve(rec);
    var y = targetY(rec, el);
    if (y == null && el) {
      var u = union(rectsFor(rec, { el: el }));
      if (u) y = getY() + u.top - viewH() / 2 + u.height / 2;
    }
    if (y == null) return false;
    setY(y, smooth && !(rec.scroll && rec.scroll.bound));
    return true;
  }

  if (SHOT) {
    window.__review = {
      restore: function (rec) { return restore(rec, false); },
      rects: function (rec) { return rectsFor(rec); }
    };
    return;
  }

  /* ---------- overlay ------------------------------------------------------ */
  var link = doc.createElement('link');
  link.rel = 'stylesheet';
  link.href = '/__review/annotator.css';
  (doc.head || doc.documentElement).appendChild(link);

  var ov = mk('div'); ov.id = OVID;
  doc.documentElement.appendChild(ov);
  var hoverBox = add('rvx-box');
  var chip = add('rvx-chip');
  var selBoxes = [];
  var flashBoxes = [];
  var peekBoxes = [];
  var drawBox = add('rvx-box draw');
  var cover = add('rvx-cover');
  var hint = add('rvx-hint');
  var tip = add('rvx-tip');

  function mk(t, c) { var e = doc.createElement(t); if (c) e.className = c; return e; }
  function add(c) { var e = mk('div', c); ov.appendChild(e); return e; }
  function put(node, r, pad) {
    pad = pad || 0;
    node.style.left = (r.left - pad) + 'px';
    node.style.top = (r.top - pad) + 'px';
    node.style.width = (r.width + pad * 2) + 'px';
    node.style.height = (r.height + pad * 2) + 'px';
    node.style.display = 'block';
  }
  /* draw a set of rects with a pool of boxes; mod is the box's class modifier (sel, peek, flash) */
  function drawRects(pool, rects, mod, pad) {
    rects = rects || [];
    while (pool.length < rects.length) pool.push(add('rvx-box ' + mod));
    for (var i = 0; i < pool.length; i++) {
      if (i < rects.length) put(pool[i], rects[i], pad); else pool[i].style.display = 'none';
    }
  }

  /* ---------- state ------------------------------------------------------ */
  var tool = 'click';
  var Z = 1;                 // the frame is CSS-scaled by the tool; the overlay UI is scaled back by Z
  var hovered = null;
  var pending = null;        // the composer's target {kind, el, rel, box, range, quote...} while it is open
  var comments = [];
  var pins = [];             // {rec, el, range, node, retryAt}
  var pop = null;
  var peek = null;
  var flash = null, flashUntil = 0;
  var drawing = null;

  var ctx = HOST.register(window, {
    setTool: function (t) { setTool(t); },
    setScale: function (s) { setScale(s); },
    setComments: function (list) { comments = list || []; if (!pop) buildPins(); },
    focus: function (rec) { focusRec(rec); },
    edit: function (rec) { var el = resolve(rec); restore(rec, false); setTimeout(function () { openPop(fromRec(rec, el), rec); }, 120); },
    where: function () { return { y: getY(), docH: docH() }; }
  });
  if (!ctx) return;
  comments = ctx.comments || [];

  function setScale(s) {
    Z = Math.min(2.4, 1 / Math.max(0.3, s || 1));
    ov.style.setProperty('--z', String(Z));
  }
  setScale(ctx.scale || 1);

  function setTool(t) {
    tool = t || 'click';
    if (tool !== 'click') clearHover();
    cover.style.display = tool === 'box' ? 'block' : 'none';
    doc.documentElement.classList.toggle('rvx-text-mode', tool === 'text');
    if (tool !== 'text') { try { window.getSelection().removeAllRanges(); } catch (e) {} }
    closePop();
    showHint({
      click: 'Click an element to note it · Alt grabs the parent block',
      box: 'Drag a rectangle over any area · Esc cancels',
      text: 'Select words, the note quotes them exactly',
      browse: 'Browsing: links and forms work, nothing is marked'
    }[tool], 2200);
  }

  var hintT;
  function showHint(s, ms) {
    clearTimeout(hintT);
    if (!s) { hint.style.display = 'none'; return; }
    hint.textContent = s; hint.style.display = 'block';
    if (ms) hintT = setTimeout(function () { hint.style.display = 'none'; }, ms);
  }

  /* ---------- click tool ---------------------------------------------------- */
  function hideHover() { hoverBox.style.display = 'none'; chip.style.display = 'none'; }
  function clearHover() { hovered = null; hideHover(); }

  doc.addEventListener('mousemove', function (e) {
    if (tool !== 'click' || pop) return;
    hovered = pick(e.target, e.altKey);
  }, true);
  doc.addEventListener('mouseleave', clearHover, true);

  doc.addEventListener('click', function (e) {
    if (inOverlay(e.target) || tool === 'browse') return;
    e.preventDefault(); e.stopPropagation();
    if (tool !== 'click' || pop) return;
    var el = pick(e.target, e.altKey);
    if (!el) return;
    var existing = null;
    for (var i = 0; i < comments.length; i++) {
      var c = comments[i];
      if ((c.kind || 'element') === 'element' && resolve(c) === el && (!c.scroll || !c.scroll.bound || nearY(c, el))) { existing = c; break; }
    }
    openPop(existing ? fromRec(existing, el) : { kind: 'element', el: el }, existing);
  }, true);

  ['mousedown', 'pointerdown', 'touchstart'].forEach(function (t) {
    doc.addEventListener(t, function (e) {
      if (tool === 'click' && !inOverlay(e.target)) { e.stopPropagation(); }
    }, true);
  });
  doc.addEventListener('submit', function (e) { if (tool !== 'browse') { e.preventDefault(); e.stopPropagation(); } }, true);

  /* ---------- text tool ---------------------------------------------------- */
  doc.addEventListener('mouseup', function (e) {
    if (tool !== 'text' || pop || inOverlay(e.target)) return;
    setTimeout(function () {
      var t = textPending();
      if (t) openPop(t, null);
    }, 10);
  }, true);

  function textPending() {
    var s = window.getSelection();
    if (!s || s.isCollapsed || !s.rangeCount) return null;
    var range = s.getRangeAt(0);
    var shown = s.toString().replace(/\s+/g, ' ').trim();
    if (!shown) return null;
    var anc = range.commonAncestorContainer;
    if (anc.nodeType !== 1) anc = anc.parentNode;
    if (!anc || inOverlay(anc)) return null;
    var el = pick(anc) || anc;
    if (!el.contains(range.startContainer) || !el.contains(range.endContainer)) el = anc;
    var pre = doc.createRange();
    pre.setStart(el, 0);
    pre.setEnd(range.startContainer, range.startOffset);
    var r = range.cloneRange();
    return { kind: 'text', el: el, range: r, raw: range.toString().slice(0, 4000), quote: shown.slice(0, 1000), offset: pre.toString().length };
  }

  /* ---------- box tool ---------------------------------------------------- */
  cover.addEventListener('mousedown', function (e) {
    if (e.button !== 0 || pop) return;
    e.preventDefault();
    drawing = { x0: e.clientX, y0: e.clientY };
    put(drawBox, { left: e.clientX, top: e.clientY, width: 0, height: 0 });
  });
  window.addEventListener('mousemove', function (e) {
    if (!drawing) return;
    put(drawBox, norm(drawing.x0, drawing.y0, e.clientX, e.clientY));
  }, true);
  window.addEventListener('mouseup', function (e) {
    if (!drawing) return;
    var r = norm(drawing.x0, drawing.y0, e.clientX, e.clientY);
    drawing = null;
    drawBox.style.display = 'none';
    if (r.width < 6 || r.height < 6) return;
    cover.style.display = 'none';
    var under = doc.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    cover.style.display = 'block';
    var el = pick(under);
    while (el && el !== doc.body && el !== doc.documentElement && !holds(el.getBoundingClientRect(), r)) el = el.parentElement;
    if (el === doc.body || el === doc.documentElement) el = null;
    var rel = null;
    if (el) {
      var a = el.getBoundingClientRect();
      rel = { x: +((r.left - a.left) / a.width).toFixed(5), y: +((r.top - a.top) / a.height).toFixed(5),
        w: +(r.width / a.width).toFixed(5), h: +(r.height / a.height).toFixed(5) };
    }
    var box = { x: Math.round(r.left + window.pageXOffset), y: Math.round(r.top + getY()), w: Math.round(r.width), h: Math.round(r.height) };
    openPop({ kind: 'box', el: el, rel: rel, box: box }, null);
  }, true);

  function norm(x0, y0, x1, y1) {
    return { left: Math.min(x0, x1), top: Math.min(y0, y1), width: Math.abs(x1 - x0), height: Math.abs(y1 - y0) };
  }
  function holds(a, r) {
    var ix = Math.max(0, Math.min(a.right, r.left + r.width) - Math.max(a.left, r.left));
    var iy = Math.max(0, Math.min(a.bottom, r.top + r.height) - Math.max(a.top, r.top));
    return ix * iy >= 0.9 * r.width * r.height;
  }

  /* ---------- keys ------------------------------------------------------ */
  function typing(e) {
    var t = e.target;
    return t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName));
  }
  doc.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
      if (drawing) { drawing = null; drawBox.style.display = 'none'; }
      if (pop) { closePop(); e.stopPropagation(); e.preventDefault(); }
      return;
    }
    if (pop || typing(e) || e.ctrlKey || e.metaKey || e.altKey) return;
    var k = (e.key || '').toLowerCase();
    if ('cvtb'.indexOf(k) >= 0 && k.length === 1) {
      e.preventDefault(); e.stopPropagation();
      ctx.key(k);
    }
  }, true);

  /* ---------- composer ------------------------------------------------------ */
  function fromRec(rec, el) {
    var t = { kind: rec.kind || 'element', el: el, rel: rec.rel, box: rec.box, raw: rec.raw, quote: rec.quote, offset: rec.offset };
    if (t.kind === 'text' && el) t.range = findQuote(el, rec.raw || rec.quote, rec.offset);
    return t;
  }
  function pendingRects(p) {
    if (p.kind === 'box') return rectsFor({ kind: 'box', rel: p.rel, box: p.box }, { el: p.el || null });
    if (p.kind === 'text' && p.range) {
      var rs = [].slice.call(p.range.getClientRects()).filter(function (q) { return q.width > 0.5; }).map(plain);
      if (rs.length) return rs;
    }
    return p.el ? [plain(p.el.getBoundingClientRect())] : [];
  }

  function closePop() {
    if (pop) { pop.remove(); pop = null; }
    pending = null;
    drawRects(selBoxes, [], 'sel');
    showHint('');
    if (ctx.popState) ctx.popState(false);
  }

  function openPop(target, rec) {
    closePop();
    pending = target;
    if (ctx.popState) ctx.popState(true);
    var d = target.el ? describe(target.el) : { label: 'the page', section: '', text: '', sel: '', path: '', tagName: '' };
    var label = d.label;
    if (target.kind === 'box') label = 'Area on ' + d.label;
    else if (target.kind === 'text') label = 'Text: ' + short(target.quote, 70);
    if (rec && rec.label) label = rec.kind === 'text' ? 'Text: ' + short(rec.quote, 70) : rec.label;
    var action = (rec && rec.action) || 'rework';
    var sc = rec ? rec.scroll : scrollCtx(target.el);

    pop = mk('div', 'rvx-pop');
    pop.innerHTML =
      '<header><span class="dot"></span><b></b><span class="num"></span></header>' +
      '<div class="where"></div><div class="quote"></div>' +
      '<div class="body"><textarea placeholder="What should change? Hungarian or English."></textarea>' +
      '<div class="rvx-acts"></div><div class="err"></div></div>' +
      '<div class="rvx-act"><button class="save">Save</button><button class="cancel">Cancel</button>' +
      '<button class="del">Delete</button><span class="tip">Enter saves · Shift+Enter new line</span></div>';
    pop.querySelector('b').textContent = label;
    pop.querySelector('.num').textContent = rec ? '#' + rec.n : 'new';
    var where = [d.section, sc && sc.track ? sc.track.label + ' at ' + Math.round(sc.track.progress * 100) + ' %' : '',
      sc ? 'scroll ' + Math.round((sc.progress || 0) * 100) + ' %' : ''].filter(Boolean).join(' · ');
    pop.querySelector('.where').textContent = where;
    if (!where) pop.querySelector('.where').style.display = 'none';
    var q = pop.querySelector('.quote');
    if (target.kind === 'text' && target.quote) q.textContent = '"' + target.quote + '"'; else q.style.display = 'none';
    var ta = pop.querySelector('textarea');
    ta.value = (rec && rec.comment) || '';
    var dot = pop.querySelector('.dot');
    var err = pop.querySelector('.err');

    var acts = pop.querySelector('.rvx-acts');
    function paintActs() {
      [].forEach.call(acts.children, function (b) {
        var a = actionOf(b.dataset.id);
        var on = a.id === action;
        b.className = on ? 'on' : '';
        b.style.background = on ? a.color : '#fff';
      });
      dot.style.background = actionOf(action).color;
    }
    ACTIONS.forEach(function (a) {
      var b = mk('button');
      b.type = 'button';
      b.dataset.id = a.id;
      b.textContent = a.label;
      var k = mk('span', 'k'); k.textContent = 'Alt+' + a.key; b.appendChild(k);
      b.addEventListener('click', function () { action = a.id; paintActs(); ta.focus(); });
      acts.appendChild(b);
    });
    paintActs();

    pop.querySelector('.cancel').addEventListener('click', closePop);
    var del = pop.querySelector('.del');
    if (rec) del.addEventListener('click', function () { ctx.remove(rec.id); closePop(); });
    else del.style.display = 'none';
    pop.querySelector('.save').addEventListener('click', save);
    // Esc never gets here: the document's capture listener closes the composer first
    ta.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); save(); return; }
      if (e.altKey && /^[1-5]$/.test(e.key)) { e.preventDefault(); action = ACTIONS[+e.key - 1].id; paintActs(); }
      e.stopPropagation();
    });

    function save() {
      var txt = ta.value.trim();
      if (!txt && NEEDS_TEXT[action]) {
        err.textContent = actionOf(action).label + ' needs a sentence.';
        err.style.display = 'block'; ta.focus(); return;
      }
      var payload;
      if (rec) {
        payload = { id: rec.id, action: action, comment: txt };
      } else {
        payload = {
          kind: target.kind, action: action, comment: txt, label: label, section: d.section, text: d.text,
          sel: d.sel, path: d.path, tagName: d.tagName, scroll: sc, title: doc.title
        };
        if (target.kind === 'box') { payload.box = target.box; payload.rel = target.rel; }
        if (target.kind === 'text') { payload.quote = target.quote; payload.raw = target.raw; payload.offset = target.offset; }
      }
      ctx.upsert(payload);
      try { window.getSelection().removeAllRanges(); } catch (e) {}
      closePop();
    }

    ov.appendChild(pop);
    placePop(union(pendingRects(target)));
    setTimeout(function () { ta.focus(); }, 30);
  }

  function placePop(r) {
    r = r || { left: innerWidth / 2, top: 80, width: 0, height: 0, right: innerWidth / 2, bottom: 80 };
    var w = Math.min(340, (innerWidth - 16) / Z) * Z, h = (pop.offsetHeight || 260) * Z;
    var underLeft = Math.max(8, Math.min(innerWidth - w - 8, r.left));   // left edge when neither side fits
    var left = r.left + r.width + 12;
    if (left + w > innerWidth - 8) left = r.left - w - 12;
    if (left < 8) left = underLeft;
    var top = Math.max(8, r.top);
    if (left === underLeft) {
      // narrow viewport: below the target, or above when there is no room
      top = r.top + r.height + 10;
      if (top + h > innerHeight - 8) top = Math.max(8, r.top - h - 10);
    }
    top = Math.min(top, Math.max(8, innerHeight - h - 8));
    pop.style.left = left + 'px';
    pop.style.top = top + 'px';
  }

  /* ---------- pins ------------------------------------------------------ */
  function nearY(rec, el) {
    var y = targetY(rec, el);
    return y == null || Math.abs(getY() - y) < viewH() * 0.5;
  }

  function buildPins() {
    pins.forEach(function (p) { p.node.remove(); });
    pins = [];
    peek = null;                       // the hovered pin is gone; so are its tooltip and outline
    tip.style.display = 'none';
    comments.forEach(function (rec) {
      var node = mk('div', 'rvx-pin' + (rec.status === 'done' ? ' done' : ''));
      node.textContent = rec.n;
      node.style.background = actionOf(rec.action).color;
      var p = { rec: rec, el: undefined, range: undefined, node: node, retryAt: 0 };
      node.addEventListener('mouseenter', function () {
        peek = p;
        tip.textContent = '#' + rec.n + ' ' + actionOf(rec.action).label + (rec.status === 'done' ? ' (done)' : '') + '\n' + (rec.comment || '(no note)') + (rec.reply ? '\nClaude: ' + rec.reply : '');
        var r = node.getBoundingClientRect();
        tip.style.left = Math.max(4, Math.min(r.right + 6, innerWidth - 310 * Z)) + 'px';
        tip.style.top = Math.max(4, Math.min(r.top, innerHeight - 90 * Z)) + 'px';
        tip.style.display = 'block';
      });
      node.addEventListener('mouseleave', function () { peek = null; tip.style.display = 'none'; });
      node.addEventListener('click', function (e) {
        e.preventDefault(); e.stopPropagation();
        tip.style.display = 'none';
        resolvePin(p, true);
        openPop(fromRec(rec, p.el), rec);
      }, true);
      ov.appendChild(node);
      pins.push(p);
    });
    reportPins();
  }

  function resolvePin(p, force) {
    if (!force && p.el !== undefined && (p.el || Date.now() < p.retryAt)) return;
    p.el = resolve(p.rec);
    p.range = (p.el && p.rec.kind === 'text') ? findQuote(p.el, p.rec.raw || p.rec.quote, p.rec.offset) : null;
    if (!p.el) p.retryAt = Date.now() + 1500;
  }

  var lastMissing = '';
  function reportPins() {
    var missing = pins.filter(function (p) { resolvePin(p); return !p.el && !(p.rec.kind === 'box' && p.rec.box); })
      .map(function (p) { return p.rec.id; });
    var key = missing.join(',');
    if (key !== lastMissing && ctx.onPins) { lastMissing = key; ctx.onPins(missing); }
  }

  function focusRec(rec) {
    restore(rec, true);
    var p = null;
    for (var i = 0; i < pins.length; i++) if (pins[i].rec.id === rec.id) p = pins[i];
    if (p) resolvePin(p, true);
    setTimeout(function () { flash = p || { rec: rec }; flashUntil = Date.now() + 1700; }, rec.scroll && rec.scroll.bound ? 120 : 420);
  }

  /* ---------- paint loop -------------------------------------------------- */
  function paint() {
    var r = tool === 'click' && hovered && !pop && hovered.isConnected ? hovered.getBoundingClientRect() : null;
    if (r && r.width && r.height) {
      put(hoverBox, r, 1);
      chip.textContent = labelOf(hovered);
      chip.style.display = 'block';
      var ct = r.top - 27 * Z;
      chip.style.left = Math.max(4, Math.min(r.left, innerWidth - 220 * Z)) + 'px';
      chip.style.top = (ct < 4 ? Math.min(r.bottom + 6, innerHeight - 26 * Z) : ct) + 'px';
    } else {
      hideHover();
    }

    drawRects(selBoxes, pending ? pendingRects(pending) : [], 'sel', 1);

    var stacks = {};
    pins.forEach(function (p) {
      resolvePin(p);
      var rs = rectsFor(p.rec, { el: p.el || null, range: p.range });
      var u = union(rs);
      var bound = p.rec.scroll && p.rec.scroll.bound;
      var show = u && (u.width || u.height) && u.bottom > -40 && u.top < innerHeight + 40 && (!bound || nearY(p.rec, p.el));
      if (!show) { p.node.style.display = 'none'; return; }
      var key = Math.round(u.left / 8) + ':' + Math.round(u.top / 8);
      var k = stacks[key] = (stacks[key] || 0) + 1;
      p.node.style.left = Math.min(Math.max(2, u.left - 13 * Z + (k - 1) * 22 * Z), innerWidth - 30 * Z) + 'px';
      p.node.style.top = Math.min(Math.max(2, u.top - 13 * Z), innerHeight - 30 * Z) + 'px';
      p.node.style.display = 'flex';
    });

    drawRects(peekBoxes, peek ? rectsFor(peek.rec, { el: peek.el || null, range: peek.range }) : [], 'peek', 2);

    if (flash && Date.now() < flashUntil) {
      drawRects(flashBoxes, rectsFor(flash.rec, flash.el !== undefined ? { el: flash.el || null, range: flash.range } : null), 'flash', 3);
    } else if (flash) { flash = null; drawRects(flashBoxes, [], 'flash'); }
  }

  var tick = 0;
  (function loop() {
    try { paint(); if (++tick % 60 === 0) reportPins(); } catch (e) { /* never break the page */ }
    requestAnimationFrame(loop);
  })();

  setTool(ctx.tool || 'click');
  buildPins();
  if (ctx.onReady) ctx.onReady({ title: doc.title, path: location.pathname + location.search });
})();
