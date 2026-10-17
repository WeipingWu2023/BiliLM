const { chromium } = require(process.env.BILILM_PLAYWRIGHT || 'playwright');
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  let installed = false, consent = false;
  const errors = []; page.on('pageerror', e => errors.push(e.message));
  try {
    await page.addInitScript(() => localStorage.setItem('bililm-ai-enabled', 'false'));
    // Exercise download UX without downloading anything in this test.
    await page.route('**/api/asr/models', route => route.fulfill({ json: ['tiny','small','medium','large-v3','SenseVoiceSmall'].map(model => ({ model, cached: model === 'small' || (model === 'medium' && installed), usable: model === 'small' || (model === 'medium' && installed), runtime_ready: model !== 'SenseVoiceSmall', size: '约 1.5 GB', state: model === 'small' || (model === 'medium' && installed) ? 'ready' : 'not_installed', error: null })) }));
    await page.route('**/api/asr/models/medium/install', route => { consent = route.request().postDataJSON().authorized === true; installed = true; return route.fulfill({ json: { state: 'ready', model: 'medium' } }); });
    await page.goto('http://127.0.0.1:3000');
    await page.locator('.quality-controls summary').click();
    await page.getByLabel('转录质量', { exact: true }).selectOption('medium');
    await page.getByRole('button', { name: '下载所选模型（约 1.5 GB）' }).click();
    await page.getByText('medium · 已安装，可使用', { exact: true }).waitFor();
    if (!consent || errors.length) throw Error('Model preparation UX failed: ' + errors.join('\n'));
    if (!(await page.getByLabel('识别后端', { exact: true }).locator('option[value=sensevoice]').evaluate(option => option.disabled))) throw Error('Missing SenseVoice dependencies must be visible');
    console.log('Model UI passed: larger model selection, explicit download action, ready state, SenseVoice dependency status; download was mocked.');
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
