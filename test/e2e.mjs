// review-page end-to-end test: drives the real review UI headless with a real mouse.
//
//   node test/e2e.mjs --base http://127.0.0.1:8900 --store <review folder>
//        [--scene .act--mirror --scene-at 0.47]      a pinned scene to note at a given progress
//        [--text-sel "main p"]                         an element whose words get selected
//        [--view both|fit]                             which frames to expect (default: both)
//        [--click-sel ".tl span"]                       what the click test clicks (default h1, else h2/p)
//        [--shot <png>]                                screenshot of the tool at the end
//
// Exits 1 on the first failed check. Uses a fresh store: it deletes nothing but expects to start
// from zero notes, so point it at a throwaway review (zz-test-*).
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const { chromium } = createRequire('D:/WORK/package.json')('playwright-core');
const argv = process.argv.slice(2);
const arg = (k, d) => (argv.includes(k) ? argv[argv.indexOf(k) + 1] : d);
const BASE = arg('--base');
const STORE = arg('--store');
const SCENE = arg('--scene');
const SCENE_AT = parseFloat(arg('--scene-at', '0.47'));
const TEXT_SEL = arg('--text-sel', 'p');
const VIEW = arg('--view', 'both');
const SHOT = arg('--shot');
const TOOL = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

let failures = 0;
const ok = (cond, msg, extra) => {
  console.log(`${cond ? 'PASS' : 'FAIL'}  ${msg}${extra !== undefined ? '  ' + JSON.stringify(extra) : ''}`);
  if (!cond) failures++;
};
const items = () => {
  const f = path.join(STORE, 'comments.json');
  if (!fs.existsSync(f)) return [];
  const d = JSON.parse(fs.readFileSync(f, 'utf8'));
  return Array.isArray(d) ? d : d.items;
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const chrome = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
// Real scrollbars, as on Dave's desktop: Playwright hides them by default, and that hid the bug where
// the phone frame's own scrollbar narrowed the page to 375 px (the check in section 5).
const browser = await chromium.launch({ headless: true, executablePath: chrome, ignoreDefaultArgs: ['--hide-scrollbars'] });
const ctx = await browser.newContext({ viewport: { width: 1680, height: 1000 } });
const page = await ctx.newPage();
const errors = [];
page.on('pageerror', (e) => errors.push('page: ' + e.message));
page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });

await page.goto(BASE + '/__review/', { waitUntil: 'load' });
const nFrames = VIEW === 'both' ? 2 : 1;
await page.waitForFunction((n) => {
  const fr = [...document.querySelectorAll('.frames iframe')];
  return fr.length === n && fr.every((f) => f.contentWindow && f.contentWindow.__rvAnnotator && f.contentDocument.getElementById('__rv'));
}, nFrames, { timeout: 30000 });
ok(true, `tool loaded with ${nFrames} annotated frame(s)`);
const startCount = items().length;
if (startCount) {
  console.error(`the store already holds ${startCount} note(s); clicking a noted element edits it instead of adding one. Use a fresh zz-test-* review.`);
  process.exit(2);
}

const frameEl = (i) => page.locator('.frames iframe').nth(i);
const frameOf = async (i) => (await frameEl(i).elementHandle()).contentFrame();

