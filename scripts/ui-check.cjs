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
    await page.goto('http://127.0.0.1:3000');
    await page.getByRole('heading', { name: '我的资料库' }).waitFor();
    await page.locator('.hero-character img').evaluate(img => img.decode());
    const brand = await page.locator('.app').evaluate(el => getComputedStyle(el).getPropertyValue('--brand').trim());
    if (brand !== '#00aeec') throw Error('Bilibili blue token is missing');
    await page.screenshot({ path: path.join(out, 'home-desktop.png'), fullPage: true });
    const overflow = () => page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
    if (await overflow()) throw Error('Desktop overflow');
    await page.getByRole('button', { name: '切换深色' }).click();
    await page.screenshot({ path: path.join(out, 'home-dark.png'), fullPage: true });
    await page.getByRole('button', { name: '切换浅色' }).click();
    await page.setViewportSize({ width: 390, height: 844 });
    const escapedCover = await page.locator('.cover img').evaluateAll(images => images.some(img => img.getBoundingClientRect().height > img.parentElement.getBoundingClientRect().height + 1));
    if (escapedCover) throw Error('Video thumbnail overlaps card text on mobile');
    await page.screenshot({ path: path.join(out, 'home-mobile.png'), fullPage: true });
    if (await overflow()) throw Error('Mobile overflow');
    await page.setViewportSize({ width: 1440, height: 1000 });
    const card = page.locator('.video-card').filter({ hasText: '天空颜色的秘密' }).first();
    if (await card.count()) {
      await card.click(); await page.getByRole('tab', { name: '文稿核对', exact: true }).click(); await page.getByRole('heading', { name: '转录笔记' }).waitFor();
      await page.locator('.segment').first().waitFor();
      if (await page.locator('.studio-companion img').count()) throw Error('Studio portrait should be removed');
      await page.screenshot({ path: path.join(out, 'workspace-desktop.png'), fullPage: true });
      const originalTab = page.getByRole('tab', { name: /原始时间轴|原始稿/ });
      const readableTab = page.getByRole('tab', { name: '可读稿', exact: true });
      await readableTab.click(); await originalTab.click();
      if (await page.locator('.segment').count()) {
        await page.getByRole('textbox', { name: '搜索文稿' }).fill('天空');
        if (!(await page.locator('mark').count())) throw Error('Transcript search found no matches');
        await page.screenshot({ path: path.join(out, 'workspace-search.png'), fullPage: true });
        await page.getByRole('textbox', { name: '搜索文稿' }).fill('');
        await readableTab.click(); await page.getByRole('button', { name: '编辑文稿', exact: true }).click();
        const editor = page.getByRole('textbox', { name: /编辑可读稿|编辑片段 1$/ }).first();
        const before = await editor.inputValue();
        await editor.fill(before + '\n\n界面验收编辑。');
        await page.getByRole('button', { name: '保存修改' }).click();
        await page.getByRole('button', { name: '编辑文稿', exact: true }).waitFor();
        // Restore the original readable text after verifying a real edit.
        await page.getByRole('button', { name: '编辑文稿', exact: true }).click();
        await editor.fill(before); await page.getByRole('button', { name: '保存修改' }).click();
        await page.getByRole('button', { name: '编辑文稿', exact: true }).waitFor();
        await originalTab.click();
        await page.getByRole('tab', { name: '来源问答', exact: true }).click(); await page.getByRole('textbox', { name: '向来源提问' }).fill('天空');
        await page.getByRole('button', { name: '发送来源问题' }).click();
        await page.locator('.chat-answer').waitFor();
        if (!(await page.locator('.learning-turn .learning-citations button').count())) throw Error('Assistant returned no source citations');
        await page.locator('.learning-turn .learning-citations button').first().click(); await page.getByRole('button', { name: '在文稿中核对 / 重听' }).click();
        await page.getByLabel('导出文稿').click();
        const downloadPromise = page.waitForEvent('download');
        await page.getByRole('link', { name: 'SRT · 原始字幕' }).click();
        const download = await downloadPromise;
        const data = path.join(__dirname, '../data'); fs.mkdirSync(data, { recursive: true });
        await download.saveAs(path.join(data, 'ui-export.srt'));
        await page.getByLabel('导出文稿').click();
        await page.screenshot({ path: path.join(out, 'workspace-desktop.png'), fullPage: true });
        await page.getByRole('button', { name: '切换深色' }).click();
        await page.screenshot({ path: path.join(out, 'workspace-dark.png'), fullPage: true });
        await page.getByRole('button', { name: '切换浅色' }).click();
      }
      await page.setViewportSize({ width: 390, height: 844 });
      await page.screenshot({ path: path.join(out, 'workspace-mobile.png'), fullPage: true });
      if (await overflow()) throw Error('Workspace mobile overflow');
    }
    if (errors.length) throw Error(errors.join('\n'));
    console.log('UI check passed: desktop/mobile, light/dark, available transcript interactions, no JS errors.');
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
