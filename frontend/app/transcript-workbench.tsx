'use client';
import { useEffect, useRef, useState } from 'react';
import { IconCopy, IconDownload, IconFileText, IconPlayerPlay, IconRefresh } from '@tabler/icons-react';
import { ASRSettings, QualityControls } from './quality-controls';
type Segment = { start: number; end: number; text: string; avg_logprob?: number };
type Correction = { id: string; segment_index: number; before_text: string; after_text: string; reason: string; state: string };
type Run = { id: string; provenance: string; raw: Segment[]; proofread: Segment[]; readable_segments: Segment[]; readable: string; proof_revision: number; readable_revision: number; mapped: number; playback: string | null; audio: string | null; config: Record<string, string | number>; metrics: Record<string, unknown>; corrections: Correction[]; change_log: unknown[] };
type Choice = { id: string; provenance: string; config: Record<string, string | number>; created_at: string };
const time = (s: number) => `${Math.floor(s / 60).toString().padStart(2, '0')}:${Math.floor(s % 60).toString().padStart(2, '0')}`;
const localDate = (value: string) => new Date(value.replace(' ', 'T') + 'Z').toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false });
async function request<T>(path: string, body?: unknown, method = 'POST'): Promise<T> {
  const response = await fetch(path, body === undefined ? undefined : { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const data = await response.json(); if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : '请求失败'); return data;
}

export function TranscriptWorkbench({ videoKey, config, onConfig, onRunId, onDirty, onError, onMessage, llmConfigured }: { videoKey: string; config: ASRSettings; onConfig: (value: ASRSettings) => void; onRunId: (rid: string) => void; onDirty: (dirty: boolean) => void; onError: (s: string) => void; onMessage: (s: string) => void; llmConfigured: boolean }) {
  const [choices, setChoices] = useState<Choice[]>([]); const [rid, setRid] = useState(''); const [run, setRun] = useState<Run | null>(null);
  const [view, setView] = useState<'raw' | 'proofread' | 'readable'>('raw'); const [query, setQuery] = useState('');
  const [editing, setEditing] = useState(false); const [draft, setDraft] = useState<string[]>([]); const [busy, setBusy] = useState(false);
  const [removeFiller, setRemoveFiller] = useState(false); const [compareId, setCompareId] = useState(''); const [differences, setDifferences] = useState<{ start: number; primary: string; secondary: string }[]>([]);
  const [job, setJob] = useState<{ id: string; progress: number; stage: string; status: string; error: string } | null>(null);
  const selected = useRef(''); const audio = useRef<HTMLAudioElement>(null); const limit = useRef<number | null>(null); const wantLatest = useRef(false); const latest = useRef('');
  const rows = run ? view === 'raw' ? run.raw : view === 'proofread' ? run.proofread : run.readable_segments : [];
  const dirty = editing && draft.some((t, i) => t !== rows[i]?.text);
  useEffect(() => {
    const jump = (event: Event) => {
      if (dirty && !confirm('放弃尚未保存的修改并回到原始稿吗？')) return;
      const start = (event as CustomEvent<number>).detail;
      setView('raw'); setEditing(false); setQuery('');
      requestAnimationFrame(() => document.getElementById(`segment-${start}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }));
    };
    window.addEventListener('bililm-transcript-jump', jump);
    return () => window.removeEventListener('bililm-transcript-jump', jump);
  }, [dirty]);
  useEffect(() => { onDirty(dirty); return () => onDirty(false); }, [dirty, onDirty]);
  useEffect(() => {
    let active = true;
    const poll = async () => {
      try {
        const [video, jobs] = await Promise.all([request<{ runs: Choice[] }>(`/api/videos/${encodeURIComponent(videoKey)}`), request<{ video_id: string; id: string; progress: number; stage: string; status: string; error: string }[]>('/api/jobs')]);
        if (!active) return; setChoices(video.runs);
        setJob(jobs.find(j => j.video_id === videoKey) ?? null);
        const newest = video.runs[0]?.id;
        if (newest && (!selected.current || (wantLatest.current && newest !== latest.current))) { setRid(newest); selected.current = newest; wantLatest.current = false; }
        latest.current = newest ?? '';
      } catch (e) { if (active) onError((e as Error).message); }
    };
    void poll(); const timer = setInterval(poll, 3000); return () => { active = false; clearInterval(timer); };
  }, [videoKey, onError]);
  useEffect(() => {
    let active = true; setRun(null); setEditing(false); setDifferences([]); setQuery('');
    if (rid) { selected.current = rid; onRunId(rid); request<Run>(`/api/runs/${rid}`).then(r => { if (active) setRun(r); }).catch(e => active && onError(e.message)); }
    return () => { active = false; };
  }, [rid, onError, onRunId]);
  const reload = async () => { setRun(await request<Run>(`/api/runs/${rid}`)); window.dispatchEvent(new Event('bililm-source-updated')); };
  const act = async (action: () => Promise<void>) => { setBusy(true); try { await action(); } catch (e) { onError((e as Error).message); } finally { setBusy(false); } };
  function play(start: number, end?: number) {
    if (!audio.current) { onError('历史版本没有保留音轨。请重新转录或提供原文件。'); return; }
    audio.current.currentTime = Math.max(0, start - 0.3); limit.current = end === undefined ? null : end + 0.3;
    void audio.current.play().catch(() => onError('音频暂时无法播放，请检查媒体文件。'));
  }
  function tab(next: typeof view) { if (dirty && !confirm('放弃尚未保存的逐段修改吗？')) return; setView(next); setEditing(false); }
  return <section className="transcript-panel panel version-workbench"><div className="panel-heading"><h2><IconFileText size={18} /> 转录笔记</h2><div className="toolbar"><button className="icon-button" aria-label="复制当前文稿" disabled={!run} onClick={() => void act(async () => { await navigator.clipboard.writeText(view === 'readable' && !editing ? run!.readable : (editing ? draft : rows.map(s => s.text)).join('\n')); onMessage('已复制。'); })}><IconCopy size={17} /></button><details className="export-menu"><summary aria-label="导出文稿"><IconDownload size={18} /></summary><div>{['txt', 'srt', 'md', 'json'].map(fmt => run && !dirty ? <a key={fmt} href={`/api/runs/${rid}/export?version=${view}&format=${fmt}`}>{fmt.toUpperCase()} · {view === 'raw' ? '原始字幕' : view === 'proofread' ? '校对稿' : '可读稿'}</a> : <span key={fmt}>先保存修改</span>)}</div></details></div></div>
    <div className="run-selector"><label>转录记录<select aria-label="选择转录版本" value={rid} disabled={dirty} onChange={e => setRid(e.target.value)}>{choices.map(c => <option key={c.id} value={c.id}>{c.config.model || c.provenance} · {localDate(c.created_at)} · {c.id.slice(0, 7)}</option>)}</select></label><button className="text-button" disabled={busy || dirty || job?.status === 'running' || job?.status === 'queued'} onClick={() => void act(async () => { const result = await request<{ job_id: string }>(`/api/videos/${encodeURIComponent(videoKey)}/retranscribe`, config); wantLatest.current = true; onMessage(`已创建重新转录任务 ${result.job_id.slice(0, 8)}。旧原稿保留。`); })}><IconRefresh size={15} /> 重新转录</button></div>
    <div className="workbench-settings"><QualityControls value={config} onChange={onConfig} /></div>
    {job && ['queued', 'running', 'failed'].includes(job.status) && <div className="version-job" role="status">{job.stage} · {job.progress}% {job.error}<button className="text-button" hidden={job.status !== 'failed'} onClick={() => void act(async () => { await request(`/api/jobs/${job.id}/retry`, {}); onMessage('失败任务已重新入队。'); })}>重试</button></div>}
    <div className="transcript-controls"><div className="tabs" role="tablist" aria-label="文稿版本">{([['raw', '原始稿'], ['proofread', '校对稿'], ['readable', '可读稿']] as const).map(([v, label]) => <button role="tab" key={v} aria-selected={view === v} className={view === v ? 'active' : ''} onClick={() => tab(v)}>{label}</button>)}</div>{view !== 'raw' && run && <button className="text-button" disabled={busy} onClick={() => editing ? void act(async () => { await request(`/api/runs/${rid}/${view}`, { texts: draft, revision: view === 'proofread' ? run.proof_revision : run.readable_revision }, 'PUT'); await reload(); setEditing(false); onMessage('逐段修改已保存，原始稿未改变。'); }) : (setDraft(rows.map(r => r.text)), setEditing(true))}>{editing ? '保存修改' : '编辑文稿'}</button>}</div>
    {run?.playback ? <div className="audio-review"><audio ref={audio} controls preload="metadata" src={`/api/runs/${rid}/audio`} onTimeUpdate={() => { if (limit.current !== null && audio.current && audio.current.currentTime >= limit.current) { audio.current.pause(); limit.current = null; } }} aria-label="原音频片段播放" /><a href={`/api/runs/${rid}/audio?original=true`}>下载原媒体</a></div> : <p className="audio-missing">历史版本未保留可播放音频；重新转录后可按时间戳重听。</p>}
    <label className="transcript-search search-box"><input aria-label="搜索文稿" value={query} onChange={e => setQuery(e.target.value)} placeholder="在当前版本搜索…" /></label>
    <div className="transcript-scroll">
      {!run ? <p className="muted">正在加载转录记录…</p> : <><details className="run-info"><summary>模型、执行信息与修改日志</summary><pre>{JSON.stringify({ config: run.config, execution: run.metrics, provenance: run.provenance, change_log: run.change_log }, null, 2)}</pre><a href={`/api/runs/${rid}/export?format=json`}>导出全部元数据与日志</a></details>
        {view === 'raw' && <p className="provenance-note">不可覆盖的原始输出。诊断低分不代表已证实错误，请重听核对。</p>}
        {view === 'proofread' && <><p className="provenance-note">文本校对建议未经听音验证。只有人工接受的修改进入校对稿。</p><button className="secondary" disabled={!llmConfigured || busy || dirty} onClick={() => void act(async () => { if (!confirm('将当前文字与词表发送给已配置的 LLM，生成待人工审核建议？')) return; await request(`/api/runs/${rid}/proofread`, {}); await reload(); })}>生成保守文本校对建议</button>{!llmConfigured && <p className="muted">未配置 LLM，仍可人工逐段校对。</p>}
          {run.corrections.filter(p => p.state === 'pending').map(p => <div className="correction" key={p.id}><strong>待人工复核 · {time(run.raw[p.segment_index].start)}</strong><del>{p.before_text}</del><ins>{p.after_text}</ins><p>{p.reason}</p><button onClick={() => play(run.raw[p.segment_index].start, run.raw[p.segment_index].end)}>重听</button><button disabled={busy || dirty} onClick={() => void act(async () => { await request(`/api/runs/${rid}/corrections/${p.id}/review`, { accept: true }); await reload(); })}>接受</button><button disabled={busy || dirty} onClick={() => void act(async () => { await request(`/api/runs/${rid}/corrections/${p.id}/review`, { accept: false }); await reload(); })}>保留原文</button></div>)}
        </>}
        {view === 'readable' && <div className="readable-actions"><label><input type="checkbox" checked={removeFiller} onChange={e => setRemoveFiller(e.target.checked)} /> 仅移除片段开头明确的“嗯/呃”停顿词</label><button className="text-button" disabled={busy || dirty} onClick={() => void act(async () => { if (!confirm('从当前校对稿重新生成可读稿？现有可读稿修改会记录并替换，原稿不变。')) return; await request(`/api/runs/${rid}/readable/format`, { revision: run.readable_revision, remove_filler: removeFiller }); await reload(); })}>从校对稿整理</button></div>}
        {view === 'readable' && !run.mapped && !editing ? <div className="readable"><p className="provenance-note">保留历史自由编辑稿；没有可证明的逐段映射，SRT 导出会明确拒绝。</p><p>{run.readable}</p></div> : rows.map((s, i) => (s.text.toLowerCase().includes(query.toLowerCase()) || editing) && <div className="segment" id={`segment-${s.start}`} key={i}><button className="timestamp" onClick={() => play(s.start, s.end)} title="重听此片段">{time(s.start)}{run.playback && <IconPlayerPlay size={10} />}</button><div>{editing ? <textarea className="segment-editor" aria-label={`编辑片段 ${i + 1}`} value={draft[i] ?? ''} onChange={e => setDraft(d => d.map((t, n) => n === i ? e.target.value : t))} /> : view === 'proofread' && s.text !== run.raw[i].text ? <div className="corrected-text"><del>{run.raw[i].text}</del><ins>{s.text}</ins></div> : <p>{query ? s.text.split(query).map((t, n) => <span key={n}>{n > 0 && <mark>{query}</mark>}{t}</span>) : s.text}</p>}{view === 'raw' && s.avg_logprob !== undefined && s.avg_logprob < -1 && <small className="uncertain-tag">诊断：低平均 log probability，建议重听</small>}</div></div>)}
        {editing && <button className="text-button" onClick={() => setEditing(false)}>放弃修改</button>}
        <details className="comparison-controls"><summary>对照另一个已有 ASR 记录（不会运行第二模型）</summary><select value={compareId} onChange={e => setCompareId(e.target.value)}><option value="">选择已有记录</option>{choices.filter(c => c.id !== rid).map(c => <option value={c.id} key={c.id}>{c.provenance} · {c.id.slice(0, 8)}</option>)}</select><button className="text-button" disabled={!compareId || busy} onClick={() => void act(async () => { const result = await request<{ differences: typeof differences }>(`/api/runs/${rid}/compare/${compareId}`); setDifferences(result.differences); })}>定位分歧</button>{differences.map((d, i) => <div className="correction" key={i}><button onClick={() => play(d.start)}>{time(d.start)} · 重听</button><p>{d.primary}</p><p>{d.secondary}</p><small>只是分歧候选，不能据此判定正确答案。</small></div>)}</details>
      </>}
    </div>
  </section>;
}