// viewport point inside frame i -> page point (the iframe is CSS-scaled)
async function toPage(i, x, y) {
  const box = await frameEl(i).boundingBox();
  const w = await (await frameOf(i)).evaluate(() => innerWidth);
  const s = box.width / w;
  return { x: box.x + x * s, y: box.y + y * s };
}
async function rectIn(i, sel) {
  const f = await frameOf(i);
  return f.evaluate((sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    el.scrollIntoView({ block: 'center', behavior: 'instant' });
    const r = el.getBoundingClientRect();
    return { x: r.left, y: r.top, w: r.width, h: r.height };
  }, sel);
}
async function clickIn(i, sel, opts = {}) {
  const r = await rectIn(i, sel);
  if (!r) return false;
  await sleep(250);
  const p = await toPage(i, r.x + r.w / 2, r.y + Math.min(r.h / 2, 30));
  await page.mouse.move(p.x, p.y);
  await sleep(120);
  await page.mouse.click(p.x, p.y, opts);
  return true;
}
async function popOpen(i) {
  const f = await frameOf(i);
  return f.waitForFunction(() => document.activeElement && document.activeElement.closest &&
    !!document.activeElement.closest('#__rv .rvx-pop'), null, { timeout: 4000 }).then(() => true, () => false);
}
async function writeNote(text, actionKey) {
  if (actionKey) await page.keyboard.press('Alt+' + actionKey);
  await page.keyboard.type(text);
  await page.keyboard.press('Enter');
  await sleep(700);
}

// 1. click tool: a heading in the desktop frame
const headSel = arg('--click-sel') || ((await (await frameOf(0)).evaluate(() => !!document.querySelector('h1'))) ? 'h1' : 'h2, p');
await clickIn(0, headSel);
ok(await popOpen(0), 'click on a heading opens the note composer');
if (SHOT) { await page.keyboard.type('Composer at frame scale'); await page.screenshot({ path: SHOT.replace(/\.png$/, '-composer.png') }); await page.keyboard.press('Control+A'); await page.keyboard.press('Backspace'); }
await writeNote('E2E: heading note');
let it = items();
ok(it.length === startCount + 1 && it.at(-1).kind === 'element', 'element note saved', it.at(-1) && it.at(-1).label);
ok(it.at(-1).viewport === (VIEW === 'both' ? 'desktop' : 'fit') && it.at(-1).scroll && it.at(-1).scroll.y >= 0, 'note carries viewport + scroll', it.at(-1).scroll);
ok(fs.readFileSync(path.join(STORE, 'REVIEW-NOTES.md'), 'utf8').includes('E2E: heading note'), 'REVIEW-NOTES.md rewritten on save');

// 2. pinned scene at a given progress (scroll-driven pages)
if (SCENE) {
  const f = await frameOf(0);
  const y = await f.evaluate(({ sel, at }) => {
    const sec = document.querySelector(sel);
    const st = [sec, ...sec.querySelectorAll('*')].find((e) => getComputedStyle(e).position === 'sticky');
    const track = st.parentElement;
    const top = track.getBoundingClientRect().top + scrollY;
    const y = top + at * (track.offsetHeight - st.offsetHeight);
    scrollTo({ top: y, behavior: 'instant' });
    return Math.round(y);
  }, { sel: SCENE, at: SCENE_AT });
  await sleep(900);
  const target = await f.evaluate((sel) => {
    const sec = document.querySelector(sel);
    const c = sec.querySelector('canvas') || sec.querySelector('img') || sec.querySelector('h2,p');
    const r = c.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2, tag: c.tagName };
  }, SCENE);
  const p = await toPage(0, target.x, target.y);
  await page.mouse.move(p.x, p.y);
  await sleep(150);
  await page.mouse.click(p.x, p.y);
  ok(await popOpen(0), `click on the scene's ${target.tag} opens the composer`);
  await writeNote('E2E: scene note', '4');
  it = items();
  const sc = it.at(-1).scroll || {};
  ok(it.at(-1).action === 'discuss', 'Alt+4 picked Discuss', it.at(-1).action);
  ok(sc.bound && sc.track && Math.abs(sc.track.progress - SCENE_AT) < 0.03, 'scene note records the pinned progress', sc.track);
  ok(Math.abs(sc.y - y) < 3, 'scene note records the scroll position', { saved: sc.y, scrolled: y });
  await f.evaluate(() => scrollTo({ top: 0, behavior: 'instant' }));
  await sleep(300);
}

