const { chromium } = require(process.env.BILILM_PLAYWRIGHT || 'playwright');
const path = require('node:path');
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = []; page.on('pageerror', e => errors.push(e.message));
  try {
    await page.addInitScript(() => localStorage.setItem('bililm-ai-enabled', 'false'));
    await page.goto('http://127.0.0.1:3000');
    await page.locator('.video-card').filter({ hasText: 'authorized-speech.wav' }).first().click();
    await page.getByRole('tab', { name: '文稿核对', exact: true }).click(); await page.getByRole('tab', { name: '原始稿', exact: true }).waitFor();
    await page.locator('audio').waitFor();
    const rid = await page.getByLabel('选择转录版本').inputValue();
    const original = await page.request.get(`http://127.0.0.1:3000/api/runs/${rid}`).then(r => r.json());
    await page.locator('.timestamp').first().click();
    await page.waitForFunction(() => document.querySelector('audio')?.currentTime > 0);
    await page.locator('audio').evaluate(audio => audio.pause());
    await page.getByRole('tab', { name: '校对稿', exact: true }).click();
    await page.getByRole('button', { name: '编辑文稿', exact: true }).click();
    const editor = page.getByRole('textbox', { name: '编辑片段 1', exact: true });
    const text = await editor.inputValue();
    await editor.fill(text + ' [人工复核测试]');
    await page.getByRole('button', { name: '保存修改' }).click();
    await page.locator('.corrected-text ins').waitFor();
    const edited = await page.request.get(`http://127.0.0.1:3000/api/runs/${rid}`).then(r => r.json());
    if (JSON.stringify(edited.raw) !== JSON.stringify(original.raw)) throw Error('Raw changed after manual proofreading');
    if (!edited.change_log.length) throw Error('Manual change audit missing');
    await page.getByRole('button', { name: '编辑文稿', exact: true }).click();
    await editor.fill(text); await page.getByRole('button', { name: '保存修改' }).click();
    await page.getByRole('button', { name: '编辑文稿', exact: true }).waitFor();
    await page.getByRole('tab', { name: '原始稿', exact: true }).click();
    await page.screenshot({ path: path.join(__dirname, '../docs/screenshots/accuracy-audio-desktop.png'), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) throw Error('Accuracy workspace mobile overflow');
    await page.screenshot({ path: path.join(__dirname, '../docs/screenshots/accuracy-audio-mobile.png'), fullPage: true });
    if (errors.length) throw Error(errors.join('\n'));
    console.log('Accuracy UI passed: timestamp audio playback, manual proofread diff/audit, raw unchanged, restore, mobile layout.');
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
