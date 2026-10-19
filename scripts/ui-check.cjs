// Uses an installed Playwright module; optional BILILM_PLAYWRIGHT points at a bundled runtime.
const { chromium } = require(process.env.BILILM_PLAYWRIGHT || 'playwright');
const path = require('node:path');
const fs = require('node:fs');

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  const out = path.join(__dirname, '../docs/screenshots'); fs.mkdirSync(out, { recursive: true });
  try {
    await page.addInitScript(() => localStorage.setItem('bililm-ai-enabled', 'false'));
    await page.route('**/api/videos', route => route.fulfill({json:[]}));
    await page.route('**/api/jobs', route => route.fulfill({json:[]}));
    await page.goto('http://127.0.0.1:3000');
    await page.getByRole('heading', { name: '我的资料库' }).waitFor();
    if (await page.locator('.hero-character').count()) throw Error('Homepage illustration should be removed');
    const brand = await page.locator('.app').evaluate(el => getComputedStyle(el).getPropertyValue('--brand').trim());
    if (brand !== '#00aeec') throw Error('Bilibili blue token is missing');
    await page.screenshot({ path: path.join(out, 'home-desktop.png'), fullPage: true });
    const overflow = () => page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
    if (await overflow()) throw Error('Desktop overflow');
    await page.setViewportSize({ width: 1906, height: 1000 });
    const form = await page.locator('.import-box').boundingBox(), library = await page.locator('.library-section').boundingBox();
    if (Math.abs(form.width-library.width)>2) throw Error('Import area should align with library');
    await page.screenshot({ path: path.join(out, 'home-wide.png'), fullPage: true });
    if (await overflow()) throw Error('Wide desktop overflow');
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.getByRole('button', { name: '切换深色' }).click();
    await page.screenshot({ path: path.join(out, 'home-dark.png'), fullPage: true });
    await page.getByRole('button', { name: '切换浅色' }).click();
    await page.setViewportSize({ width: 390, height: 844 });
    const escapedCover = await page.locator('.cover img').evaluateAll(images => images.some(img => img.getBoundingClientRect().height > img.parentElement.getBoundingClientRect().height + 1));
    if (escapedCover) throw Error('Video thumbnail overlaps card text on mobile');
    await page.screenshot({ path: path.join(out, 'home-mobile.png'), fullPage: true });
    if (await overflow()) throw Error('Mobile overflow');
    await page.setViewportSize({ width: 1440, height: 1000 });
    if (errors.length) throw Error(errors.join('\n'));
    console.log('Homepage passed: blue theme, dark mode, desktop/mobile layout; empty library fixture, no external AI.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
