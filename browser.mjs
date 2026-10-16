// review-page: the headless browser for shots.mjs and test/e2e.mjs.
//
// playwright-core resolves like any Node import, from this folder upward: `npm install` here, or
// any node_modules in a parent folder that already has it.
// Browser, first that works: $REVIEW_PAGE_CHROME, "chrome" (a path) in config.local.json, the
// installed Google Chrome, Playwright's own Chromium (`npx playwright install chromium`).
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const TOOL_DIR = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);

function localConfig() {
  const f = path.join(TOOL_DIR, 'config.local.json');
  if (!fs.existsSync(f)) return {};
  try {
    return JSON.parse(fs.readFileSync(f, 'utf8').replace(/^﻿/, ''));
  } catch (e) {
    console.error(`review-page: cannot read ${f}: ${e.message}`);
    process.exit(2);
  }
}

function playwright() {
  try {
    return require('playwright-core');
  } catch {
    console.error(`review-page: playwright-core is not installed. Run \`npm install\` in ${TOOL_DIR}.`);
    process.exit(2);
  }
}

export async function launch(options = {}) {
  const { chromium } = playwright();
  const exe = process.env.REVIEW_PAGE_CHROME || localConfig().chrome;
  if (exe) return chromium.launch({ headless: true, ...options, executablePath: exe });
  try {
    return await chromium.launch({ headless: true, ...options, channel: 'chrome' });
  } catch (chromeErr) {
    try {
      return await chromium.launch({ headless: true, ...options });
    } catch {
      console.error('review-page: no browser found. Install Google Chrome, set REVIEW_PAGE_CHROME to a\n' +
        'Chromium-based browser, or run `npx playwright install chromium`.\n' + chromeErr.message.split('\n')[0]);
      process.exit(2);
    }
  }
}
