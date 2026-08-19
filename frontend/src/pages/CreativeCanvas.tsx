import { useCallback, useEffect, useRef, useState } from 'react';
import { Arrow, Image as KonvaImage, Layer, Rect, Stage, Transformer } from 'react-konva';
import type Konva from 'konva';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import {
  ArrowLeft, Award, BookOpen, Check, Download, Focus, Grid2X2, HelpCircle, ImagePlus,
  Loader2, Palette, Redo2, Save, ShieldCheck, Sparkles, Trash2, Undo2, Upload, X,
} from 'lucide-react';
import { creativeApi, mediaUrl, productApi } from '../api/client';
import type { CanvasNodeRecord, CreativeFeedback, CreativeProject, LearnedDesignProfile, Product } from '../types';

type CanvasItem = {
  id: string;
  nodeType: string;
  parentNodeId?: string | null;
  x: number;
  y: number;
  width: number;
  height: number;
  imageUrl?: string;
  label: string;
  data: Record<string, unknown>;
  reviewStatus?: string;
};

type Viewport = { x: number; y: number; zoom: number };
type SelectionBox = { visible: boolean; x: number; y: number; width: number; height: number; startX: number; startY: number };
type GenerationBasis = {
  material_strategy?: string;
  materials?: Array<{ id: string; type: string; label?: string }>;
  brand_documents?: Array<{ id: number; title: string }>;
  skills?: Array<{ id: number; name: string; scope: string }>;
  learned_profile?: boolean;
};

const VISUAL_OPTIONS = {
  '整体气质': ['高级克制', '自然温和', '年轻清透', '科技专业', '东方雅致'],
  '构图方式': ['商品居中', '左右结构', '俯拍构图', '悬浮展示', '近景特写'],
  '场景光线': ['米白棚拍', '东方草本', '梳妆台场景', '柔和晨光', '商业柔光'],
};

const MIN_ZOOM = 0.15;
const MAX_ZOOM = 3;

function useHtmlImage(url?: string) {
  const [image, setImage] = useState<HTMLImageElement | null>(null);
  useEffect(() => {
    if (!url) { setImage(null); return; }
    const next = new window.Image();
    next.crossOrigin = 'anonymous';
    next.onload = () => setImage(next);
    next.src = mediaUrl(url);
    return () => { next.onload = null; };
  }, [url]);
  return image;
}

function CanvasPicture({ item, selected, onSelect, onChange }: {
  item: CanvasItem;
  selected: boolean;
  onSelect: (event: Konva.KonvaEventObject<MouseEvent | TouchEvent>) => void;
  onChange: (next: CanvasItem) => void;
}) {
  const image = useHtmlImage(item.imageUrl);
  const shapeRef = useRef<Konva.Image>(null);
  const transformerRef = useRef<Konva.Transformer>(null);

  useEffect(() => {
    if (selected && transformerRef.current && shapeRef.current) {
      transformerRef.current.nodes([shapeRef.current]);
      transformerRef.current.getLayer()?.batchDraw();
    }
  }, [selected]);

  const border = item.data.is_final ? '#d59b22' : item.reviewStatus === 'rejected' ? '#dc6b6b' : item.reviewStatus === 'usable' ? '#238765' : '#ffffff';
  return <>
    <KonvaImage
      ref={shapeRef}
      id={item.id}
      name="canvas-picture"
      image={image || undefined}
      x={item.x}
      y={item.y}
      width={item.width}
      height={item.height}
      draggable
      stroke={selected ? '#087866' : border}
      strokeWidth={selected ? 5 : 3}
      shadowColor="#283a34"
      shadowBlur={selected ? 18 : 8}
      shadowOpacity={0.2}
      shadowOffsetY={4}
      onClick={onSelect}
      onTap={onSelect}
      onDragEnd={(event) => onChange({ ...item, x: event.target.x(), y: event.target.y() })}
      onTransformEnd={() => {
        const shape = shapeRef.current;
        if (!shape) return;
        const scaleX = shape.scaleX();
        const scaleY = shape.scaleY();
        shape.scaleX(1); shape.scaleY(1);
        onChange({ ...item, x: shape.x(), y: shape.y(), width: Math.max(80, shape.width() * scaleX), height: Math.max(80, shape.height() * scaleY) });
      }}
    />
    {selected && <Transformer ref={transformerRef} rotateEnabled={false} flipEnabled={false} keepRatio borderStroke="#087866" anchorFill="#ffffff" anchorStroke="#087866" anchorSize={10} boundBoxFunc={(oldBox, newBox) => newBox.width < 80 || newBox.height < 80 ? oldBox : newBox} />}
  </>;
}

function toItem(row: CanvasNodeRecord, feedback?: CreativeFeedback): CanvasItem {
  return {
    id: row.id,
    nodeType: row.node_type,
    parentNodeId: row.parent_node_id,
    x: row.position_x,
    y: row.position_y,
    width: row.width || 280,
    height: row.height || 320,
    imageUrl: row.data.image_url ? String(row.data.image_url) : undefined,
    label: String(row.data.label || row.node_type),
    data: row.data,
    reviewStatus: feedback?.status,
  };
}

function intersects(a: { x: number; y: number; width: number; height: number }, b: CanvasItem) {
  return a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y;
}

