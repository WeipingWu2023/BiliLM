'use client';
import { useEffect, useState } from 'react';

export type ProofreadSummary = { status: string; model: string; automatic_segments: number; pending_segments: number; batches: number; search_requested: boolean; search_queries: number; warnings: string[]; sources: { url: string; title: string; snippet: string }[]; rejected: { reason: string }[] };
type Run = { id: string; proof_revision: number; readable_revision: number; config: Record<string, unknown>; proofreading?: ProofreadSummary | null; metrics: Record<string, unknown> };
type Job = { id: string; status: string };
export function AIProofreadingPanel({ run, configured, blocked, job, reload, onMessage }: { run: Run; configured: boolean; blocked: boolean; job: Job | null; reload: () => Promise<void>; onMessage: (s: string) => void }) {
  const [topic, setTopic] = useState(''); const [glossary, setGlossary] = useState(''); const [search, setSearch] = useState(false);
  const [sending, setSending] = useState(false); const [submitted, setSubmitted] = useState(''); const [error, setError] = useState('');
  useEffect(() => { setTopic(String(run.config.topic || '')); setGlossary(String(run.config.glossary || '')); }, [run.id]);
  const waiting = !!submitted && (job?.id !== submitted || ['queued','running'].includes(job.status));
  const active = waiting || !!job && ['queued','running'].includes(job.status);
  async function submit(undo = false) {
    setSending(true); setError('');
    try {
      const response = await fetch(`/api/runs/${run.id}/proofread/${undo ? 'undo' : 'pipeline'}`, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(undo ? {} : { proof_revision:run.proof_revision, readable_revision:run.readable_revision, use_search:search, topic, glossary }) });
      const result = await response.json(); if (!response.ok) throw Error(typeof result.detail === 'string' ? result.detail : '提交失败');
      if (undo) { await reload(); onMessage('已撤销最近一次 AI 校对，原稿保持独立。'); }
      else { setSubmitted(result.job_id); onMessage('AI 语境校对已进入持久队列；完成后自动更新校对稿、可读稿与来源。'); }
    } catch(e) { setError((e as Error).message); }
    finally { setSending(false); }
  }
  const report = run.proofreading;
  const automaticFailure = run.metrics.ai_proofreading as { status?: string; notice?: string } | undefined;
  return <section className="ai-proofreading" aria-label="AI 语境校对"><header><h3>先校对，再整理</h3><span>保留原稿 · 可撤销</span></header><p>利用上下文识别同音专名，例如“返振东 → 樊振东”。有标题/词表或权威拼写依据的同音修正可自动应用；标题/词表中的专名也允许单处前后鼻音差异（如“樊正东”）。其余留待重听。</p>
    <div className="ai-proofreading-fields"><label>内容主题<input aria-label="校对主题" maxLength={300} value={topic} onChange={e => setTopic(e.target.value)} placeholder="例如：乒乓球赛事、国乒运动员" /></label><label>已知专名 / 术语<textarea aria-label="校对专名词表" maxLength={2000} value={glossary} onChange={e => setGlossary(e.target.value)} placeholder="例如：樊振东、王励勤、马龙。只用于实际出现的内容。" /></label></div>
    <label className="quality-check"><input type="checkbox" checked={search} onChange={e => setSearch(e.target.checked)} /> 联网核对专名拼写（官方 DeepSeek Search，最多 3 次检索，可能另行计费）</label>
    <small>点击将发送当前文稿、标题和词表到已配置 AI，最多 8 批请求；联网时只检索候选词与主题。会重生成可读稿，旧内容写入改动日志。不改变时间戳，不声称听音验证。</small>
    <div className="ai-proofreading-actions"><button className="primary" disabled={!configured || blocked || sending || active} onClick={() => void submit()}>{sending || active ? '校对处理中…可离开页面' : 'AI 语境校对并生成可读稿'}</button>{report && <button className="text-button" disabled={blocked || sending || active} onClick={() => void submit(true)}>撤销最近 AI 校对</button>}</div>
    {!configured && <p className="muted">请先到来源问答配置 DeepSeek；仍可仅使用本地转录。</p>}
    {error && <p className="error-text" role="alert">{error}</p>}
    {!report && automaticFailure?.status === 'failed' && <p className="error-text" role="alert">{automaticFailure.notice || '自动 AI 校对未完成，原稿已保存；可在此重新校对。'}</p>}
    {report && <div className="ai-proofreading-report" role="status"><strong>自动修改 {report.automatic_segments} 段 · 待复核 {report.pending_segments} 段</strong><p>{report.model} · {report.batches} 批 · {report.search_requested ? `成功完成 ${report.search_queries} 次拼写检索` : '未联网检索'} · 未听音验证</p>{report.warnings?.map((s,i) => <p key={i}>{s}</p>)}{report.rejected?.length>0 && <p>{report.rejected.length} 个候选定位不可靠，未应用；详见改动记录。</p>}{report.sources?.length>0 && <details><summary>查看拼写参考来源（不能证明音频说了这些内容）</summary>{report.sources.map((s,i) => <p key={i}><a href={s.url} target="_blank" rel="noreferrer">{s.title || s.url}</a><small>{s.snippet}</small></p>)}</details>}</div>}
  </section>;
}
