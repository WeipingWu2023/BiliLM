'use client';
import { useEffect, useRef, useState } from 'react';
import { IconCopy, IconDownload, IconFileText, IconRefresh } from '@tabler/icons-react';
import { ASRSettings, QualityControls } from './quality-controls';

type Segment = { start:number; end:number; text:string };
type Final = { status:string; message:string; run_id?:string; revision?:number; segments?:Segment[]; readable?:string; playback?:boolean };
async function request<T>(url:string, body:unknown, method='POST'):Promise<T> {
  const response=await fetch(url,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const value=await response.json(); if(!response.ok) throw Error(typeof value.detail==='string'?value.detail:'暂时无法处理文稿'); return value;
}
export function TranscriptWorkbench({videoKey,config,onConfig,onRunId,onDirty,onError,onMessage,llmConfigured}:{videoKey:string;config:ASRSettings;onConfig:(v:ASRSettings)=>void;onRunId:(s:string)=>void;onDirty:(b:boolean)=>void;onError:(s:string)=>void;onMessage:(s:string)=>void;llmConfigured:boolean}) {
  const [state,setState]=useState<Final>({status:'processing',message:'正在准备文稿…'});
  const [query,setQuery]=useState(''); const [editing,setEditing]=useState(false); const [draft,setDraft]=useState<string[]>([]); const [busy,setBusy]=useState(false);
  const audio=useRef<HTMLAudioElement>(null); const signature=useRef(''); const lastStatus=useRef(''); const base=`/api/videos/${encodeURIComponent(videoKey)}`;
  const ready=state.status==='ready'; const dirty=editing&&draft.some((t,i)=>t!==state.segments?.[i]?.text);
  useEffect(()=>{onDirty(dirty);return()=>onDirty(false)},[dirty,onDirty]);
  function receive(value:Final) {
    if(value.status==='failed'&&lastStatus.current!==value.status)onError(value.message);
    lastStatus.current=value.status;
    const next=value.status==='ready'?`${value.run_id}:${value.revision}`:'';
    if(signature.current&&signature.current!==next)window.dispatchEvent(new Event('bililm-source-updated'));
    signature.current=next;setState(previous=>previous.status===value.status&&previous.run_id===value.run_id&&previous.revision===value.revision&&previous.message===value.message?previous:value);
    onRunId(value.status==='ready'?value.run_id!: '');
  }
  useEffect(()=>{
    let active=true, fetching=false; signature.current='';onRunId('');
    const poll=async()=>{if(fetching)return;fetching=true;try{const value=await request<Final>(base+'/finalize',{});if(active)receive(value)}catch(e){if(active)setState({status:'failed',message:(e as Error).message})}finally{fetching=false}};
    void poll();const timer=setInterval(poll,3000);return()=>{active=false;clearInterval(timer)};
  },[base,llmConfigured,onRunId]);
  useEffect(()=>{
    const jump=(event:Event)=>{const start=(event as CustomEvent<number>).detail;setQuery('');requestAnimationFrame(()=>{document.getElementById(`segment-${start}`)?.scrollIntoView({block:'center',behavior:'smooth'});if(audio.current){audio.current.currentTime=Math.max(0,start-.3);void audio.current.play().catch(()=>{})}})};
    window.addEventListener('bililm-transcript-jump',jump);return()=>window.removeEventListener('bililm-transcript-jump',jump);
  },[]);
  async function act(action:()=>Promise<void>){setBusy(true);try{await action()}catch(e){onError((e as Error).message)}finally{setBusy(false)}}
  const paragraphs:Segment[][]=[];let count=0;
  for(const row of state.segments||[]){if(!paragraphs.length||count>=180){paragraphs.push([]);count=0}paragraphs[paragraphs.length-1].push(row);count+=row.text.length}
  return <section className="transcript-panel panel version-workbench final-workbench"><div className="panel-heading"><h2><IconFileText size={18}/> 完整文稿</h2><div className="toolbar"><button className="icon-button" aria-label="复制文稿" disabled={!ready||dirty} onClick={()=>void act(async()=>{await navigator.clipboard.writeText(state.readable!);onMessage('已复制完整文稿。')})}><IconCopy size={17}/></button><a className="text-button final-download" aria-label="下载文稿" aria-disabled={!ready||dirty} href={ready&&!dirty?base+'/final/export?format=md':undefined}><IconDownload size={17}/> 下载文稿</a><details className="export-menu"><summary aria-label="其他下载格式">其他格式</summary><div>{['txt','srt'].map(format=>ready&&!dirty?<a key={format} href={`${base}/final/export?format=${format}`} onClick={e=>e.currentTarget.closest('details')?.removeAttribute('open')}>{format.toUpperCase()}</a>:<span key={format}>{dirty?'请先保存修改':'文稿完成后可下载'}</span>)}</div></details></div></div>
    {!ready?<div className="final-preparing" role="status"><IconFileText size={32}/><h3>{state.status==='needs_configuration'?'首次使用：连接 DeepSeek':state.status==='failed'?'文稿尚未完成':'正在为你整理文稿'}</h3><p>{state.message}</p>{state.status==='needs_configuration'&&<p>回到“来源问答”打开 DeepSeek 设置，保存一次后即可自动处理。</p>}{state.status==='failed'&&<button className="primary" disabled={busy} onClick={()=>void act(async()=>receive(await request<Final>(base+'/finalize',{retry:true})))}>重新处理</button>}</div>:<>
    <div className="transcript-controls"><span className="final-ready">已自动校对 · 可直接阅读和下载</span><button className="text-button" disabled={busy} onClick={()=>editing?void act(async()=>{receive(await request<Final>(base+'/final',{texts:draft,revision:state.revision,run_id:state.run_id},'PUT'));setEditing(false);window.dispatchEvent(new Event('bililm-source-updated'));onMessage('文稿已保存，总结与导图将使用最新内容。')}):(setDraft(state.segments!.map(s=>s.text)),setEditing(true))}>{editing?'保存修改':'编辑文稿'}</button></div>
    <label className="transcript-search search-box"><input aria-label="搜索文稿" placeholder="在文稿中搜索…" value={query} onChange={e=>setQuery(e.target.value)}/></label>
    <div className="transcript-scroll"><div className="readable final-readable">{editing?draft.map((text,i)=><textarea className="segment-editor" key={i} aria-label={`编辑片段 ${i+1}`} value={text} onChange={e=>setDraft(old=>old.map((s,n)=>n===i?e.target.value:s))}/>):paragraphs.filter(rows=>!query||rows.some(r=>r.text.toLowerCase().includes(query.toLowerCase()))).map((rows,i)=><p key={i}>{rows.map(r=><span key={r.start} id={`segment-${r.start}`}>{r.text}{' '}</span>)}</p>)}</div>{editing&&<button className="text-button" onClick={()=>setEditing(false)}>取消编辑</button>}
    <details className="final-options"><summary>音频与转录设置</summary>{state.playback&&<audio ref={audio} controls preload="none" src={`/api/runs/${state.run_id}/audio`} aria-label="来源音频播放"/>}<QualityControls value={config} onChange={onConfig}/><button className="text-button" disabled={busy||dirty} onClick={()=>void act(async()=>{await request(base+'/retranscribe',config);receive({status:'processing',message:'正在重新生成文稿…'});onMessage('已开始重新转录和自动校对。')})}><IconRefresh size={15}/> 使用所选模型重新生成</button></details>
    </div></>}
  </section>;
}