// 3. box tool (V pressed in the tool page)
await page.mouse.click(5, 300);   // focus the tool page (sidebar), not a frame
await page.keyboard.press('v');
await sleep(300);
{
  const p0 = await toPage(0, 200, 160), p1 = await toPage(0, 520, 360);
  await page.mouse.move(p0.x, p0.y);
  await page.mouse.down();
  await page.mouse.move((p0.x + p1.x) / 2, (p0.y + p1.y) / 2, { steps: 4 });
  await page.mouse.move(p1.x, p1.y, { steps: 4 });
  await page.mouse.up();
  ok(await popOpen(0), 'dragging a box opens the composer');
  await writeNote('E2E: box note', '2');
  it = items();
  const b = it.at(-1);
  ok(b.kind === 'box' && b.box && Math.abs(b.box.w - 320) < 4 && Math.abs(b.box.h - 200) < 4, 'box note saved with its size', b.box);
  ok(!b.rel || (b.rel.w > 0 && b.rel.w <= 1.001), 'box anchored relative to an element', { rel: b.rel, on: b.label });
}

// 4. text tool
await page.mouse.click(5, 300);
await page.keyboard.press('t');
await sleep(300);
{
  const f = await frameOf(0);
  const r = await f.evaluate((sel) => {
    const els = [...document.querySelectorAll(sel)].filter((e) => (e.innerText || '').trim().length > 30 && e.getBoundingClientRect().width > 100);
    const el = els[0];
    if (!el) return null;
    const tw = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    let n; while ((n = tw.nextNode()) && n.data.trim().length < 12);
    n.parentElement.scrollIntoView({ block: 'center', behavior: 'instant' });
    const rg = document.createRange();
    rg.setStart(n, 0); rg.setEnd(n, Math.min(n.data.length, 14));
    const rr = rg.getClientRects()[0];
    return { x0: rr.left + 1, y: rr.top + rr.height / 2, x1: rr.right - 1, expect: rg.toString().replace(/\s+/g, ' ').trim() };
  }, TEXT_SEL);
  if (!r) { ok(false, 'no text element found for ' + TEXT_SEL); }
  else {
    await sleep(250);
    const a = await toPage(0, r.x0, r.y), b2 = await toPage(0, r.x1, r.y);
    await page.mouse.move(a.x, a.y);
    await page.mouse.down();
    await page.mouse.move(b2.x, b2.y, { steps: 6 });
    await page.mouse.up();
    ok(await popOpen(0), 'selecting text opens the composer');
    await writeNote('E2E: text note', '3');
    it = items();
    const t = it.at(-1);
    ok(t.kind === 'text' && t.quote && r.expect.startsWith(t.quote.slice(0, 6)), 'text note quotes the selection', { quote: t.quote, expect: r.expect });
  }
}

// 5. mobile frame
if (VIEW === 'both') {
  const layoutW = await (await frameOf(1)).evaluate(() => document.documentElement.clientWidth);
  ok(layoutW === 390, 'phone frame lays out at the full 390 px, no desktop scrollbar (frame.css)', { clientWidth: layoutW });
  await page.mouse.click(5, 300);
  await page.keyboard.press('c');
  await sleep(300);
  await clickIn(1, headSel);
  ok(await popOpen(1), 'click in the phone frame opens the composer');
  await writeNote('E2E: phone note');
  it = items();
  ok(it.at(-1).viewport === 'mobile' && it.at(-1).vw === 390, 'phone note keyed to the 390 px viewport', { vp: it.at(-1).viewport, vw: it.at(-1).vw });
}

// 6. Claude answers + closes from the CLI; the open review picks it up by polling
const first = items()[startCount];
execFileSync('python', [path.join(TOOL, 'notes.py'), STORE, 'done', String(first.n), '--reply', 'E2E reply from notes.py']);
await sleep(3200);
const listTxt = await page.locator('#list').innerText();
ok(!listTxt.includes('E2E: heading note'), 'closed note left the Open list without a reload');
await page.locator('#filters button[data-f="all"]').click();
await sleep(300);
ok((await page.locator('#list').innerText()).includes('E2E reply from notes.py'), 'Claude reply shows under the note');
await page.locator('#filters button[data-f="open"]').click();

