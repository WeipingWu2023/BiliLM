'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { IconArrowRight, IconChevronDown, IconChevronRight, IconDownload, IconFocusCentered, IconMaximize, IconMinimize, IconX, IconZoomIn, IconZoomOut } from '@tabler/icons-react';

type Citation = { start: number; end: number; text: string };
type Node = { text: string; citations: number[]; children?: Node[] };
type MapData = { title?: string; mode: string; branches?: Node[]; citations: Citation[]; notice: string; stale?: boolean };
type Pose = { x: number; y: number; scale: number };
const stamp = (s: number) => `${Math.floor(s / 60).toString().padStart(2, '0')}:${Math.floor(s % 60).toString().padStart(2, '0')}`;

export function MindMapViewer({ open, onClose, title, map, onLocate, onExport }: { open: boolean; onClose: () => void; title: string; map: MapData | null; onLocate: (c: Citation) => void; onExport: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const viewport = useRef<HTMLDivElement>(null);
  const tree = useRef<HTMLDivElement>(null);
  const scaleLabel = useRef<HTMLButtonElement>(null);
  const pose = useRef<Pose>({ x: 30, y: 30, scale: 1 });
  const drag = useRef<{ id: number; x: number; y: number; origin: Pose; moved: boolean } | null>(null);
  const suppressClick = useRef(false);
  const [full, setFull] = useState(false);
  const [expanded, setExpanded] = useState<number[]>([0]);
  const [evidence, setEvidence] = useState<Citation | null>(null);
  const [paths, setPaths] = useState<string[]>([]);

  // Continuous pan updates stay outside React: nodes do not rerender per pointer move.
  const paint = useCallback(() => {
    const { x, y, scale } = pose.current;
    if (tree.current) tree.current.style.transform = `translate3d(${x}px,${y}px,0) scale(${scale})`;
    if (scaleLabel.current) scaleLabel.current.textContent = `${Math.round(scale * 100)}%`;
  }, []);
  const fit = useCallback(() => {
    const frame = viewport.current, content = tree.current;
    if (!frame || !content) return;
    const next = Math.max(0.25, Math.min(1, (frame.clientWidth - 48) / content.offsetWidth, (frame.clientHeight - 48) / content.offsetHeight));
    pose.current = { x: (frame.clientWidth - content.offsetWidth * next) / 2, y: (frame.clientHeight - content.offsetHeight * next) / 2, scale: next };
    paint();
  }, [paint]);
  const zoomAt = useCallback((next: number, x?: number, y?: number) => {
    const frame = viewport.current;
    if (!frame) return;
    const old = pose.current;
    const bounded = Math.min(2.5, Math.max(0.25, next));
    const anchorX = x ?? frame.clientWidth / 2, anchorY = y ?? frame.clientHeight / 2;
    pose.current = { x: anchorX - (anchorX - old.x) * bounded / old.scale, y: anchorY - (anchorY - old.y) * bounded / old.scale, scale: bounded };
    paint();
  }, [paint]);

  useEffect(() => {
    if (open) { setFull(false); setExpanded([0]); setEvidence(null); dialog.current?.showModal(); }
    else { dialog.current?.close(); drag.current = null; }
  }, [open]);
  useEffect(() => {
    if (!open) return;
    const frame = requestAnimationFrame(fit);
    return () => cancelAnimationFrame(frame);
  }, [open, full, map, fit]);
  useEffect(() => {
    const content = tree.current;
    if (!open || !content) return;
    const measure = () => {
      const origin = content.getBoundingClientRect(), zoom = pose.current.scale;
      const nodes = new Map(Array.from(content.querySelectorAll<HTMLElement>('[data-map-node]')).map(el => [el.dataset.mapNode!, el]));
      const links: string[] = [];
      nodes.forEach(node => {
        const parent = nodes.get(node.dataset.mapParent || '');
        if (!parent) return;
        const a = parent.getBoundingClientRect(), b = node.getBoundingClientRect();
        const x1 = (a.right - origin.left) / zoom, y1 = (a.top + a.height / 2 - origin.top) / zoom;
        const x2 = (b.left - origin.left) / zoom, y2 = (b.top + b.height / 2 - origin.top) / zoom;
        const middle = (x1 + x2) / 2;
        links.push(`M ${x1} ${y1} C ${middle} ${y1}, ${middle} ${y2}, ${x2} ${y2}`);
      });
      setPaths(links);
    };
    const observer = new ResizeObserver(measure); observer.observe(content);
    const frame = requestAnimationFrame(measure);
    return () => { observer.disconnect(); cancelAnimationFrame(frame); };
  }, [open, expanded, map]);
  useEffect(() => {
    const frame = viewport.current;
    if (!open || !frame) return;
    const wheel = (event: WheelEvent) => {
      event.preventDefault();
      const rect = frame.getBoundingClientRect();
      zoomAt(pose.current.scale * Math.exp(-event.deltaY * 0.0015), event.clientX - rect.left, event.clientY - rect.top);
    };
    frame.addEventListener('wheel', wheel, { passive: false });
    return () => frame.removeEventListener('wheel', wheel);
  }, [open, zoomAt]);

  const citations = (ids: number[]) => <span className="learning-citations">{ids.map(id => map?.citations[id] && <button key={id} aria-label={`查看引用 ${stamp(map.citations[id].start)}`} onClick={() => setEvidence(map.citations[id])}>{stamp(map.citations[id].start)}</button>)}</span>;
  const endDrag = () => { drag.current = null; viewport.current?.removeAttribute('data-dragging'); };

  return <dialog ref={dialog} className={`mindmap-dialog map-viewer${full ? ' map-viewer-full' : ''}`} aria-label="思维导图查看器" onCancel={event => { if (full) { event.preventDefault(); setFull(false); } else onClose(); }}>
    <header className="mindmap-heading map-viewer-heading">
      <div><h2>{map?.mode === 'llm' ? '思维导图' : '原文结构导图'}</h2><p>{map?.title || title}</p><span className="map-source-pill">1 个来源 · {map?.mode === 'llm' ? 'AI 生成，需核对' : '本地原文'}{map?.stale && ' · 历史版本'}</span></div>
      <div className="map-actions"><button className="icon-button" aria-label="导出导图" title="导出 Markdown" onClick={onExport}><IconDownload size={19} /></button><button className="icon-button" aria-label={full ? '退出导图全屏' : '全屏显示导图'} title={full ? '退出全屏' : '铺满窗口'} onClick={() => setFull(value => !value)}>{full ? <IconMinimize size={19} /> : <IconMaximize size={19} />}</button><button className="icon-button" aria-label="关闭思维导图" onClick={onClose}><IconX size={21} /></button></div>
    </header>
    <div ref={viewport} className="mindmap-scroll map-canvas" tabIndex={0} role="region" aria-label="思维导图画布：拖动平移，滚轮缩放，方向键移动，0 适应窗口"
      onPointerDown={event => { if (event.button !== 0) return; suppressClick.current = false; drag.current = { id: event.pointerId, x: event.clientX, y: event.clientY, origin: { ...pose.current }, moved: false }; }}
      onPointerMove={event => {
        const current = drag.current;
        if (!current || current.id !== event.pointerId) return;
        const dx = event.clientX - current.x, dy = event.clientY - current.y;
        if (!current.moved && Math.hypot(dx, dy) < 5) return;
        if (!current.moved) { current.moved = true; event.currentTarget.setPointerCapture(event.pointerId); event.currentTarget.setAttribute('data-dragging', 'true'); }
        suppressClick.current = true;
        pose.current = { ...current.origin, x: current.origin.x + dx, y: current.origin.y + dy }; paint();
      }}
      onPointerUp={endDrag} onPointerCancel={endDrag}
      onClickCapture={event => { if (suppressClick.current) { event.preventDefault(); event.stopPropagation(); suppressClick.current = false; } }}
      onDoubleClick={event => { if (!(event.target as HTMLElement).closest('button')) fit(); }}
      onKeyDown={event => {
        if (event.target !== event.currentTarget) return;
        const directions: Record<string, [number, number]> = { ArrowLeft: [40, 0], ArrowRight: [-40, 0], ArrowUp: [0, 40], ArrowDown: [0, -40] };
        if (directions[event.key]) { event.preventDefault(); const [x, y] = directions[event.key]; pose.current = { ...pose.current, x: pose.current.x + x, y: pose.current.y + y }; paint(); }
        else if (event.key === '+' || event.key === '=') { event.preventDefault(); zoomAt(pose.current.scale * 1.2); }
        else if (event.key === '-') { event.preventDefault(); zoomAt(pose.current.scale / 1.2); }
        else if (event.key === '0' || event.key === 'Home') { event.preventDefault(); fit(); }
      }}>
      <div ref={tree} className="mindmap-tree map-tree"><svg className="map-links" aria-hidden="true">{paths.map((d, i) => <path key={i} d={d} />)}</svg><div className="mindmap-root" data-map-node="root">{map?.title || title}</div><ul>{map?.branches?.map((branch, i) => <li key={i}><div className="mindmap-branch" data-map-node={`b${i}`} data-map-parent="root"><button aria-expanded={expanded.includes(i)} onClick={() => setExpanded(values => values.includes(i) ? values.filter(n => n !== i) : [...values, i])}>{expanded.includes(i) ? <IconChevronDown size={15} /> : <IconChevronRight size={15} />}{branch.text}</button>{citations(branch.citations)}</div>{expanded.includes(i) && <ul>{branch.children?.map((child, n) => <li key={n}><button className="mindmap-leaf" data-map-node={`b${i}c${n}`} data-map-parent={`b${i}`} onClick={() => { const citation = map.citations[child.citations[0]]; if (citation) setEvidence(citation); }}>{child.text}</button></li>)}</ul>}</li>)}</ul></div>
    </div>
    <div className="map-navigation" aria-label="导图缩放工具"><button className="icon-button" aria-label="缩小导图" onClick={() => zoomAt(pose.current.scale / 1.2)}><IconZoomOut size={19} /></button><button ref={scaleLabel} className="map-scale" aria-label="重置为百分之百" onClick={() => zoomAt(1)}>100%</button><button className="icon-button" aria-label="放大导图" onClick={() => zoomAt(pose.current.scale * 1.2)}><IconZoomIn size={19} /></button><span /><button className="icon-button" aria-label="适应窗口" title="适应窗口（0）" onClick={fit}><IconFocusCentered size={19} /></button></div>
    {evidence && <div className="mindmap-evidence"><div className="map-evidence-title"><strong>来源原文 · {stamp(evidence.start)}</strong><button className="icon-button" aria-label="关闭导图引用" onClick={() => setEvidence(null)}><IconX size={15} /></button></div><p>{evidence.text}</p><button className="text-button" disabled={map?.stale} onClick={() => { onClose(); onLocate(evidence); }}>在文稿中核对 <IconArrowRight size={14} /></button></div>}
    <footer className="map-viewer-footer"><span>拖动画布 · 滚轮缩放 · 点击节点核对原文</span><span>AI 内容可能有误，以来源为准</span></footer>
  </dialog>;
}
