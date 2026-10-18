'use client';
import { useEffect, useState } from 'react';

export type ASRSettings = { backend: 'faster-whisper' | 'sensevoice'; model: string; language: string; device: string; beam_size: number; topic: string; glossary: string; vad_filter: boolean; multilingual: boolean; speech_pad_ms: number; min_silence_duration_ms: number; vad_threshold: number; allow_model_download: boolean; ai_proofread: boolean; proofread_search: boolean };
export const defaultSettings: ASRSettings = { backend: 'faster-whisper', model: 'small', language: 'auto', device: 'auto', beam_size: 5, topic: '', glossary: '', vad_filter: true, multilingual: false, speech_pad_ms: 400, min_silence_duration_ms: 2000, vad_threshold: 0.5, allow_model_download: false, ai_proofread: false, proofread_search: false };
type Hardware = { cpu_threads: number; ram_gib: number | null; available_ram_gib: number | null; cuda_devices: number; available_vram_gib: number | null };
type ModelState = { model: string; usable: boolean; cached: boolean; runtime_ready: boolean; size: string; state: string; error: string | null; note: string };

export function QualityControls({ value, onChange }: { value: ASRSettings; onChange: (value: ASRSettings) => void }) {
  const [info, setInfo] = useState<{ hardware: Hardware; warnings: Record<string, string[]> } | null>(null);
  const [models, setModels] = useState<ModelState[]>([]); const [installError, setInstallError] = useState(''); const [installing, setInstalling] = useState(false);
  const [open, setOpen] = useState(false);
  useEffect(() => { let active = true; const refresh = () => fetch('/api/asr/models').then(r => r.ok ? r.json() : []).then(rows => { if (active) setModels(rows); }).catch(() => {}); void refresh(); const timer = setInterval(refresh,4000); return () => { active = false; clearInterval(timer); }; }, []);
  useEffect(() => { fetch('/api/asr/hardware').then(r => r.ok ? r.json() : null).then(setInfo).catch(() => {}); }, []);
  const set = (patch: Partial<ASRSettings>) => onChange({ ...value, ...patch });
  const sensevoice = value.backend === 'sensevoice';
  const selected = models.find(m => m.model === value.model);
  useEffect(() => { if (selected && !selected.usable) setOpen(true); }, [value.model, selected?.usable]);
  const sensevoiceRuntime = models.find(m => m.model === 'SenseVoiceSmall')?.runtime_ready;
  async function install() {
    setInstalling(true); setInstallError('');
    try { const response = await fetch(`/api/asr/models/${value.model}/install`, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({authorized:true}) }); const result = await response.json(); if (!response.ok) throw Error(result.detail || '下载启动失败'); setModels(await fetch('/api/asr/models').then(r => r.json())); }
    catch (e) { setInstallError((e as Error).message); }
    finally { setInstalling(false); }
  }
  const profile = ({ small: 'fast', medium: 'balanced', 'large-v3': 'accuracy', turbo: 'turbo' } as Record<string, string>)[value.model];
  return <details className="quality-controls" open={open} onToggle={event => setOpen(event.currentTarget.open)}><summary>转录质量与术语 <span>{value.model} · {value.language === 'auto' ? '自动语言' : value.language}</span></summary><div className="quality-grid">
    <label>识别后端<select aria-label="识别后端" value={value.backend} onChange={e => set({ backend: e.target.value as ASRSettings['backend'], model: e.target.value === 'sensevoice' ? 'SenseVoiceSmall' : 'small', allow_model_download: false })}><option value="faster-whisper">Whisper · 支持 medium / large-v3 / turbo</option><option value="sensevoice" disabled={sensevoiceRuntime === false}>SenseVoice · {sensevoiceRuntime === false ? '需额外安装运行依赖' : '实验后端'}</option></select></label>
    <label>质量配置<select aria-label="转录质量" disabled={sensevoice} value={value.model} onChange={e => set({ model: e.target.value })}>{sensevoice && <option value="SenseVoiceSmall">SenseVoiceSmall · 尚未实测</option>}<option value="small">Fast · small（原 MVP）</option><option value="medium">Balanced · medium</option><option value="large-v3">High Accuracy · large-v3（名称不代表实测结论）</option><option value="turbo">turbo · 对照候选</option><option value="tiny">tiny · 快速检查</option><option value="base">base</option></select></label>
    <label>语言<select aria-label="转录语言" value={value.language} onChange={e => set({ language: e.target.value, multilingual: false })}><option value="auto">自动识别 / 中英混合</option><option value="zh">普通话为主 · zh</option><option value="yue">粤语 · yue（需模型支持）</option><option value="en">英语 · en</option></select></label>
    <label>执行设备<select value={value.device} onChange={e => set({ device: e.target.value })}><option value="auto">自动（不改变模型）</option><option value="cpu">{sensevoice ? 'CPU float32' : 'CPU int8'}</option><option value="cuda">{sensevoice ? 'CUDA GPU（PyTorch）' : 'CUDA GPU float16'}</option></select></label>
    <label>beam size<select disabled={sensevoice} value={value.beam_size} onChange={e => set({ beam_size: Number(e.target.value) })}><option value={5}>5 · 保持默认</option><option value={8}>8 · 待对照测量</option></select></label>
    <div className="model-preparation quality-wide" role="status"><strong>{value.model} · {selected?.usable ? '已安装，可使用' : selected?.state === 'downloading' ? '正在下载模型文件…' : selected ? '尚未准备完成' : '正在检查本地模型…'}</strong><p>{selected?.size}。{selected?.runtime_ready === false ? selected.note : '模型选择与设备独立；medium / large-v3 / turbo 可以用 CPU 运行，处理速度与内存需求需实测。'}</p>{selected && !selected.usable && selected.runtime_ready && <button type="button" className="secondary" disabled={installing || selected.state === 'downloading'} onClick={() => void install()}>{selected.state === 'downloading' ? '下载中，完成后可使用' : `下载所选模型（${selected.size}）`}</button>}{(installError || selected?.error) && <p className="error-text">{installError || selected?.error}</p>}<small>点击下载只准备模型，不会自动开始转录。下载中断可重试并复用缓存。SenseVoiceSmall 是另一种模型，并不等同于更高等级的 Whisper。</small></div>
    <div className="quality-wide ai-pipeline-options"><label className="quality-check"><input type="checkbox" checked={!!value.ai_proofread} onChange={e => set({ ai_proofread: e.target.checked, proofread_search: e.target.checked ? value.proofread_search : false })} /> 转录后自动 AI 校对，再生成可读稿</label><label className="quality-check"><input type="checkbox" disabled={!value.ai_proofread} checked={!!value.proofread_search} onChange={e => set({ proofread_search: e.target.checked })} /> 同时联网核对专名拼写（最多 3 次检索）</label><small>需先在来源问答配置 DeepSeek。启用会向服务商发送文稿、标题与词表，可能产生费用；仅保守修正独立校对稿，不改原稿。失败仍保存 ASR 输出。粤语的拼写建议留待人工复核。</small></div>
    <label className="quality-wide">视频主题<input disabled={sensevoice} maxLength={300} placeholder="例如：计算机网络、嵌入式系统" value={value.topic} onChange={e => set({ topic: e.target.value })} /></label>
    <label className="quality-wide">术语词表<textarea disabled={sensevoice} aria-label="自定义术语词表" maxLength={2000} placeholder="TCP/IP, Transformer, FFmpeg, ESP32-S3, Python, API, GPU, Bilibili" value={value.glossary} onChange={e => set({ glossary: e.target.value })} /></label>
    <label className="quality-check"><input type="checkbox" disabled={sensevoice} checked={value.vad_filter} onChange={e => set({ vad_filter: e.target.checked })} /> VAD（保留当前默认）</label>
    <label className="quality-check"><input type="checkbox" checked={value.multilingual} disabled={sensevoice || value.language !== 'auto'} onChange={e => set({ multilingual: e.target.checked })} /> 逐段多语言检测</label>
    <label>语音边缘保留 ms<input disabled={sensevoice} type="number" min={0} max={2000} value={value.speech_pad_ms} onChange={e => set({ speech_pad_ms: Number(e.target.value) })} /></label>
    <label>静音分隔 ms<input disabled={sensevoice} type="number" min={100} max={5000} value={value.min_silence_duration_ms} onChange={e => set({ min_silence_duration_ms: Number(e.target.value) })} /></label>
    <label className="quality-check quality-wide"><input type="checkbox" disabled={sensevoice} checked={value.allow_model_download} onChange={e => set({ allow_model_download: e.target.checked })} /> 明确允许首次下载所选 Whisper 大模型（可能占用数 GB）</label>
    {sensevoice && <p className="quality-note quality-wide">SenseVoice 转录只读取本地缓存；模型可由上方显式下载，运行依赖通过 install-models.ps1 -IncludeSenseVoice 准备。此适配器暂不使用 beam、术语提示或 VAD；时间戳仅表示最多 30 秒输入窗，不能当作逐词对齐。{selected?.usable ? '本机模型与依赖已准备；准确率仍需真值评测。' : '请先完成模型和运行依赖安装。'}默认仍为 Whisper small。</p>}
    {info && <p className="quality-note quality-wide">{info.hardware.cpu_threads} 逻辑核心 · RAM {info.hardware.ram_gib?.toFixed(1) ?? '未知'} GiB · 可用 {info.hardware.available_ram_gib?.toFixed(1) ?? '未知'} GiB · CUDA {info.hardware.cuda_devices} · VRAM {info.hardware.available_vram_gib?.toFixed(1) ?? '未知'} GiB<br />{info.warnings[profile]?.join(' ')}{value.device === 'cuda' && !info.hardware.cuda_devices && '当前主机无 CUDA；GPU 任务需要兼容 worker。'}</p>}
    <p className="quality-note quality-wide">词表只作为识别提示，不自动替换原词。beam=8、VAD 参数和更大模型是否更准，都需要相同音频真值对照。small 保留为兼容默认，尚未依据准确率评测选新默认。</p>
  </div></details>;
}