// 7. sidebar focus returns to the scene moment
if (SCENE) {
  const sceneItem = items().find((x) => x.comment === 'E2E: scene note');
  await page.locator('#list .item', { hasText: 'E2E: scene note' }).click();
  await sleep(1500);
  const y = await (await frameOf(0)).evaluate(() => Math.round(scrollY));
  ok(Math.abs(y - sceneItem.scroll.y) < 4, 'clicking the note restores the scene scroll position', { y, saved: sceneItem.scroll.y });
  const pinShown = await (await frameOf(0)).evaluate((n) => [...document.querySelectorAll('#__rv .rvx-pin')].some((p) => p.textContent === String(n) && p.style.display === 'flex'), sceneItem.n);
  ok(pinShown, 'the scene pin is visible at that moment');
}

// 8. reload keeps the pins
await page.reload({ waitUntil: 'load' });
await page.waitForFunction(() => [...document.querySelectorAll('.frames iframe')].every((f) => f.contentWindow && f.contentWindow.__rvAnnotator), null, { timeout: 30000 });
await sleep(800);
const pins = await (await frameOf(0)).evaluate(() => document.querySelectorAll('#__rv .rvx-pin').length);
const expectPins = items().filter((x) => x.viewport === (VIEW === 'both' ? 'desktop' : 'fit') && x.page === first.page).length;
ok(pins === expectPins, 'pins rebuilt after reload', { pins, expectPins });

// 9. browse tool follows navigation in both frames
await page.mouse.click(5, 300);
await page.keyboard.press('b');
await sleep(300);
const before = await page.inputValue('#page');
const href = await (await frameOf(0)).evaluate(() => {
  const a = [...document.querySelectorAll('a[href]')].find((x) => {
    const u = new URL(x.href, location.href);
    const r = x.getBoundingClientRect();
    return u.origin === location.origin && u.pathname !== location.pathname && !u.hash && r.width > 20 && !x.target && !/\.(pdf|jpg|png|webp|zip)$/i.test(u.pathname);
  });
  return a ? new URL(a.href, location.href).pathname : null;
});
if (href) {
  const f0 = await frameOf(0);
  await f0.evaluate((h) => { const a = [...document.querySelectorAll('a[href]')].find((x) => new URL(x.href, location.href).pathname === h); a.scrollIntoView({ block: 'center', behavior: 'instant' }); }, href);
  await sleep(300);
  const r = await f0.evaluate((h) => { const a = [...document.querySelectorAll('a[href]')].find((x) => new URL(x.href, location.href).pathname === h); const q = a.getBoundingClientRect(); return { x: q.left + Math.min(q.width / 2, 20), y: q.top + q.height / 2 }; }, href);
  const p = await toPage(0, r.x, r.y);
  await page.mouse.click(p.x, p.y);
  await sleep(2500);
  const after = await page.inputValue('#page');
  ok(after !== before, 'browsing a link updates the page box', { before, after, href });
  if (VIEW === 'both') {
    const other = await (await frameOf(1)).evaluate(() => location.pathname);
    ok(other === new URL(after, BASE).pathname, 'the phone frame follows the navigation', { other, after });
  }
} else ok(true, 'no same-origin link to browse (skipped)');

if (SHOT) {
  await page.keyboard.press('c');
  await page.locator('#page').fill(first.page);
  await page.locator('#page').press('Enter');
  await sleep(2500);
  await page.screenshot({ path: SHOT });
  console.log('tool screenshot: ' + SHOT);
}

const real = errors.filter((e) => !/favicon|beacon|cloudflareinsights|ERR_|net::/i.test(e));
ok(real.length === 0, 'no page errors', real.slice(0, 5));
await browser.close();
console.log(failures ? `\n${failures} check(s) FAILED` : '\nall checks passed');
process.exit(failures ? 1 : 0);
