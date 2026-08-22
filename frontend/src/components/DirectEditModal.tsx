import { Check, Loader2, RotateCcw, X } from 'lucide-react';
import { useRef, useState } from 'react';

export interface DirectEditState {
  headline: string;
  subtitle: string;
  zoom: number;
  offset_x: number;
  offset_y: number;
  text_x: number;
  text_y: number;
  font_size: number;
  text_color: string;
  text_align: 'left' | 'center';
  text_background: boolean;
  replacement_node_id?: string | null;
}

interface DragState { x: number; y: number; start: DirectEditState }

export default function DirectEditModal({ imageUrl, title, materials, onClose, onSave }: {
  imageUrl: string;
  title: string;
  materials: Array<{ id: string; imageUrl: string; label: string }>;
  onClose: () => void;
  onSave: (state: DirectEditState) => Promise<void>;
}) {
  const initial: DirectEditState = { headline: title, subtitle: '', zoom: 1, offset_x: 0, offset_y: 0, text_x: .08, text_y: .78, font_size: 42, text_color: '#183028', text_align: 'left', text_background: true, replacement_node_id: null };
  const [state, setState] = useState(initial);
  const [history, setHistory] = useState<DirectEditState[]>([]);
  const [saving, setSaving] = useState(false);
  const [preview, setPreview] = useState(imageUrl);
  const imageDrag = useRef<DragState | null>(null);
  const textDrag = useRef<DragState | null>(null);
  const checkpoint = () => setHistory(items => [...items.slice(-19), state]);

  function beginImageDrag(event: React.PointerEvent<HTMLDivElement>) {
    checkpoint();
    imageDrag.current = { x: event.clientX, y: event.clientY, start: state };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function moveImage(event: React.PointerEvent<HTMLDivElement>) {
    if (!imageDrag.current) return;
    const { start, x, y } = imageDrag.current;
    setState({ ...start, offset_x: Math.max(-1, Math.min(1, start.offset_x + (event.clientX - x) / event.currentTarget.clientWidth * 2)), offset_y: Math.max(-1, Math.min(1, start.offset_y + (event.clientY - y) / event.currentTarget.clientHeight * 2)) });
  }

  function beginTextDrag(event: React.PointerEvent<HTMLDivElement>) {
    event.stopPropagation();
    checkpoint();
    textDrag.current = { x: event.clientX, y: event.clientY, start: state };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function moveText(event: React.PointerEvent<HTMLDivElement>) {
    event.stopPropagation();
    if (!textDrag.current) return;
    const canvas = event.currentTarget.parentElement;
    if (!canvas) return;
    const { start, x, y } = textDrag.current;
    setState({ ...start, text_x: Math.max(0, Math.min(.9, start.text_x + (event.clientX - x) / canvas.clientWidth)), text_y: Math.max(0, Math.min(.95, start.text_y + (event.clientY - y) / canvas.clientHeight)) });
  }

  function undo() {
    const previous = history.at(-1);
    if (previous) { setState(previous); setHistory(items => items.slice(0, -1)); }
  }

  return <div className="fixed inset-0 z-50 bg-black/60 p-4 overflow-auto" onClick={onClose}>
    <div className="max-w-6xl mx-auto bg-white rounded-2xl overflow-hidden grid lg:grid-cols-[1fr_380px]" onClick={event => event.stopPropagation()}>
      <div className="bg-[#d9d7d1] p-6 grid place-items-center">
        <div className="relative w-full max-w-[590px] aspect-[3/4] overflow-hidden bg-white shadow-2xl cursor-grab touch-none" onPointerDown={beginImageDrag} onPointerMove={moveImage} onPointerUp={() => imageDrag.current = null} onWheel={event => { event.preventDefault(); checkpoint(); setState({ ...state, zoom: Math.max(1, Math.min(2, state.zoom - event.deltaY * .001)) }); }}>
          <img src={preview} draggable={false} className="w-full h-full object-cover pointer-events-none" style={{ transform: `translate(${state.offset_x * 18}%,${state.offset_y * 18}%) scale(${state.zoom})` }} />
          <div className={`absolute max-w-[84%] rounded-xl p-3 cursor-move select-none ${state.text_background ? 'bg-[#f8f7f2]/90' : ''}`} style={{ left: `${state.text_align === 'center' ? 50 : state.text_x * 100}%`, top: `${state.text_y * 100}%`, color: state.text_color, textAlign: state.text_align, transform: state.text_align === 'center' ? 'translateX(-50%)' : undefined }} onPointerDown={beginTextDrag} onPointerMove={moveText} onPointerUp={() => textDrag.current = null}>
            <div className="font-medium leading-tight whitespace-nowrap" style={{ fontSize: `${Math.max(16, state.font_size * .56)}px` }}>{state.headline || '拖动标题'}</div>
            {state.subtitle && <div className="mt-2 opacity-80" style={{ fontSize: `${Math.max(12, state.font_size * .31)}px` }}>{state.subtitle}</div>}
          </div>
          <span className="absolute top-3 left-3 bg-black/55 text-white rounded-full px-3 py-1 text-xs pointer-events-none">拖动画面 · 拖动标题 · 滚轮缩放</span>
        </div>
      </div>
      <aside className="p-6 space-y-4">
        <div className="flex justify-between"><div><h3 className="font-medium">直接编辑 · {title}</h3><p className="text-xs text-[var(--muted)] mt-1">调整画面和文字，保存为新版本。</p></div><button onClick={onClose}><X size={18} /></button></div>
        {materials.length > 0 && <div><div className="text-xs text-[var(--muted)] mb-2">点击替换画面素材</div><div className="flex gap-2 overflow-x-auto pb-2">{materials.map(item => <button key={item.id} title={item.label} onClick={() => { checkpoint(); setPreview(item.imageUrl); setState({ ...state, replacement_node_id: item.id, zoom: 1, offset_x: 0, offset_y: 0 }); }}><img src={item.imageUrl} className={`w-16 h-16 object-cover rounded-lg border-2 ${state.replacement_node_id === item.id ? 'border-[var(--accent)]' : 'border-transparent'}`} /></button>)}</div></div>}
        <button className="btn-secondary" disabled={!history.length} onClick={undo}><RotateCcw size={14} />撤销</button>
        <input className="input w-full" value={state.headline} onChange={event => setState({ ...state, headline: event.target.value })} />
        <input className="input w-full" placeholder="副标题" value={state.subtitle} onChange={event => setState({ ...state, subtitle: event.target.value })} />
        <label className="block text-sm">标题字号 <span className="text-xs text-[var(--muted)]">{state.font_size}px</span><input type="range" className="w-full mt-2" min="18" max="96" value={state.font_size} onChange={event => setState({ ...state, font_size: Number(event.target.value) })} /></label>
        <div className="grid grid-cols-2 gap-3"><label className="text-sm">文字颜色<input type="color" className="mt-2 h-10 w-full rounded border border-[var(--border)]" value={state.text_color} onChange={event => setState({ ...state, text_color: event.target.value })} /></label><label className="text-sm">对齐方式<select className="input w-full mt-2" value={state.text_align} onChange={event => setState({ ...state, text_align: event.target.value as DirectEditState['text_align'] })}><option value="left">左对齐</option><option value="center">居中</option></select></label></div>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={state.text_background} onChange={event => setState({ ...state, text_background: event.target.checked })} />使用文字背景遮罩</label>
        <button className="btn-primary w-full justify-center" disabled={saving} onClick={async () => { setSaving(true); try { await onSave(state); } finally { setSaving(false); } }}>{saving ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}保存为新版本</button>
      </aside>
    </div>
  </div>;
}
