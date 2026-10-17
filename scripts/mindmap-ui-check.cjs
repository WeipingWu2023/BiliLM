// Browser-only synthetic fixture: no private library, server writes, model downloads or paid AI.
const { chromium } = require(process.env.BILILM_PLAYWRIGHT || 'playwright');
const fs = require('node:fs');
const path = require('node:path');
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = []; page.on('pageerror', e => errors.push(e.message));
  const assert = (condition, message) => { if (!condition) throw Error(message); };
  const rows = [
    { start: 0, end: 5, text: '这是界面测试示例。语音识别把音频变成文字。' },
    { start: 5, end: 10, text: '原始稿独立保留，修改与总结另存。' },
    { start: 10, end: 15, text: '遇到疑问，点击时间戳核对来源。' },
  ];
  const choice = { id: 'map-ui-run', provenance: 'local-asr:small', config: { model: 'small' }, created_at: '2026-10-17 00:00:00' };
  const video = { id: 'local:map-ui-fixture', title: '界面测试示例：从视频到学习笔记', creator: '合成界面夹具 · 非真实视频或评测真值', thumbnail: '', duration: 15, ready: 1, status: 'completed', url: 'local-file', segments: rows, readable: rows.map(r => r.text).join('\n\n'), revision: 0, provenance: choice.provenance, runs: [choice] };
  const run = { ...choice, raw: rows, proofread: rows, readable_segments: rows, readable: video.readable, proof_revision: 0, readable_revision: 0, mapped: 1, playback: null, audio: null, metrics: {}, corrections: [], change_log: [] };
  const summary = { id: 'summary-fixture', kind: 'summary', mode: 'local-extractive', title: video.title, run_id: run.id, citations: rows, cached: true, overview: '这是合成界面测试，用于验证交互，不是真实学习材料。', items: [{ text: rows[0].text, citations: [0] }], questions: [], notice: '本地原文提要，不是 AI。' };
  const map = { ...summary, id: 'map-fixture', kind: 'mindmap', branches: ['认识语音识别', '保留原始来源', '人工核对与编辑', '建立自己的资料库', '来源问答', '总结与复习'].map((text, i) => ({ text, citations: [i % 3], children: ['聆听音频并记录', '保留时间戳映射', '对照来源检查'].map((text, n) => ({ text, citations: [n] })) })) };
  let externalRequests = 0;
  try {
    await page.addInitScript(() => localStorage.setItem('bililm-ai-enabled', 'false'));
    await page.route('**/api/**', async route => {
      const request = route.request(), url = new URL(request.url()), endpoint = decodeURIComponent(url.pathname);
      let body;
      if (request.method() !== 'GET') { body = request.postDataJSON(); if (body?.external) externalRequests++; }
      let json;
      if (endpoint === '/api/videos') json = [video];
      else if (endpoint === '/api/jobs') json = [];
      else if (endpoint === '/api/health') json = { status: 'ok', ffmpeg: true, llm_configured: false };
      else if (endpoint === '/api/llm/settings') json = { configured: false, key_saved: false, auto_enabled: false, model: 'fixture' };
      else if (endpoint === '/api/videos/' + video.id) json = video;
      else if (endpoint === '/api/runs/' + run.id) json = run;
      else if (endpoint.endsWith('/learning/artifacts')) json = [map, summary];
      else if (endpoint.endsWith('/learning')) json = body?.kind === 'mindmap' ? map : summary;
      else if (endpoint === '/api/asr/models') json = [];
      else if (endpoint === '/api/asr/hardware') json = { hardware: { cpu_threads: 4, ram_gib: 16, available_ram_gib: 8, cuda_devices: 0 }, warnings: {} };
      else throw Error('Unhandled fixture request: ' + endpoint);
      await route.fulfill({ json });
    });
    await page.goto('http://127.0.0.1:3000');
    await page.locator('.video-card').first().click();
    await page.locator('.studio-result').filter({ hasText: '思维导图' }).first().click();
    const dialog = page.locator('.map-viewer'), canvas = page.locator('.map-canvas'), tree = page.locator('.map-tree');
    await page.locator('.map-links path').first().waitFor();
    await page.getByRole('button', { name: '全屏显示导图' }).click();
    const rect = await dialog.boundingBox();
    assert(Math.abs(rect.width - 1440) < 2 && Math.abs(rect.height - 1000) < 2, 'Fullscreen must cover viewport');
    const box = await canvas.boundingBox(), before = await tree.getAttribute('style');
    await page.mouse.move(box.x + box.width - 230, box.y + 35); await page.mouse.down();
    await page.mouse.move(box.x + box.width - 130, box.y + 105, { steps: 8 }); await page.mouse.up();
    assert(await tree.getAttribute('style') !== before, 'Canvas must pan after dragging');
    const prior = await page.getByRole('button', { name: '重置为百分之百' }).innerText();
    await page.mouse.wheel(0, -240);
    await page.waitForFunction(text => document.querySelector('.map-scale')?.textContent !== text, prior);
    await page.getByRole('button', { name: '适应窗口', exact: true }).click();
    await page.locator('.mindmap-leaf').first().click();
    await dialog.locator('.mindmap-evidence').waitFor();
    await page.getByRole('button', { name: '关闭导图引用' }).click();
    await canvas.focus(); const keyboardBefore = await tree.getAttribute('style');
    await page.keyboard.press('ArrowRight');
    assert(await tree.getAttribute('style') !== keyboardBefore, 'Keyboard pan must work');
    await page.keyboard.press('0');
    const folder = path.join(__dirname, '../docs/assets'); fs.mkdirSync(folder, { recursive: true });
    await page.screenshot({ path: path.join(folder, 'mindmap-desktop.png') });
    await page.keyboard.press('Escape');
    assert(await dialog.isVisible() && !await dialog.evaluate(el => el.classList.contains('map-viewer-full')), 'Escape must exit fullscreen first');
    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole('button', { name: '全屏显示导图' }).click();
    await page.getByRole('button', { name: '适应窗口', exact: true }).click();
    assert((await dialog.boundingBox()).width <= 391, 'Mobile dialog must fit viewport');
    await page.screenshot({ path: path.join(folder, 'mindmap-mobile.png') });
    await page.getByRole('button', { name: '关闭思维导图' }).click();
    assert(!await dialog.isVisible(), 'Close must dismiss dialog');
    assert(!errors.length && externalRequests === 0, 'No browser errors or external AI requests');
    console.log(JSON.stringify({ status: 'passed', fullscreen: true, pointer_pan: true, wheel_zoom: true, keyboard: true, citations: true, mobile: true, fixture_only: true, errors }));
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