export default function CreativeCanvasPage() {
  const projectId = Number(useParams().id);
  const [searchParams, setSearchParams] = useSearchParams();
  const stageRef = useRef<Konva.Stage>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const saveTimer = useRef<number | null>(null);
  const historyRef = useRef<CanvasItem[][]>([]);
  const historyIndexRef = useRef(-1);
  const [spacePressed, setSpacePressed] = useState(false);
  const [project, setProject] = useState<CreativeProject | null>(null);
  const [product, setProduct] = useState<Product | null>(null);
  const [items, setItemsState] = useState<CanvasItem[]>([]);
  const [profile, setProfile] = useState<LearnedDesignProfile | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [viewport, setViewport] = useState<Viewport>({ x: 40, y: 40, zoom: 0.8 });
  const [canvasSize, setCanvasSize] = useState({ width: 900, height: 700 });
  const [selectionBox, setSelectionBox] = useState<SelectionBox>({ visible: false, x: 0, y: 0, width: 0, height: 0, startX: 0, startY: 0 });
  const [prompt, setPrompt] = useState('保持商品包装、品牌名称和瓶身结构准确');
  const [visualTags, setVisualTags] = useState<string[]>(['高级克制', '东方雅致', '商品居中', '米白棚拍', '商业柔光']);
  const [showAdvancedPrompt, setShowAdvancedPrompt] = useState(false);
  const [advancedPrompt, setAdvancedPrompt] = useState('');
  const [action, setAction] = useState('详情页·首屏');
  const [autoSelectMaterials, setAutoSelectMaterials] = useState(true);
  const [lastGenerationBasis, setLastGenerationBasis] = useState<GenerationBasis | null>(null);
  const [busy, setBusy] = useState(false);
  const [showHelp, setShowHelp] = useState(false);
  const [showWelcome, setShowWelcome] = useState(searchParams.get('welcome') === '1');
  const [workspaceMode, setWorkspaceMode] = useState<'design' | 'expert'>(() => localStorage.getItem('creative_workspace_mode') === 'expert' ? 'expert' : 'design');
  const [dragOver, setDragOver] = useState(false);
  const [deliveryNote, setDeliveryNote] = useState('');
  const [deliveryMessage, setDeliveryMessage] = useState('');
  const [error, setError] = useState('');

  const selected = items.filter((item) => selectedIds.includes(item.id));
  const materials = items.filter((item) => ['product', 'product_image', 'detail_image', 'brand_asset', 'reference'].includes(item.nodeType));
  const results = items.filter((item) => ['generated', 'refined', 'deliverable'].includes(item.nodeType));
  const productMaterials = materials.filter((item) => ['product', 'product_image'].includes(item.nodeType));
  const supportingMaterials = materials.filter((item) => !['product', 'product_image'].includes(item.nodeType));
  const assembledPrompt = [`任务：${action}`, visualTags.length ? `视觉要求：${visualTags.join('、')}` : '', prompt.trim() ? `补充要求：${prompt.trim()}` : '', '避免包装变形、品牌文字错误、元素拥挤和廉价促销感'].filter(Boolean).join('。');

  const commitItems = useCallback((next: CanvasItem[] | ((current: CanvasItem[]) => CanvasItem[]), record = true) => {
    setItemsState((current) => {
      const value = typeof next === 'function' ? next(current) : next;
      if (record) {
        const history = historyRef.current.slice(0, historyIndexRef.current + 1);
        history.push(structuredClone(value));
        if (history.length > 60) history.shift();
        historyRef.current = history;
        historyIndexRef.current = history.length - 1;
      }
      return value;
    });
  }, []);

  const load = useCallback(async () => {
    const [projectRow, nodeRows, feedbackRows] = await Promise.all([creativeApi.get(projectId), creativeApi.nodes(projectId), creativeApi.feedback(projectId)]);
    const loaded = nodeRows.map((row) => toItem(row, feedbackRows.find((entry) => entry.node_id === row.id)));
    setProject(projectRow); setItemsState(loaded);
    historyRef.current = [structuredClone(loaded)]; historyIndexRef.current = 0;
    const [profileRow, productRow] = await Promise.all([creativeApi.learnedProfile(projectRow.product_id), productApi.get(projectRow.product_id)]);
    setProfile(profileRow); setProduct(productRow);
    if (projectRow.viewport?.zoom) setViewport({ x: projectRow.viewport.x || 0, y: projectRow.viewport.y || 0, zoom: projectRow.viewport.zoom });
  }, [projectId]);

  useEffect(() => { load().catch(() => setError('画布加载失败')); }, [load]);
  useEffect(() => {
    if (!canvasRef.current) return;
    const observer = new ResizeObserver(([entry]) => setCanvasSize({ width: entry.contentRect.width, height: entry.contentRect.height }));
    observer.observe(canvasRef.current);
    return () => observer.disconnect();
  }, []);

  const canvasPayload = useCallback((currentItems = items) => currentItems.map((item) => ({
    id: item.id, node_type: item.nodeType, parent_node_id: item.parentNodeId || null,
    position_x: item.x, position_y: item.y, width: item.width, height: item.height,
    data: { ...item.data, label: item.label, image_url: item.imageUrl },
  })), [items, viewport]);

  const save = useCallback(async (silent = false) => {
    if (!project) return;
    if (!silent) setBusy(true);
    try { await creativeApi.saveCanvas(projectId, canvasPayload(), viewport); }
    finally { if (!silent) setBusy(false); }
  }, [canvasPayload, project, projectId, viewport]);

  useEffect(() => {
    if (!project) return;
    if (saveTimer.current) window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => save(true).catch(() => undefined), 1200);
    return () => { if (saveTimer.current) window.clearTimeout(saveTimer.current); };
  }, [items, viewport, project, save]);

  const undo = useCallback(() => {
    if (historyIndexRef.current <= 0) return;
    historyIndexRef.current -= 1; setItemsState(structuredClone(historyRef.current[historyIndexRef.current])); setSelectedIds([]);
  }, []);
  const redo = useCallback(() => {
    if (historyIndexRef.current >= historyRef.current.length - 1) return;
    historyIndexRef.current += 1; setItemsState(structuredClone(historyRef.current[historyIndexRef.current])); setSelectedIds([]);
  }, []);
  const removeSelected = useCallback(() => {
    if (!selectedIds.length) return;
    commitItems((current) => current.filter((item) => !selectedIds.includes(item.id))); setSelectedIds([]);
  }, [commitItems, selectedIds]);

  useEffect(() => {
    const typing = () => ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName || '');
    const down = (event: KeyboardEvent) => {
      if (event.code === 'Space' && !typing()) { setSpacePressed(true); event.preventDefault(); }
      if (typing()) return;
      const command = event.metaKey || event.ctrlKey;
      if (command && event.key.toLowerCase() === 's') { event.preventDefault(); save(); }
      else if (command && event.key.toLowerCase() === 'z' && event.shiftKey) { event.preventDefault(); redo(); }
      else if (command && event.key.toLowerCase() === 'z') { event.preventDefault(); undo(); }
      else if (event.key === 'Delete' || event.key === 'Backspace') { event.preventDefault(); removeSelected(); }
      else if (event.key === 'Escape') setSelectedIds([]);
      else if (event.key === '0') { event.preventDefault(); setViewport({ x: 40, y: 40, zoom: 0.8 }); }
      else if (event.key === '?') setShowHelp(true);
    };
    const up = (event: KeyboardEvent) => { if (event.code === 'Space') setSpacePressed(false); };
    window.addEventListener('keydown', down); window.addEventListener('keyup', up);
    return () => { window.removeEventListener('keydown', down); window.removeEventListener('keyup', up); };
  }, [redo, removeSelected, save, undo]);

  async function generate() {
    setBusy(true); setError('');
    try {
      await creativeApi.saveCanvas(projectId, canvasPayload(), viewport);
      const parent = selected.length === 1 && ['generated', 'refined'].includes(selected[0].nodeType) ? selected[0].id : null;
      const effectivePrompt = showAdvancedPrompt ? advancedPrompt.trim() || assembledPrompt : assembledPrompt;
      const result = await creativeApi.generate(projectId, { prompt: effectivePrompt, action, selected_node_ids: selectedIds, parent_node_id: parent, auto_select_materials: autoSelectMaterials, count: action === '生成主图套系' ? 5 : 3 });
      commitItems((current) => [...current, ...result.nodes.map((row) => toItem(row))]);
      setLastGenerationBasis((result.nodes[0]?.data.context_summary || null) as GenerationBasis | null);
    } catch (err) { console.error(err); setError('生成请求未完成，请检查网络后重试；已生成结果不会丢失。'); }
    finally { setBusy(false); }
  }

  async function addReference(file: File | null) {
    if (!file) return; setBusy(true);
    try {
      const url = await productApi.uploadImage(file);
      const item: CanvasItem = { id: crypto.randomUUID().replaceAll('-', ''), nodeType: 'reference', x: 80, y: 100, width: 280, height: 320, imageUrl: url, label: file.name, data: { label: file.name, image_url: url } };
      commitItems((current) => [...current, item]); setSelectedIds([item.id]);
    } finally { setBusy(false); }
  }

  async function addReferenceFiles(files: File[]) {
    const images = files.filter((file) => file.type.startsWith('image/'));
    for (const file of images) await addReference(file);
  }

  async function submitDeliverable(file: File | null) {
    if (!file) return;
    setBusy(true); setDeliveryMessage('');
    try {
      const row = await creativeApi.submitDeliverable(projectId, file, selectedIds[0], deliveryNote);
      const item = toItem(row);
      commitItems((current) => [...current, item]);
      setSelectedIds([item.id]);
      setProject((current) => current ? { ...current, status: 'pending_review' } : current);
      setDeliveryMessage('最终设计已归档为新版本，并提交给负责人/运营审核。');
      setDeliveryNote('');
    } catch (err) {
      console.error(err); setDeliveryMessage('提交失败，请稍后重试。');
    } finally { setBusy(false); }
  }

  async function reviewSelected(status: 'usable' | 'rejected') {
    if (selected.length !== 1) return; setBusy(true);
    try {
      const row = await creativeApi.reviewNode(projectId, selected[0].id, status);
      commitItems((current) => current.map((item) => item.id === row.node_id ? { ...item, reviewStatus: row.status } : item));
    } finally { setBusy(false); }
  }

  async function markFinal() {
    if (selected.length !== 1) return; setBusy(true);
    try { const row = await creativeApi.markFinal(projectId, selected[0].id); commitItems((current) => current.map((item) => item.id === row.id ? toItem(row) : item)); }
    finally { setBusy(false); }
  }

  function arrange() {
    const columns = Math.max(2, Math.ceil(Math.sqrt(items.length)));
    commitItems(items.map((item, index) => ({ ...item, x: (index % columns) * 340 + 80, y: Math.floor(index / columns) * 400 + 80 })));
    setViewport({ x: 30, y: 30, zoom: 0.7 });
  }

  function focusSelected() {
    if (!selected.length) { setViewport({ x: 40, y: 40, zoom: 0.8 }); return; }
    const item = selected[0]; const zoom = Math.min(1.2, canvasSize.width / Math.max(item.width * 1.8, 1));
    setViewport({ x: canvasSize.width / 2 - (item.x + item.width / 2) * zoom, y: canvasSize.height / 2 - (item.y + item.height / 2) * zoom, zoom });
  }

  function focusItem(item: CanvasItem) {
    const zoom = Math.min(1.2, canvasSize.width / Math.max(item.width * 1.8, 1));
    setSelectedIds([item.id]);
    setViewport({ x: canvasSize.width / 2 - (item.x + item.width / 2) * zoom, y: canvasSize.height / 2 - (item.y + item.height / 2) * zoom, zoom });
  }

  const selectItem = (id: string, event: Konva.KonvaEventObject<MouseEvent | TouchEvent>) => {
    const native = event.evt as MouseEvent;
    setSelectedIds((current) => native.shiftKey || native.metaKey || native.ctrlKey ? current.includes(id) ? current.filter((entry) => entry !== id) : [...current, id] : [id]);
  };

  const stagePoint = () => {
    const stage = stageRef.current; const pointer = stage?.getPointerPosition();
    if (!stage || !pointer) return null;
    return { x: (pointer.x - viewport.x) / viewport.zoom, y: (pointer.y - viewport.y) / viewport.zoom };
  };

  if (!project) return <div className="h-64 grid place-items-center"><Loader2 className="animate-spin" /></div>;
  const selectedImage = selected.length === 1 ? selected[0].imageUrl : '';
  const closeWelcome = () => { setShowWelcome(false); searchParams.delete('welcome'); setSearchParams(searchParams, { replace: true }); };
  const changeWorkspaceMode = (mode: 'design' | 'expert') => { setWorkspaceMode(mode); localStorage.setItem('creative_workspace_mode', mode); setSelectedIds([]); };

  return <div className="fixed inset-0 left-60 bg-[#f4f1eb] z-10 flex flex-col text-[#242622]">
    <header className="h-16 bg-white border-b border-[#ded9cf] px-5 flex items-center justify-between gap-4">
      <div className="flex items-center gap-3"><Link to="/creative-projects"><ArrowLeft size={18} /></Link><div><div className="font-medium flex items-center gap-2">{project.name}<span className={`text-[11px] px-2 py-0.5 rounded-full ${project.status === 'pending_review' ? 'bg-amber-100 text-amber-800' : 'bg-emerald-50 text-emerald-700'}`}>{project.status === 'pending_review' ? '待审核' : '创作中'}</span></div><div className="text-xs text-[#77736b]">{project.platform} · {project.output_width}×{project.output_height}{profile ? ` · 已学习 ${profile.sample_count} 个设计选择` : ' · 正在积累品牌偏好'}</div></div></div>
      <div className="flex gap-2"><div className="flex rounded-lg bg-[#ece9e2] p-1 mr-1"><button onClick={() => changeWorkspaceMode('design')} className={`px-3 py-1.5 rounded-md text-xs ${workspaceMode === 'design' ? 'bg-white shadow-sm font-medium' : 'text-[#77736b]'}`}>设计模式</button><button onClick={() => changeWorkspaceMode('expert')} className={`px-3 py-1.5 rounded-md text-xs ${workspaceMode === 'expert' ? 'bg-white shadow-sm font-medium' : 'text-[#77736b]'}`}>专家模式</button></div><button className="btn-secondary" onClick={undo} title="撤销 ⌘Z"><Undo2 size={14} /></button><button className="btn-secondary" onClick={redo} title="重做 ⇧⌘Z"><Redo2 size={14} /></button><button className="btn-secondary" onClick={arrange}><Grid2X2 size={14} />整理</button><button className="btn-secondary" onClick={focusSelected}><Focus size={14} />聚焦</button><button className="btn-secondary" onClick={() => save()}><Save size={14} />保存</button>{workspaceMode === 'expert' && <button className="btn-secondary" onClick={() => setShowHelp(true)}><HelpCircle size={14} />快捷键</button>}</div>
    </header>

    <div className="h-12 bg-[#f9f7f2] border-b border-[#ded9cf] px-5 flex items-center gap-3 text-xs overflow-x-auto">
      <span className="font-medium text-[#4f504b] shrink-0">系统已为你准备：</span>
      <span className="rounded-full bg-white border border-[#d8d3c9] px-3 py-1.5 flex items-center gap-1.5 shrink-0"><ShieldCheck size={13} className="text-emerald-700" />{product?.name || '商品资料'}</span>
      <span className="rounded-full bg-white border border-[#d8d3c9] px-3 py-1.5 flex items-center gap-1.5 shrink-0"><BookOpen size={13} className="text-emerald-700" />{product?.brand_name || '品牌'}知识自动参与</span>
      <span className="rounded-full bg-white border border-[#d8d3c9] px-3 py-1.5 flex items-center gap-1.5 shrink-0"><Palette size={13} className="text-emerald-700" />{profile?.status === 'stable' ? `已应用稳定偏好 ${Math.round(profile.confidence * 100)}%` : '设计选择将自动学习'}</span>
    </div>

    <div className="flex-1 min-h-0 flex">
      <aside className="w-56 bg-white border-r border-[#ded9cf] flex flex-col">
        <div className="p-4 border-b border-[#eee9df]"><div className="font-medium mb-1">生成素材</div><div className="text-xs text-[#77736b]">商品原图默认全部参与，无需逐张选择。</div></div>
        <div className="flex-1 overflow-y-auto p-3 space-y-3">
          {!!productMaterials.length && <div className="text-[11px] font-medium text-[#77736b] px-1">商品原图 · 自动参与 {productMaterials.length} 张</div>}
          {productMaterials.map((item, index) => <button key={item.id} onClick={() => focusItem(item)} className={`relative w-full rounded-xl overflow-hidden border-2 text-left bg-[#f7f6f2] ${selectedIds.includes(item.id) ? 'border-[#087866]' : 'border-transparent'}`}><span className="absolute top-2 left-2 z-10 rounded-full bg-emerald-700 text-white px-2 py-0.5 text-[10px]">原图 {index + 1}</span><img src={mediaUrl(item.imageUrl || '')} className="w-full h-28 object-contain" /><div className="px-2 py-1.5 text-xs truncate">{item.label}</div></button>)}
          {!!supportingMaterials.length && <div className="text-[11px] font-medium text-[#77736b] px-1 pt-2">品牌/详情/参考素材 · 按需参与</div>}
          {supportingMaterials.map((item) => <button key={item.id} onClick={() => focusItem(item)} className={`relative w-full rounded-xl overflow-hidden border-2 text-left bg-[#f7f6f2] ${selectedIds.includes(item.id) ? 'border-[#087866]' : 'border-transparent'}`}><span className="absolute top-2 left-2 z-10 rounded-full bg-white/90 text-[#5f5c55] px-2 py-0.5 text-[10px]">{item.nodeType === 'brand_asset' ? '品牌素材' : item.nodeType === 'reference' ? '参考图' : '详情素材'}</span><img src={mediaUrl(item.imageUrl || '')} className="w-full h-28 object-contain" /><div className="px-2 py-1.5 text-xs truncate">{item.label}</div></button>)}
          {!materials.length && <div className="text-xs text-[#99958d] py-8 text-center">暂无素材</div>}
        </div>
        <div className="p-3 border-t border-[#eee9df]"><label className="btn-secondary w-full justify-center cursor-pointer"><ImagePlus size={14} />添加参考图<input type="file" accept="image/*" className="hidden" onChange={(event) => addReference(event.target.files?.[0] || null)} /></label></div>
      </aside>

      <main ref={canvasRef} className={`flex-1 min-w-0 relative overflow-hidden bg-[#ebe8e1] ${dragOver ? 'ring-4 ring-inset ring-[#087866]/40' : ''}`} style={{ backgroundImage: 'radial-gradient(#c8c3b8 1px, transparent 1px)', backgroundSize: `${24 * viewport.zoom}px ${24 * viewport.zoom}px`, backgroundPosition: `${viewport.x}px ${viewport.y}px` }} onDragOver={(event) => { event.preventDefault(); setDragOver(true); }} onDragLeave={() => setDragOver(false)} onDrop={(event) => { event.preventDefault(); setDragOver(false); void addReferenceFiles(Array.from(event.dataTransfer.files)); }}>
        {error && <div className="absolute top-4 left-1/2 -translate-x-1/2 z-30 bg-red-50 text-red-700 px-4 py-2 rounded-lg shadow">{error}</div>}
        <Stage
          ref={stageRef} width={canvasSize.width} height={canvasSize.height} x={viewport.x} y={viewport.y} scaleX={viewport.zoom} scaleY={viewport.zoom}
          draggable={workspaceMode === 'design' || spacePressed}
          onDragEnd={(event) => { if (event.target === stageRef.current) setViewport((current) => ({ ...current, x: event.target.x(), y: event.target.y() })); }}
          onWheel={(event) => {
            event.evt.preventDefault(); const stage = stageRef.current; const pointer = stage?.getPointerPosition(); if (!stage || !pointer) return;
            const oldZoom = viewport.zoom; const direction = event.evt.deltaY > 0 ? -1 : 1; const zoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, oldZoom * (direction > 0 ? 1.08 : 1 / 1.08)));
            const world = { x: (pointer.x - viewport.x) / oldZoom, y: (pointer.y - viewport.y) / oldZoom };
            setViewport({ x: pointer.x - world.x * zoom, y: pointer.y - world.y * zoom, zoom });
          }}
          onMouseDown={(event) => {
            if (workspaceMode === 'design' || event.target !== event.target.getStage() || spacePressed) return;
            const point = stagePoint(); if (!point) return; setSelectedIds([]);
            setSelectionBox({ visible: true, x: point.x, y: point.y, width: 0, height: 0, startX: point.x, startY: point.y });
          }}
          onMouseMove={() => {
            if (!selectionBox.visible) return; const point = stagePoint(); if (!point) return;
            setSelectionBox((box) => ({ ...box, x: Math.min(box.startX, point.x), y: Math.min(box.startY, point.y), width: Math.abs(point.x - box.startX), height: Math.abs(point.y - box.startY) }));
          }}
          onMouseUp={() => {
            if (!selectionBox.visible) return;
            if (selectionBox.width > 4 && selectionBox.height > 4) setSelectedIds(items.filter((item) => intersects(selectionBox, item)).map((item) => item.id));
            setSelectionBox((box) => ({ ...box, visible: false }));
          }}
        >
          <Layer>
            {workspaceMode === 'expert' && items.filter((item) => item.parentNodeId).map((item) => { const parent = items.find((entry) => entry.id === item.parentNodeId); return parent ? <Arrow key={`relation-${item.id}`} points={[parent.x + parent.width, parent.y + parent.height / 2, item.x, item.y + item.height / 2]} stroke="#8b918b" fill="#8b918b" opacity={0.55} pointerLength={8} pointerWidth={8} strokeWidth={2} listening={false} /> : null; })}
            {items.map((item) => <CanvasPicture key={item.id} item={item} selected={selectedIds.includes(item.id)} onSelect={(event) => selectItem(item.id, event)} onChange={(next) => commitItems((current) => current.map((entry) => entry.id === next.id ? next : entry))} />)}
            {selectionBox.visible && <Rect x={selectionBox.x} y={selectionBox.y} width={selectionBox.width} height={selectionBox.height} fill="rgba(8,120,102,0.12)" stroke="#087866" dash={[8, 5]} />}
          </Layer>
        </Stage>
        <div className="absolute top-4 left-4 bg-white/95 shadow-sm border border-[#ded9cf] rounded-xl px-4 py-3 text-xs text-[#5f5c55] max-w-sm"><span className="font-medium text-[#262824]">{workspaceMode === 'design' ? '设计模式：' : '专家模式：'}</span>{workspaceMode === 'design' ? '空白处直接拖动画布，拖入参考图，点击图片后在右侧生成。' : '可框选多张图片、查看生成关系，并组合多个参考进行分支探索。'}</div>
        {dragOver && <div className="absolute inset-0 z-20 bg-[#087866]/10 grid place-items-center pointer-events-none"><div className="bg-white rounded-2xl shadow-xl px-8 py-6 font-medium text-[#087866]"><ImagePlus className="mx-auto mb-2" />松开即可加入参考图片</div></div>}
        <div className="absolute bottom-4 left-4 bg-white/95 shadow rounded-lg px-3 py-2 text-xs text-[#69665f]">{workspaceMode === 'design' ? '拖动空白移动画布 · 拖动图片整理 · 滚轮缩放' : '空白处框选 · Shift 多选 · Space 拖动画布'} · {Math.round(viewport.zoom * 100)}%</div>
      </main>

      <aside className="w-80 bg-white border-l border-[#ded9cf] flex flex-col">
        <div className="p-4 border-b border-[#eee9df]"><div className="font-medium">生成视觉方案</div><div className="text-xs text-[#77736b] mt-1">先选择生成目标，系统会自动匹配正确素材。</div></div>
        <div className="p-4 space-y-4 overflow-y-auto">
          <div><label className="text-xs font-medium text-[#55534e]">1 · 想完成什么</label><button onClick={() => setAction('生成主图套系')} className={`w-full mt-2 rounded-xl border p-3 text-left ${action === '生成主图套系' ? 'border-[#087866] bg-[#edf5f2]' : 'border-[#ded9cf] hover:border-[#9ebbb1]'}`}><span className="block text-sm font-medium text-[#205f52]">一键生成主图套系</span><span className="block text-[11px] text-[#77736b] mt-1">一次生成：主封面、核心卖点、套装内容、成分质地、使用场景</span></button><div className="mt-3 text-[11px] font-medium text-[#77736b]">单张主图探索 · 每次生成 A/B/C</div><div className="grid grid-cols-2 gap-2 mt-2">{['主图·主封面', '主图·核心卖点', '主图·套装内容', '主图·成分质地', '主图·使用场景'].map((item) => <button key={item} onClick={() => setAction(item)} className={`rounded-xl border px-3 py-2.5 text-xs text-left ${action === item ? 'border-[#087866] bg-[#edf5f2] text-[#086c5c]' : 'border-[#ded9cf] hover:border-[#9ebbb1]'}`}>{item.replace('主图·', '')}</button>)}</div><div className="mt-3 text-[11px] font-medium text-[#77736b]">详情页模块 · 每次生成 A/B/C</div><div className="grid grid-cols-2 gap-2 mt-2">{['详情页·首屏', '详情页·核心卖点', '详情页·成分功效', '详情页·使用场景', '详情页·使用方法'].map((item) => <button key={item} onClick={() => setAction(item)} className={`rounded-xl border px-3 py-2.5 text-xs text-left ${action === item ? 'border-[#087866] bg-[#edf5f2] text-[#086c5c]' : 'border-[#ded9cf] hover:border-[#9ebbb1]'}`}>{item.replace('详情页·', '')}</button>)}</div></div>
          <div className="rounded-xl bg-[#f4f7f5] border border-[#dce9e4] p-3"><label className="flex items-start gap-2 cursor-pointer"><input type="checkbox" className="mt-0.5" checked={autoSelectMaterials} onChange={(event) => setAutoSelectMaterials(event.target.checked)} /><span><span className="block text-xs font-medium text-[#315e54]">自动匹配生成素材（推荐）</span><span className="block text-[11px] leading-4 text-[#6d7d77] mt-1">{action.startsWith('详情页') ? `自动使用全部商品原图，并优先加入已定稿主图；选中的图片作为额外参考。` : `自动使用全部 ${productMaterials.length} 张商品原图；选中的图片仅作为额外参考。`}</span></span></label></div>
          <div><label className="text-xs font-medium text-[#55534e]">2 · 选择视觉方向</label><div className="mt-2 space-y-3">{Object.entries(VISUAL_OPTIONS).map(([group, options]) => <div key={group}><div className="text-[11px] text-[#88847c] mb-1.5">{group}</div><div className="flex flex-wrap gap-1.5">{options.map((option) => <button key={option} type="button" onClick={() => setVisualTags((current) => current.includes(option) ? current.filter((item) => item !== option) : [...current, option])} className={`rounded-full border px-2.5 py-1.5 text-[11px] ${visualTags.includes(option) ? 'border-[#087866] bg-[#e8f2ef] text-[#086c5c]' : 'border-[#ded9cf] bg-white text-[#66635d]'}`}>{option}</button>)}</div></div>)}</div></div>
          <div><label className="text-xs font-medium text-[#55534e]">3 · 还有什么需要调整？（可选）</label><textarea className="input w-full mt-2 min-h-20 resize-none" value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="例如：商品再大一点，不要太绿，背景更干净" /></div>
          <div className="rounded-xl border border-[#ded9cf] overflow-hidden"><button type="button" className="w-full px-3 py-2.5 flex items-center justify-between text-xs font-medium text-left" onClick={() => { if (!showAdvancedPrompt) setAdvancedPrompt(assembledPrompt); setShowAdvancedPrompt((current) => !current); }}><span>高级 Prompt 模式</span><span className="text-[#77736b]">{showAdvancedPrompt ? '收起' : '查看并编辑'}</span></button>{showAdvancedPrompt && <div className="border-t border-[#eee9df] p-3"><textarea className="input w-full min-h-36 resize-y font-mono text-[11px] leading-5" value={advancedPrompt} onChange={(event) => setAdvancedPrompt(event.target.value)} /><div className="flex justify-between mt-2 text-[10px] text-[#88847c]"><span>直接修改后将优先使用此 Prompt</span><button type="button" className="text-[#087866]" onClick={() => setAdvancedPrompt(assembledPrompt)}>按当前选项重新生成</button></div></div>}</div>
          <button className="btn-primary w-full justify-center py-3" disabled={busy} onClick={generate}>{busy ? <Loader2 size={16} className="animate-spin" /> : <Sparkles size={16} />}4 · {action === '生成主图套系' ? '生成 5 张主图套系' : '生成 3 个候选方案'}</button>{busy && <div className="rounded-lg bg-blue-50 px-3 py-2 text-[11px] leading-5 text-blue-700">Seedream 正在逐张生成。单张通常需要约30–60秒，主图套系可能需要3–5分钟，请不要重复点击或关闭页面。</div>}
          <div className="text-xs text-[#77736b] text-center">{autoSelectMaterials ? `系统自动使用 ${productMaterials.length} 张商品原图${selected.length ? `，另加 ${selected.length} 张手动参考` : ''}` : `手动模式：已选择 ${selected.length} 张图`}</div>
          {lastGenerationBasis && <div className="rounded-xl border border-[#ded9cf] bg-[#faf9f6] p-3 text-xs"><div className="font-medium mb-2">本次生成依据</div><div className="text-[#77736b] leading-5">{lastGenerationBasis.material_strategy}</div><div className="mt-2 flex flex-wrap gap-1">{lastGenerationBasis.materials?.map((item) => <span key={item.id} className="rounded-full bg-white border px-2 py-1">{item.label || item.type}</span>)}</div>{!!lastGenerationBasis.brand_documents?.length && <div className="mt-2 text-[#66635d]">品牌知识：{lastGenerationBasis.brand_documents.map((item) => item.title).join('、')}</div>}{!!lastGenerationBasis.skills?.length && <div className="mt-1 text-[#66635d]">设计 Skill：{lastGenerationBasis.skills.map((item) => item.name).join('、')}</div>}</div>}
          <div className="border-t border-[#eee9df] pt-4"><div className="text-sm font-medium mb-3">当前选择</div>{selected.length === 1 ? <><div className="rounded-xl bg-[#f5f3ee] overflow-hidden"><img src={mediaUrl(selected[0].imageUrl || '')} className="w-full h-44 object-contain" /><div className="p-2 text-xs truncate">{selected[0].label}</div></div><div className="mt-3"><div className="text-[11px] text-[#88847c] mb-1.5">基于当前图片快捷修改</div><div className="flex flex-wrap gap-1.5">{['商品放大', '背景简化', '更高级', '减少文字', '光线柔和', '换一种构图'].map((instruction) => <button key={instruction} type="button" className="rounded-full bg-[#f0eee8] px-2.5 py-1.5 text-[11px] hover:bg-[#e2eee9]" onClick={() => setPrompt(instruction)}>{instruction}</button>)}</div></div><div className="grid grid-cols-2 gap-2 mt-3"><button className="btn-secondary justify-center" onClick={() => reviewSelected('usable')}><Check size={14} />采用</button><button className="btn-secondary justify-center" onClick={() => reviewSelected('rejected')}><X size={14} />不合适</button><button className="btn-secondary justify-center" onClick={markFinal}><Award size={14} />定稿</button>{selectedImage && <a className="btn-secondary justify-center" href={mediaUrl(selectedImage)} download><Download size={14} />下载</a>}<button className="btn-secondary justify-center col-span-2 text-red-600" onClick={removeSelected}><Trash2 size={14} />移出画布</button></div></> : <div className="text-xs text-[#99958d] rounded-xl bg-[#f7f6f2] p-5 text-center">点击一张图片进行操作<br />Shift 可多选作为生成参考</div>}</div>
          {results.length > 0 && <div className="text-xs text-[#77736b]">当前项目已有 {results.length} 个生成/精修方案。</div>}
          <div className="border-t border-[#ded9cf] pt-5 mt-5"><div className="flex items-center gap-2 font-medium"><Upload size={16} className="text-[#087866]" />完成设计并交付</div><p className="text-xs text-[#77736b] leading-5 mt-1">从 Photoshop/Figma 导出后在这里提交。系统会自动归档版本、标记交付稿并通知后续审核。</p><textarea className="input w-full mt-3 min-h-20 resize-none" value={deliveryNote} onChange={(event) => setDeliveryNote(event.target.value)} placeholder="交付说明（可选），例如：已完成包装文字修正和光影精修" /><label className="btn-primary w-full justify-center cursor-pointer mt-3 py-3"><Award size={15} />提交最终设计<input type="file" accept="image/*" className="hidden" onChange={(event) => submitDeliverable(event.target.files?.[0] || null)} /></label>{deliveryMessage && <div className={`mt-3 rounded-lg px-3 py-2 text-xs ${deliveryMessage.includes('失败') ? 'bg-red-50 text-red-700' : 'bg-emerald-50 text-emerald-800'}`}>{deliveryMessage}</div>}</div>
        </div>
      </aside>
    </div>

    {showWelcome && <div className="absolute inset-0 z-50 bg-black/35 grid place-items-center p-6"><div className="bg-white rounded-3xl shadow-2xl w-[620px] max-w-full overflow-hidden"><div className="bg-[#0b7563] text-white p-7"><div className="text-xs opacity-75 mb-2">项目已准备完成</div><div className="text-2xl font-medium">不用从空白画布开始</div><p className="text-sm opacity-85 mt-2">商品、品牌和已有设计偏好已经自动进入本次任务。</p></div><div className="p-7"><div className="grid grid-cols-3 gap-4">{[[ShieldCheck, '选主体', '点击商品图；不选时默认使用主图'], [ImagePlus, '加参考', '需要时添加风格、构图或场景参考'], [Sparkles, '出方案', '描述效果，生成后采用、淘汰或继续调整']].map(([Icon, title, description]) => { const StepIcon = Icon as typeof ShieldCheck; return <div key={String(title)} className="rounded-2xl bg-[#f5f3ee] p-4"><StepIcon size={21} className="text-[#087866] mb-3" /><div className="font-medium text-sm">{String(title)}</div><div className="text-xs text-[#77736b] leading-5 mt-1">{String(description)}</div></div>; })}</div><div className="mt-5 rounded-xl bg-amber-50 text-amber-800 px-4 py-3 text-xs">当前使用本地视觉草案合成验证工作流；接入正式生图模型后，换背景、场景生成和方案变体会输出真正的AI视觉结果。</div><button className="btn-primary w-full justify-center py-3 mt-5" onClick={closeWelcome}>开始设计</button></div></div></div>}

    {showHelp && <div className="absolute inset-0 z-50 bg-black/30 grid place-items-center" onClick={() => setShowHelp(false)}><div className="bg-white rounded-2xl shadow-xl w-[460px] p-6" onClick={(event) => event.stopPropagation()}><div className="flex justify-between items-center mb-5"><div><div className="text-lg font-medium">画布辅助操作</div><div className="text-xs text-[#77736b] mt-1">不记快捷键也能完成主要流程</div></div><button onClick={() => setShowHelp(false)}><X size={18} /></button></div><div className="grid grid-cols-2 gap-x-8 gap-y-3 text-sm">{[['Space', '拖动画布'], ['滚轮', '以鼠标为中心缩放'], ['Shift + 点击', '多选图片'], ['拖动空白', '框选图片'], ['⌘/Ctrl + Z', '撤销'], ['⇧⌘/Ctrl + Z', '重做'], ['⌘/Ctrl + S', '立即保存'], ['Delete', '移出画布'], ['Esc', '取消选择'], ['0', '重置视图'], ['?', '打开帮助'], ['点击左侧素材', '快速定位']].map(([key, value]) => <div key={key} className="contents"><kbd className="bg-[#f1efe9] rounded px-2 py-1 text-xs">{key}</kbd><span>{value}</span></div>)}</div></div></div>}
  </div>;
}
