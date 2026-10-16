// review-page: screenshot every open note at the viewport and scroll moment the reviewer wrote it
// in, with the noted area outlined, so Claude sees exactly what the reviewer saw.
//
//   node shots.mjs --base http://127.0.0.1:8901 --store <reviews home>/<slug> [--n 3,5] [--all]
//
// Normally run through `python notes.py <slug> shots`, which starts the review server first.
// Writes <store>/shots/n-<n>.png and <store>/shots/index.json. The browser comes from browser.mjs.
import fs from 'node:fs';
import path from 'node:path';
import { launch } from './browser.mjs';

const argv = process.argv.slice(2);
const arg = (k, d) => (argv.includes(k) ? argv[argv.indexOf(k) + 1] : d);
const BASE = arg('--base');
const STORE = arg('--store');
if (!BASE || !STORE) {
  console.error('usage: node shots.mjs --base http://127.0.0.1:<port> --store <review folder> [--n 1,2] [--all]');
  process.exit(2);
}
const ONLY = (arg('--n', '') || '').split(',').filter(Boolean);
const ALL = argv.includes('--all');

const data = JSON.parse(fs.readFileSync(path.join(STORE, 'comments.json'), 'utf8'));
const target = JSON.parse(fs.readFileSync(path.join(STORE, 'target.json'), 'utf8'));
let items = (Array.isArray(data) ? data : data.items || []);
items = ONLY.length ? items.filter((i) => ONLY.includes(String(i.n))) : items.filter((i) => ALL || i.status !== 'done');
if (!items.length) { console.log('no notes to shoot'); process.exit(0); }

const COLOR = { remove: '#e5484d', rework: '#f5a524', comment: '#4c8dff', discuss: '#a06bff', add: '#27a644' };
const SIZE = { desktop: [1440, 900], mobile: [390, 844] };
const outDir = path.join(STORE, 'shots');
fs.mkdirSync(outDir, { recursive: true });

const browser = await launch();
const contexts = new Map();
async function contextFor(w, h) {
  const key = w + 'x' + h;
  if (contexts.has(key)) return contexts.get(key);
  const ctx = await browser.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 1 });
  await ctx.addInitScript(({ session, local }) => {
    window.__REVIEW_SHOT__ = true;
    try { for (const [k, v] of Object.entries(session || {})) sessionStorage.setItem(k, v); } catch (e) {}
    try { for (const [k, v] of Object.entries(local || {})) localStorage.setItem(k, v); } catch (e) {}
  }, { session: target.session, local: target.local });
  contexts.set(key, ctx);
  return ctx;
}

const results = [];
for (const it of items.sort((a, b) => a.n - b.n)) {
  const [w, h] = SIZE[it.viewport] || [Math.max(320, it.vw || 1200), Math.max(300, it.vh || 900)];
  const ctx = await contextFor(w, h);
  const page = await ctx.newPage();
  const file = path.join(outDir, `n-${it.n}.png`);
  fs.rmSync(file, { force: true });    // a failed shot must never leave an older PNG looking current
  let found = false;
  let shot = false;
  try {
    await page.goto(new URL(it.page || '/', BASE).href, { waitUntil: 'load', timeout: 45000 });
    await page.waitForTimeout(700);
    await page.addScriptTag({ url: new URL('/__review/annotator.js', BASE).href });
    await page.evaluate((rec) => window.__review.restore(rec), it);
    await page.waitForTimeout(1100);   // scroll-driven scenes settle, lazy images arrive
    const rects = await page.evaluate((rec) => window.__review.rects(rec), it);
    found = rects.length > 0;
    await page.evaluate(({ rects, n, color, label }) => {
      const wrap = document.createElement('div');
      wrap.style.cssText = 'position:fixed;inset:0;pointer-events:none;z-index:2147483646';
      for (const q of rects) {
        // a full-screen element (a pinned scene's backdrop) gets its outline drawn just inside the viewport
        const l = Math.max(q.left, 5), t = Math.max(q.top, 5);
        const r = { left: l, top: t, width: Math.min(q.left + q.width, innerWidth - 5) - l, height: Math.min(q.top + q.height, innerHeight - 5) - t };
        if (r.width <= 0 || r.height <= 0) continue;
        const b = document.createElement('div');
        b.style.cssText = `position:fixed;left:${r.left - 3}px;top:${r.top - 3}px;width:${r.width + 6}px;height:${r.height + 6}px;` +
          `border:3px solid ${color};border-radius:4px;box-shadow:0 0 0 2px rgba(255,255,255,.7)`;
        wrap.appendChild(b);
      }
      const tag = document.createElement('div');
      const top = rects.length ? Math.max(4, rects[0].top - 30) : 8;
      const left = rects.length ? Math.max(4, Math.min(rects[0].left, innerWidth - 260)) : 8;
      tag.textContent = `#${n} ${label}`;
      tag.style.cssText = `position:fixed;left:${left}px;top:${top}px;background:${color};color:#fff;` +
        'font:700 13px/1 system-ui,sans-serif;padding:6px 9px;border-radius:5px;max-width:250px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis';
      wrap.appendChild(tag);
      document.documentElement.appendChild(wrap);
    }, { rects, n: it.n, color: COLOR[it.action] || '#4c8dff', label: it.action || '' });
    await page.screenshot({ path: file });
    shot = true;
  } catch (e) {
    console.error(`#${it.n}: ${e.message.split('\n')[0]}`);
  }
  await page.close();
  results.push({ n: it.n, file: shot ? file : null, found, page: it.page, viewport: it.viewport, comment: it.comment });
  console.log(`#${it.n}  ${!shot ? 'FAILED, no screenshot' : found ? 'outlined' : 'element not found (page view only)'}  ${shot ? file : ''}`);
}
fs.writeFileSync(path.join(outDir, 'index.json'), JSON.stringify(results, null, 2));
await browser.close();
