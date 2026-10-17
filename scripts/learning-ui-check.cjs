const { chromium } = require(process.env.BILILM_PLAYWRIGHT || 'playwright');
const fs = require('node:fs');
const path = require('node:path');
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = []; page.on('pageerror', e => errors.push(e.message));
  const out = path.join(__dirname, '../docs/screenshots');
  const assert = (test, msg) => { if (!test) throw Error(msg); };
  try {
    await page.addInitScript(() => localStorage.setItem('bililm-ai-enabled', 'false'));
    await page.goto('http://127.0.0.1:3000');
    await page.locator('.video-card').filter({ hasText: '爱奇艺这是要凉透了' }).first().click();
    await page.getByRole('heading', { name: 'Sources · 来源' }).waitFor();
    await page.locator('.learning-summary li').first().waitFor();
    assert(await page.getByRole('heading', { name: 'Studio · 创作空间' }).isVisible(), 'Studio missing');
    assert(await page.locator('.learning-summary').innerText().then(t => t.includes('不是 AI')), 'Offline mode must be honest');
    await page.getByRole('button', { name: 'DeepSeek 设置', exact: true }).click();
    assert(await page.getByLabel('DeepSeek API Key', { exact: true }).getAttribute('type') === 'password', 'Secret field must be masked');
    await page.getByRole('button', { name: '收起设置' }).click(); await page.screenshot({ path: path.join(out, 'learning-desktop.png'), fullPage: true });
    await page.getByRole('textbox', { name: '向来源提问' }).fill('爱奇艺');
    await page.getByRole('button', { name: '发送来源问题' }).click();
    await page.locator('.learning-turn').waitFor();
    await page.locator('.learning-turn .learning-citations button').first().click();
    await page.getByRole('button', { name: '在文稿中核对 / 重听' }).click();
    await page.getByRole('heading', { name: '转录笔记' }).waitFor();
    await page.getByRole('tab', { name: '可读稿', exact: true }).click();
    const download = page.waitForEvent('download');
    await page.getByLabel('导出文稿').click();
    await page.locator('.learning-transcript .export-menu').locator('a[href*="format=md"]').click();
    const file = await download; const content = fs.readFileSync(await file.path(), 'utf8');
    assert(!content.includes('原始时间轴') && !/\[\d\d:\d\d:\d\d\]/.test(content), 'Readable export contains timeline');
    const exportDir = path.join(__dirname, '../data/exports'); fs.mkdirSync(exportDir, { recursive: true });
    fs.writeFileSync(path.join(exportDir, 'bililm-readable.md'), content);
    await page.getByRole('tab', { name: '来源问答', exact: true }).click();
    await page.locator('.studio-tool').filter({ hasText: '思维导图' }).click();
    await page.locator('.studio-result').filter({hasText:'思维导图'}).first().waitFor();
    assert(await page.locator('.studio-companion').count() === 0, 'Studio portrait must be removed');
    await page.reload();
    await page.locator('.video-card').filter({hasText:'爱奇艺这是要凉透了'}).first().click();
    await page.locator('.studio-result').filter({hasText:'思维导图'}).first().click();
    await page.getByRole('dialog').waitFor();
    await page.locator('.mindmap-leaf').first().click();
    assert(await page.getByRole('dialog').locator('.mindmap-evidence').isVisible(), 'Map nodes need source evidence');
    await page.getByRole('button', { name: '放大导图' }).click();
    await page.screenshot({ path: path.join(out, 'learning-mindmap.png'), fullPage: true });
    await page.getByRole('button', { name: '关闭思维导图' }).click();
    await page.locator('.studio-tool').filter({hasText:'来源总结'}).click();
    await page.locator('.studio-result').filter({hasText:'来源总结'}).first().click();
    await page.locator('.summary-result-dialog').waitFor();
    await page.getByRole('button',{name:'关闭来源总结'}).click();
    await page.screenshot({ path: path.join(out, 'learning-conversation.png'), fullPage: true });
    await page.getByRole('button', { name: '切换深色' }).click();
    await page.screenshot({ path: path.join(out, 'learning-dark.png'), fullPage: true });
    await page.getByRole('button', { name: '切换浅色' }).click();
    for (const width of [1024, 390]) {
      await page.setViewportSize({ width, height: 844 });
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `Overflow ${width}`);
      await page.screenshot({ path: path.join(out, `learning-${width}.png`), fullPage: true });
    }
    // Simulate DeepSeek in the browser only. No fake key or AI output reaches the server.
    const ai = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    ai.on('pageerror', e => errors.push(e.message));
    let saved = false, summaryCalls = 0;
    await ai.route('**/api/llm/settings', async route => {
      if (route.request().method() === 'PUT') {
        assert(route.request().postDataJSON().api_key === 'ui-fixture-not-real', 'Unexpected key'); saved = true;
      }
      await route.fulfill({ json: { configured: saved, key_saved: saved, model: 'deepseek-flash', auto_enabled: saved } });
    });
    const cite = { id: 0, start: 0, end: 1, text: '界面测试夹具，非真实来源或真实 AI 结果。' };
    await ai.route('**/api/videos/*/learning', async route => {
      const body = route.request().postDataJSON();
      if (!body.external) return route.continue();
      const payload = { mode: 'llm', kind: body.kind, cached: false, run_id: body.run_id, citations: [cite], notice: '模拟 AI，仅用于界面验收。' };
      if (body.kind === 'summary') { summaryCalls++; Object.assign(payload, { overview: '模拟来源总结。', items: [{ text: '测试要点', citations: [0] }], questions: ['模拟追问？'] }); }
      else Object.assign(payload, { branches: [{ text: '测试主题', citations: [0], children: [{ text: '测试节点', citations: [0] }] }] });
      await route.fulfill({ json: payload });
    });
    await ai.goto('http://127.0.0.1:3000');
    await ai.locator('.video-card').filter({ hasText: '爱奇艺这是要凉透了' }).first().click();
    await ai.getByRole('button', { name: 'DeepSeek 设置', exact: true }).click();
    await ai.getByLabel('DeepSeek API Key', { exact: true }).fill('ui-fixture-not-real');
    await ai.getByRole('button', { name: '保存并启用 DeepSeek' }).click();
    await ai.getByText('模拟来源总结。', { exact: true }).waitFor();
    assert(saved && summaryCalls === 1, 'Saving provider should auto-generate exactly one summary');
    assert(await ai.getByLabel('DeepSeek API Key', { exact: true }).count() === 0, 'Secret editor should close after save');
    await ai.locator('.studio-tool').filter({ hasText: '思维导图' }).click();
    await ai.locator('.studio-result').filter({hasText:'思维导图'}).first().click();
    await ai.getByRole('button', { name: '测试节点', exact: true }).waitFor();
    await ai.getByRole('button', { name: '关闭思维导图' }).click();
    await ai.close();
    assert(!errors.length, errors.join('\n'));
    console.log(JSON.stringify({ status: 'passed', errors, readable_export_without_timeline: true, simulated_deepseek_ui: true, mode: 'local extractive + browser-only AI simulation; no paid AI request', screenshots: out }));
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
