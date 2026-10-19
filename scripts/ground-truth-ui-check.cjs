// Read-only browser acceptance; never saves references, downloads models or starts ASR.
const { chromium } = require(process.env.BILILM_PLAYWRIGHT || 'playwright');
const path = require('node:path');
const fs = require('node:fs');
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [], mutations = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('request', r => { if (r.method() !== 'GET' && r.url().includes('/api/')) mutations.push(r.url()); });
  const out = path.join(__dirname, '../docs/screenshots'); fs.mkdirSync(out, { recursive: true });
  const assert = (condition, message) => { if (!condition) throw Error(message); };
  const noOverflow = async () => assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Horizontal overflow');
  try {
    await page.goto('http://127.0.0.1:3000');
    await page.getByRole('heading', { name: '我的资料库' }).waitFor();
    assert(await page.locator('.hero-character').count() === 0, 'Homepage illustration should be removed');
    await noOverflow(); await page.screenshot({ path: path.join(out, 'phase2-home-desktop.png'), fullPage: true });
    await page.locator('.quality-controls summary').click();
    const optional = page.getByLabel('识别后端', { exact: true }).locator('option[value="sensevoice"]');
    if (!(await optional.evaluate(option => option.disabled))) {
      await page.getByLabel('识别后端', { exact: true }).selectOption('sensevoice');
      assert(await page.getByLabel('转录质量', { exact: true }).inputValue() === 'SenseVoiceSmall', 'SenseVoice model pair');
      assert(await page.getByLabel('自定义术语词表', { exact: true }).isDisabled(), 'Unsupported prompting must be disabled');
      await page.getByLabel('识别后端', { exact: true }).selectOption('faster-whisper');
    }
    await page.getByLabel('转录质量', { exact: true }).selectOption('medium');
    assert(await page.getByLabel('转录质量', { exact: true }).inputValue() === 'medium', 'Larger Whisper model selection');
    await page.getByLabel('转录质量', { exact: true }).selectOption('small');
    await page.locator('.quality-controls summary').click();
    await page.getByRole('button', { name: '切换深色' }).click();
    await page.screenshot({ path: path.join(out, 'phase2-home-dark.png'), fullPage: true });
    await page.getByRole('button', { name: '切换浅色' }).click();
    await page.setViewportSize({ width: 390, height: 844 }); await noOverflow();
    await page.screenshot({ path: path.join(out, 'phase2-home-mobile.png'), fullPage: true });
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.getByRole('button', { name: '真值标注', exact: true }).click();
    await page.getByRole('heading', { name: '人工真值工作区' }).waitFor();
    await page.locator('.gt-slots section>button').nth(8).waitFor();
    assert(await page.locator('.gt-slots section>button').count() === 9, 'Nine planned slots');
    assert(await page.getByLabel('人工参考稿', { exact: true }).inputValue() === '', 'No invented reference');
    assert(await page.getByRole('button', { name: '确认这份稿为人工真值' }).isDisabled(), 'No implicit verification');
    assert(await page.getByRole('button', { name: '导出真值清单' }).isDisabled(), 'No unverified dataset');
    await page.getByRole('button', { name: '粤语 01', exact: false }).click();
    assert(await page.getByLabel('真值语言', { exact: true }).inputValue() === 'cantonese', 'Cantonese slot');
    await page.getByLabel('人工参考稿', { exact: true }).fill('浏览器临时输入，不保存。');
    page.once('dialog', dialog => dialog.dismiss());
    await page.getByRole('button', { name: '返回资料库', exact: true }).click();
    assert(await page.getByRole('heading', { name: '人工真值工作区' }).isVisible(), 'Unsaved guard');
    page.once('dialog', dialog => dialog.accept());
    await page.getByRole('button', { name: '普通话 01', exact: false }).click();
    await noOverflow(); await page.screenshot({ path: path.join(out, 'ground-truth-desktop.png'), fullPage: true });
    await page.getByRole('button', { name: '切换深色' }).click();
    await page.screenshot({ path: path.join(out, 'ground-truth-dark.png'), fullPage: true });
    await page.getByRole('button', { name: '切换浅色' }).click();
    await page.setViewportSize({ width: 390, height: 844 }); await noOverflow();
    await page.screenshot({ path: path.join(out, 'ground-truth-mobile.png'), fullPage: true });
    assert(!errors.length, errors.join('\n')); assert(!mutations.length, 'Read-only UI check unexpectedly mutated data');
    console.log(JSON.stringify({ status: 'passed', slots: 9, errors, mutations, homepage_character_removed: true, screenshots: out }));
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
