'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { defaultSettings, QualityControls } from './quality-controls';
import { TranscriptWorkbench } from './transcript-workbench';
import { LearningWorkspace } from './learning-workspace';
import { GroundTruthWorkspace } from './ground-truth-workspace';
import { IconArrowLeft, IconArrowRight, IconBook2, IconCheck, IconChevronRight, IconCopy, IconDownload, IconFileText, IconFolder, IconLink, IconMessageCircle, IconMoon, IconPlus, IconSearch, IconSend, IconShieldLock, IconSun, IconUpload, IconVideo } from '@tabler/icons-react';

type Segment = { start: number; end: number; text: string };
type Video = { id: string; title: string; creator: string; thumbnail: string; duration: number; provenance: string; ready?: number; status?: string; url: string; segments: Segment[]; readable: string; revision: number };
type Job = { id: string; video_id: string; status: string; progress: number; stage: string; error: string | null; attempts: number };
type Chat = { question: string; answer: string; citations: Segment[]; mode: string };
const time = (s: number) => `${Math.floor(s / 60).toString().padStart(2, '0')}:${Math.floor(s % 60).toString().padStart(2, '0')}`;
const keyPath = (key: string) => `/api/videos/${encodeURIComponent(key)}`;
async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === 'string' ? body.detail : `请求失败 (${response.status})`);
  }
  return response.json();
}
const json = (body: unknown, method = 'POST') => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

export default function Page() {
  const [library, setLibrary] = useState<Video[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [groundTruthOpen, setGroundTruthOpen] = useState(false);
  const [video, setVideo] = useState<Video | null>(null);
  const [source, setSource] = useState('');
  const [model, setModel] = useState('small');
  const [settings, setSettings] = useState(defaultSettings);
  const [activeRunId, setActiveRunId] = useState('');
  const [versionDirty, setVersionDirty] = useState(false);
  const [view, setView] = useState<'original' | 'readable'>('original');
  const [draft, setDraft] = useState('');
  const [editing, setEditing] = useState(false);
  const [query, setQuery] = useState('');
  const [libraryQuery, setLibraryQuery] = useState('');
  const [question, setQuestion] = useState('');
  const [chats, setChats] = useState<Chat[]>([]);
  const [external, setExternal] = useState(false);
  const [health, setHealth] = useState<{ ffmpeg: boolean; llm_configured: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [loaded, setLoaded] = useState(false);
  const [dark, setDark] = useState(false);
  const upload = useRef<HTMLInputElement>(null);
  const activeSelection = useRef(selected);
  activeSelection.current = selected;
  const dirty = (!!video && draft !== video.readable) || versionDirty;
  const selectedJob = jobs.find(j => j.video_id === selected);
  const pending = jobs.filter(j => j.status === 'queued' || j.status === 'running');
  const selectedReady = library.find(v => v.id === selected)?.ready;
  const selectedTitle = library.find(v => v.id === selected)?.title;

  const refresh = useCallback(async () => {
    try {
      const [videos, tasks] = await Promise.all([api<Video[]>('/api/videos'), api<Job[]>('/api/jobs')]);
      setLibrary(videos); setJobs(tasks); setLoaded(true);
    } catch (e) { setError((e as Error).message + '。请确认本地服务已启动。'); }
  }, []);
  useEffect(() => { void refresh(); const timer = setInterval(refresh, 2500); void api<typeof health>('/api/health').then(setHealth).catch(() => {}); return () => clearInterval(timer); }, [refresh]);
  useEffect(() => { const changed = () => { void api<typeof health>('/api/health').then(setHealth).catch(() => {}); }; window.addEventListener('bililm-provider-changed', changed); return () => window.removeEventListener('bililm-provider-changed', changed); }, []);
  useEffect(() => {
    let active = true;
    setVideo(null); setActiveRunId(''); setEditing(false); setQuery(''); setChats([]);
    if (selected) api<Video>(keyPath(selected)).then(v => { if (active) { setVideo(v); setDraft(v.readable); } }).catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [selected, selectedReady, selectedTitle]);
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => { if (dirty) e.preventDefault(); };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);
  function navigate(key: string | null) {
    if (dirty && !window.confirm('稿件尚未保存。要放弃这些修改吗？')) return;
    setGroundTruthOpen(false); setSelected(key); setNotice(''); setError('');
  }
  function openGroundTruth() {
    if (groundTruthOpen) return;
    if (dirty && !window.confirm('稿件尚未保存。要放弃这些修改吗？')) return;
    setSelected(null); setGroundTruthOpen(true); setNotice(''); setError('');
  }
  async function importSource(file?: File) {
    if (dirty && !window.confirm('导入会离开当前稿件。要放弃未保存的修改吗？')) return;
    setBusy(true); setError(''); setNotice('');
    try {
      let result: { video_id: string; cached: boolean };
      if (file) {
        const form = new FormData(); form.append('file', file); form.append('model', model); form.append('config', JSON.stringify({ ...settings, model }));
        result = await api('/api/uploads', { method: 'POST', body: form });
      } else result = await api('/api/imports', json({ source, ...settings, model }));
      setGroundTruthOpen(false); setSelected(result.video_id); setSource(''); await refresh();
      setNotice(result.cached ? '已打开本地缓存。要使用新选择的模型，请到“文稿核对”点击“重新转录”。' : '已加入本地队列。你可以离开此页面，任务会继续运行。');
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); if (upload.current) upload.current.value = ''; }
  }
  async function save() {
    if (!video) return;
    setBusy(true); setError('');
    try {
      const result = await api<{ revision: number }>(keyPath(video.id) + '/readable', json({ text: draft, revision: video.revision }, 'PUT'));
      setVideo({ ...video, readable: draft, revision: result.revision }); setEditing(false); setNotice('可读稿已保存，原始时间轴保留。');
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  async function copy() {
    try { await navigator.clipboard.writeText(view === 'readable' ? draft : video!.segments.map(s => `[${time(s.start)}] ${s.text}`).join('\n')); setNotice('已复制到剪贴板。'); }
    catch { setError('剪贴板不可用，请选中文字手动复制。'); }
  }
  async function ask() {
    if (!video || !question.trim() || asking) return;
    const current = question; const currentKey = video.id; setAsking(true); setError('');
    try {
      const result = await api<Omit<Chat, 'question'>>(keyPath(currentKey) + '/ask', json({ question: current, external, run_id: activeRunId || null }));
      if (activeSelection.current !== currentKey) return;
      setChats(c => [...c, { ...result, question: current }]); setQuestion('');
    } catch (e) { setError((e as Error).message); }
    finally { setAsking(false); }
  }
  function jump(start: number) { window.dispatchEvent(new CustomEvent('bililm-transcript-jump', { detail: start })); setView('original'); setQuery(''); }
  const ready = !!video?.segments.length;
  const filtered = video?.segments.filter(s => s.text.toLowerCase().includes(query.toLowerCase())) || [];
  const chapters = video?.segments.filter((s, i, all) => i === 0 || Math.floor(s.start / 300) > Math.floor(all[i - 1].start / 300)) || [];

  return <div className={`app ${dark ? 'dark-theme' : ''}`}>
    <header className="topbar">
      <button className="brand" onClick={() => navigate(null)} aria-label="返回 BiliLM 首页"><span className="brand-mark"><IconBook2 size={23} /></span><span>Bili<span className="brand-lm">LM</span></span></button>
      <span className="header-divider" /><span className="app-label">视频学习笔记</span>
      <div className="top-actions"><button className="text-button" onClick={openGroundTruth}><IconFileText size={16} /> 真值标注</button><span className="local-label"><IconShieldLock size={16} /> 本地存储</span><button className="icon-button" aria-label={dark ? '切换浅色' : '切换深色'} onClick={() => setDark(!dark)}>{dark ? <IconSun size={19} /> : <IconMoon size={19} />}</button></div>
    </header>
    {error && <div className="banner error" role="alert"><span>{error}</span><button onClick={() => setError('')}>关闭</button></div>}
    {notice && <div className="banner notice" role="status"><IconCheck size={17} /><span>{notice}</span><button onClick={() => setNotice('')}>关闭</button></div>}
    <input ref={upload} type="file" hidden accept=".mp3,.mp4,.wav,.m4a,.flac,.ogg,.webm,.mkv,.aac" onChange={e => e.target.files?.[0] && void importSource(e.target.files[0])} />
    {groundTruthOpen ? <GroundTruthWorkspace onExit={() => navigate(null)} onDirty={setVersionDirty} onError={setError} onMessage={setNotice} /> : !selected ? <div className="home-layout">
      <nav className="home-nav" aria-label="主导航"><button className="nav-active"><IconFolder size={20} /> 我的资料库 <span>{library.length}</span></button><button onClick={() => document.getElementById('source-input')?.focus()}><IconPlus size={20} /> 导入新视频</button><div className="nav-bottom"><IconShieldLock size={19} /><p>你的内容，留在本地。<small>转录与编辑无需云端账号</small></p></div></nav>
      <main className="home-main">
        <section className="import-section"><div className="hero-top"><div className="hero-copy"><div className="eyebrow">从观看，到理解</div><h1>让每一段视频，<br />成为你的学习笔记。</h1><p className="intro">导入 B 站视频，保留原声里的每一句话。<br className="mobile-hide" />用时间轴阅读、整理，在自己的节奏里探索。</p></div><figure className="hero-character"><img src="/images/miku-bust-v3.png" alt="初音未来微笑着抱书的透明半身插画" width={1254} height={1254} fetchPriority="high" /><figcaption>初音未来 · 学习伙伴</figcaption></figure></div>
          <form className="import-box" onSubmit={e => { e.preventDefault(); void importSource(); }}><IconLink className="input-symbol" size={21} /><input id="source-input" aria-label="B站视频链接或 BV 号" placeholder="粘贴 B 站链接或 BV 号…" required value={source} onChange={e => setSource(e.target.value)} /><button className="primary" disabled={busy || !source.trim()}>{busy ? '正在导入…' : '导入视频'}<IconArrowRight size={18} /></button></form>
          <div className="import-options"><button className="text-button" disabled={busy} onClick={() => upload.current?.click()}><IconUpload size={16} /> 导入已授权的本地文件</button><span className="option-divider" /><label>识别模型 <select aria-label="识别模型" value={model} onChange={e => { setModel(e.target.value); setSettings({ ...settings, backend: e.target.value === 'SenseVoiceSmall' ? 'sensevoice' : 'faster-whisper', allow_model_download: false }); }}>{['tiny','base','small','medium','large-v3','turbo','SenseVoiceSmall'].map(m => <option key={m} value={m}>{m === 'SenseVoiceSmall' ? 'SenseVoice · 需先检查依赖' : m}</option>)}</select></label></div>
          <div className="import-hint">优先读取可访问字幕；无字幕时使用本地语音识别。仅导入你有权使用的内容。</div>
          <QualityControls value={{ ...settings, model }} onChange={next => { setSettings(next); setModel(next.model); }} />
          {health && !health.ffmpeg && <p className="error-text">未检测到 FFmpeg。本地转录前请完成安装。</p>}
        </section>
        {pending.length > 0 && <section className="queue-strip" aria-label="处理中任务">{pending.map(j => <button key={j.id} onClick={() => navigate(j.video_id)}><IconVideo size={19} /><span>{library.find(v => v.id === j.video_id)?.title}<small>{j.stage}</small></span><progress max={100} value={j.progress} /><b>{j.progress}%</b><IconChevronRight size={18} /></button>)}</section>}
        <section className="library-section"><div className="section-heading"><h2>我的资料库 <span>{library.length}</span></h2><label className="search-box"><IconSearch size={17} /><input aria-label="搜索资料库" placeholder="搜索笔记" value={libraryQuery} onChange={e => setLibraryQuery(e.target.value)} /></label></div>
          {!loaded ? <div className="skeleton-list" aria-label="资料库加载中"><div /><div /><div /></div> : library.length === 0 ? <div className="empty-library"><span className="empty-icon"><IconFileText size={29} /></span><div><h3>你的第一本视频笔记，从这里开始</h3><p>粘贴链接，或导入本地音视频。完成后会自动保存到资料库。</p></div><button className="icon-button" aria-label="开始导入" onClick={() => document.getElementById('source-input')?.focus()}><IconPlus size={24} /></button></div> : <div className="library-grid">{library.filter(v => v.title.toLowerCase().includes(libraryQuery.toLowerCase())).map(v => <button className="video-card" key={v.id} onClick={() => navigate(v.id)}><div className="cover">{v.thumbnail ? <img src={keyPath(v.id) + '/thumbnail'} onError={e => { e.currentTarget.style.visibility = 'hidden'; }} alt="" /> : <IconVideo size={36} />}<span>{v.duration ? time(v.duration) : v.id.startsWith('local:') ? '本地文件' : 'B 站视频'}</span></div><div className="card-copy"><div className="card-status">{v.ready ? '已保存' : v.status === 'failed' ? '需要处理' : '转录中'}<IconChevronRight size={16} /></div><h3>{v.title}</h3><p>{v.creator || '本地学习笔记'}<span>{v.provenance.includes('subtitle') ? '字幕' : v.ready ? '语音识别' : ''}</span></p></div></button>)}</div>}
          {library.length > 0 && !library.some(v => v.title.toLowerCase().includes(libraryQuery.toLowerCase())) && <p className="muted">没有匹配的笔记。</p>}
        </section>
        <footer className="home-footer"><IconShieldLock size={15} /> 原始时间轴独立保存 · 可读稿随时编辑 · 你的笔记始终可导出</footer>
      </main>
    </div> : <main className="workspace">
      <div className="workspace-heading"><button className="icon-button" aria-label="返回资料库" onClick={() => navigate(null)}><IconArrowLeft size={20} /></button><div><h1>{video?.title || '正在打开笔记…'}</h1><p>{video?.creator || '视频学习笔记'} {ready && ` · ${time(video.duration || video.segments.at(-1)!.end)} · ${video.provenance.includes('subtitle') ? '平台字幕' : '本地语音识别'}`}</p></div><button className="secondary" onClick={() => navigate(null)}><IconPlus size={17} /> 新建笔记</button></div>
      {ready ? <LearningWorkspace key={selected} video={video!} runId={activeRunId} dirty={versionDirty} llmConfigured={!!health?.llm_configured} onError={setError} onMessage={setNotice} transcript={<TranscriptWorkbench key={selected} videoKey={selected} config={{ ...settings, model }} onConfig={next => { setSettings(next); setModel(next.model); }} onRunId={setActiveRunId} onDirty={setVersionDirty} onMessage={setNotice} onError={setError} llmConfigured={!!health?.llm_configured} />} /> : <div className="workspace-grid">
        <aside className="source-panel panel"><div className="panel-heading"><h2><IconFolder size={18} /> 来源</h2><span>1</span></div><div className="source-detail">{video?.thumbnail && <img src={keyPath(video.id) + '/thumbnail'} alt="视频封面" onError={e => { e.currentTarget.style.display = 'none'; }} />}<div className="source-name"><IconVideo size={19} /><strong>{video?.title || selected}</strong></div><small>{ready ? `${video!.segments.length} 段原始字幕` : '等待转录完成'}</small>{video?.url.startsWith('https:') && <a className="text-button" href={video.url} target="_blank" rel="noreferrer">在 B 站打开 <IconArrowRight size={14} /></a>}</div>
          <div className="chapter-heading"><h3>时间导航</h3><small>按 5 分钟分段</small></div><nav className="chapters" aria-label="视频时间导航">{chapters.map(s => <button key={s.start} onClick={() => jump(s.start)}><span>{time(s.start)}</span><p>{s.text.slice(0, 32)}{s.text.length > 32 ? '…' : ''}</p></button>)}</nav><div className="source-foot"><IconShieldLock size={16} /><p>原始时间轴只读保存<br />编辑仅影响可读稿</p></div>
        </aside>
        {ready ? <TranscriptWorkbench key={selected} videoKey={selected} config={{ ...settings, model }} onConfig={next => { setSettings(next); setModel(next.model); }} onRunId={setActiveRunId} onDirty={setVersionDirty} onMessage={setNotice} onError={setError} llmConfigured={!!health?.llm_configured} /> : <section className="transcript-panel panel"><div className="panel-heading"><h2><IconFileText size={18} /> 转录笔记</h2><div className="toolbar"><button className="icon-button" disabled={!ready} onClick={copy} aria-label="复制当前文稿"><IconCopy size={17} /></button><details className="export-menu"><summary aria-label="导出文稿"><IconDownload size={18} /></summary><div>{['txt','srt','md'].map(fmt => ready && !dirty ? <a key={fmt} href={keyPath(selected) + `/export?format=${fmt}`}>{fmt.toUpperCase()}{fmt === 'srt' ? ' · 原始字幕' : ' · 已保存文稿'}</a> : <span key={fmt}>{dirty ? '先保存修改' : '转录完成后导出'}</span>)}</div></details></div></div>
          <div className="transcript-controls"><div className="tabs" role="tablist" aria-label="文稿视图"><button role="tab" aria-selected={view === 'original'} className={view === 'original' ? 'active' : ''} onClick={() => setView('original')}>原始时间轴</button><button role="tab" aria-selected={view === 'readable'} className={view === 'readable' ? 'active' : ''} onClick={() => setView('readable')}>可读稿{dirty && ' · 未保存'}</button></div>{ready && view === 'readable' && <button className="text-button" disabled={busy} onClick={() => editing ? void save() : setEditing(true)}>{editing ? busy ? '保存中…' : '保存修改' : '编辑文稿'}</button>}</div>
          {ready ? <><label className="transcript-search search-box"><IconSearch size={17} /><input aria-label="搜索文稿" placeholder="在文稿中搜索…" value={query} onChange={e => setQuery(e.target.value)} /><small>{query && `${filtered.length} 段匹配`}</small></label><div className="transcript-scroll">{view === 'original' ? <><p className="provenance-note">{video!.provenance.includes('subtitle') ? '以下内容来自平台可访问字幕。' : '以下内容由本地 Whisper 识别，可能存在听写误差。'} 保留原始文字与时间戳。</p>{filtered.map(s => <div className="segment" id={`segment-${s.start}`} key={`${s.start}-${s.end}`}><button className="timestamp" onClick={() => video!.url.startsWith('https:') && window.open(video!.url + `&t=${Math.floor(s.start)}`, '_blank', 'noopener,noreferrer')} title={video!.url.startsWith('https:') ? '在 B 站定位播放' : '本地文件时间戳'}>{time(s.start)}</button><p>{query ? s.text.split(new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi')).map((part, i) => part.toLowerCase() === query.toLowerCase() ? <mark key={i}>{part}</mark> : part) : s.text}</p></div>)}{!filtered.length && <p className="muted">没有找到匹配内容。</p>}</> : editing ? <><p className="provenance-note">整理版会补标点和分段；修改不会覆盖原稿。</p><textarea className="readable-editor" aria-label="编辑可读稿" value={draft} onChange={e => setDraft(e.target.value)} /><button className="text-button" onClick={() => { setDraft(video!.readable); setEditing(false); }}>放弃修改</button></> : <div className="readable"><p className="provenance-note">按原文整理标点与段落。{query && ' 搜索仅显示匹配段落。'}</p>{draft.split('\n\n').filter(p => p.toLowerCase().includes(query.toLowerCase())).map((p, i) => <p key={i}>{p}</p>)}</div>}</div></> : <div className="job-state"><IconFileText size={43} /><h3>{selectedJob?.status === 'failed' ? '这次导入未能完成' : '正在把视频变成笔记'}</h3><p>{selectedJob?.stage || '等待 worker 处理'}</p>{selectedJob && <><progress max={100} value={selectedJob.progress} /><small>{selectedJob.progress}% · 尝试 {selectedJob.attempts} 次</small></>}{selectedJob?.error && <div className="job-error">{selectedJob.error}</div>}{selectedJob?.status === 'failed' && <div className="job-actions"><button className="primary" onClick={async () => { try { await api(`/api/jobs/${selectedJob.id}/retry`, { method: 'POST' }); await refresh(); } catch (e) { setError((e as Error).message); } }}>重新尝试</button><button className="secondary" disabled={busy} onClick={() => upload.current?.click()}><IconUpload size={17} /> 导入本地文件</button></div>}{selectedJob?.status === 'failed' && <div className="failed-model-settings"><QualityControls value={{ ...settings, model }} onChange={next => { setSettings(next); setModel(next.model); }} /><button className="secondary" disabled={busy} onClick={async () => { setBusy(true); try { await api(keyPath(selected) + '/retranscribe', json({ ...settings, model })); setError(''); setNotice('已使用所选模型创建新的转录任务。'); await refresh(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } }}>使用所选模型重新转录</button></div>}<p className="job-help">平台访问限制不会被绕过。首次语音识别需要下载模型；<br />关闭页面不影响后台任务。</p></div>}
        </section>}
        <aside className="assistant-panel panel"><div className="panel-heading"><h2><span className="miku-avatar"><img src="/images/miku-learning.png" alt="" width={48} height={48} /></span> 学习助手</h2><span className="subtle-tag">{external ? 'LLM' : '本地检索'}</span></div><div className="chat-scroll">{chats.length === 0 ? <div className="assistant-empty"><h3>从一个好问题开始。</h3><p>输入关键词，找到视频中的相关原文。<br />每一条结果，都能回到时间轴。</p><button className="suggestion" disabled={!ready} onClick={() => setQuestion(video!.segments[0].text.slice(0, 8))}><IconSearch size={16} /> 查找开场提到的内容<IconArrowRight size={15} /></button></div> : chats.map((c, i) => <div className="chat-turn" key={i}><p className="chat-question">{c.question}</p><span className="answer-label">{c.mode === 'llm' ? 'AI 回答' : '原文检索'}</span><p className="chat-answer">{c.answer}</p><div className="citations">{c.citations.map((s, n) => <button key={n} onClick={() => jump(s.start)}>{time(s.start)}</button>)}</div></div>)}{asking && <p className="muted" role="status">正在查阅来源…</p>}</div><div className="assistant-compose">{health?.llm_configured && <label className="llm-toggle"><input type="checkbox" checked={external} onChange={e => setExternal(e.target.checked)} /> 使用已配置 LLM（发送相关原文）</label>}<form onSubmit={e => { e.preventDefault(); void ask(); }}><textarea aria-label="向学习助手提问" placeholder={ready ? '输入关键词或问题…' : '转录完成后开始探索'} value={question} disabled={!ready || asking} onChange={e => setQuestion(e.target.value)} /><button aria-label="发送问题" disabled={!ready || !question.trim() || asking}><IconSend size={19} /></button></form><small>{external ? 'AI 可能出错，请核对原文。' : '仅在本地检索 · 不发送内容到云端'}</small></div></aside>
      </div>}
    </main>}
  </div>;
}
