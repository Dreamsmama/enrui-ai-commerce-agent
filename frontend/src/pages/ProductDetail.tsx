import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import {
  ArrowLeft,
  Loader2,
  Trash2,
  Wand2,
  Image as ImageIcon,
  CheckCircle2,
  XCircle,
  Clock,
  Upload,
  FileText,
} from 'lucide-react';
import { generationApi, mediaUrl, operationsApi, productApi, productionApi } from '../api/client';
import type { GenerationListItem, Product, ProductAsset } from '../types';
import MaskEditorModal from '../components/MaskEditorModal';
import ProtectionRegionEditor from '../components/ProtectionRegionEditor';

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { cls: string; icon: typeof Clock; label: string }> = {
    completed: { cls: 'badge-ok', icon: CheckCircle2, label: '已完成' },
    failed: { cls: 'badge-err', icon: XCircle, label: '失败' },
    running: { cls: 'badge-run', icon: Loader2, label: '生成中' },
    pending: { cls: 'badge-wait', icon: Clock, label: '排队中' },
  };
  const conf = map[status] || map.pending;
  const Icon = conf.icon;
  return (
    <span className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full ${conf.cls}`}>
      <Icon size={12} className={status === 'running' || status === 'pending' ? 'animate-spin' : ''} />
      {conf.label}
    </span>
  );
}

export default function ProductDetail() {
  const { id } = useParams();
  const productId = Number(id);
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  const [product, setProduct] = useState<Product | null>(null);
  const [gens, setGens] = useState<GenerationListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState('');
  const [assets, setAssets] = useState<ProductAsset[]>([]);
  const [maskEditing,setMaskEditing]=useState<ProductAsset|null>(null);
  const [regionEditing,setRegionEditing]=useState<ProductAsset|null>(null);
  const [assetType, setAssetType] = useState('product_image');
  const [assetDescription, setAssetDescription] = useState('');
  const [uploadingAsset, setUploadingAsset] = useState(false);
  const [readiness, setReadiness] = useState<{score:number;status:string;items:Array<{key:string;label:string;complete:boolean;required:boolean}>;missing_required:string[]} | null>(null);
  const [facts,setFacts]=useState<Array<{id:number;fact_key:string;label:string;value:string;source_type:string;source_ref:string;status:string;conflict_values:string[]}>>([]);
  const [admission,setAdmission]=useState<{status:string;missing_roles:string[];images:Array<{label:string;inspection:{status:string;score:number;issues:string[]}}> }|null>(null);

  async function load() {
    const [p, g, a, ready, factRows,admissionRow] = await Promise.all([
      productApi.get(productId),
      generationApi.list(productId),
      productApi.listAssets(productId),
      operationsApi.readiness(productId),
      productionApi.facts(productId),
      operationsApi.imageAdmission(productId),
    ]);
    setProduct(p);
    setGens(g);
    setAssets(a);
    setReadiness(ready);
    setFacts(factRows);
    setAdmission(admissionRow);
  }

  useEffect(() => {
    if (!productId) return;
    (async () => {
      try {
        await load();
      } catch (e) {
        console.error(e);
        setError('加载失败');
      } finally {
        setLoading(false);
      }
    })();
  }, [productId]);

  useEffect(() => {
    if (!product || searchParams.get('autogen') !== '1') return;
    void startGenerate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [product?.id]);

  async function startGenerate() {
    if (generating) return;
    if (readiness?.status === 'blocked' && !confirm(`商品资料缺少：${readiness.missing_required.join('、')}。继续生成可能产生不准确结果，仍要继续吗？`)) return;
    setGenerating(true);
    setError('');
    try {
      const gen = await generationApi.start(productId);
      navigate(`/generations/${gen.id}`);
    } catch (e) {
      console.error(e);
      setError('启动生成失败，请检查 LLM API 配置');
      setGenerating(false);
    }
  }

  async function handleDelete() {
    if (!confirm('确定删除该商品及其所有生成记录？')) return;
    await productApi.remove(productId);
    navigate('/');
  }

  async function toggleLearnedProfile() {
    const updated = await productApi.update(productId, { learned_profile_enabled: !product.learned_profile_enabled });
    setProduct(updated);
  }

  async function uploadAssets(files: FileList | null) {
    if (!files?.length) return;
    setUploadingAsset(true);
    setError('');
    try {
      await productApi.uploadAssets(productId, Array.from(files), {
        asset_type: assetType,
        description: assetDescription,
      });
      setAssets(await productApi.listAssets(productId));
      setAssetDescription('');
    } catch (e) {
      console.error(e);
      setError('素材上传失败');
    } finally {
      setUploadingAsset(false);
    }
  }

  async function updateAsset(asset: ProductAsset, values: Partial<ProductAsset>) {
    const next = { ...asset, ...values };
    setAssets((current) => current.map((item) => item.id === asset.id ? next : item));
    try {
      const saved = await productApi.updateAsset(productId, asset.id, { description: next.description, tags: next.tags, material_role: next.material_role, priority: next.priority, locked: next.locked, excluded: next.excluded, benchmark_role: next.benchmark_role, protection:next.protection||{} });
      setAssets((current) => current.map((item) => item.id === saved.id ? saved : item));
    } catch (e) {
      console.error(e); setError(`${asset.name}设置保存失败`); setAssets((current) => current.map((item) => item.id === asset.id ? asset : item));
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-[var(--muted)]">
        <Loader2 className="animate-spin mr-2" size={20} /> 加载中…
      </div>
    );
  }

  if (!product) {
    return <div className="text-[var(--muted)]">商品不存在</div>;
  }

  const allImages = [...(product.image_urls || []), ...(product.detail_image_urls || [])];

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center gap-3 text-sm text-[var(--muted)]">
        <Link to="/" className="inline-flex items-center gap-1 hover:text-[var(--text)]">
          <ArrowLeft size={16} /> 返回
        </Link>
      </div>

      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl tracking-tight">{product.name}</h1>
          <p className="mt-1 text-sm text-[var(--muted)]">
            {product.category || '未分类'} · ¥{product.price} · 目标用户：{product.target_users || '未指定'}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            className="btn-primary inline-flex items-center gap-2"
            onClick={startGenerate}
            disabled={generating}
          >
            {generating ? <Loader2 className="animate-spin" size={16} /> : <Wand2 size={16} />}
            启动 Agent 生成
          </button>
          <button className="btn-secondary" onClick={toggleLearnedProfile}>
            自动学习画像：{product.learned_profile_enabled ? '已启用' : '已关闭'}
          </button>
          <button className="btn-danger inline-flex items-center gap-2" onClick={handleDelete}>
            <Trash2 size={16} /> 删除
          </button>
        </div>
      </header>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 text-red-700 px-4 py-3 text-sm">
          {error}
        </div>
      )}
      {readiness && <section className={`panel p-4 ${readiness.status === 'ready' ? 'border-emerald-200' : 'border-amber-300'}`}><div className="flex items-center justify-between"><div><div className="font-medium">生成前资料完整度</div><div className="text-xs text-[var(--muted)] mt-1">必填资料完成 {readiness.score}%</div></div><span className={`text-sm font-medium ${readiness.status === 'ready' ? 'text-emerald-700' : 'text-amber-700'}`}>{readiness.status === 'ready' ? '可以生成' : '建议补充'}</span></div><div className="flex flex-wrap gap-2 mt-3">{readiness.items.map(item=><span key={item.key} className={`rounded-full px-2.5 py-1 text-xs ${item.complete?'bg-emerald-50 text-emerald-800':'bg-amber-50 text-amber-800'}`}>{item.complete?'✓':'!'} {item.label}{item.required?' · 必填':''}</span>)}</div></section>}
      {admission&&<section className="panel p-4"><div className="font-medium">商品原图准入检查</div><div className="grid md:grid-cols-3 gap-2 mt-3">{admission.images.map((x,i)=><div className={`rounded-lg p-3 text-xs ${x.inspection.status==='passed'?'bg-emerald-50':'bg-amber-50'}`} key={i}><b>{x.label} · {x.inspection.score}分</b><div className="mt-1">{x.inspection.issues.join('、')||'清晰度和画幅通过'}</div></div>)}</div>{admission.missing_roles.length>0&&<div className="text-xs text-amber-800 mt-3">建议补充基准图：{admission.missing_roles.join('、')}</div>}</section>}
      <section className="panel p-5"><div className="flex justify-between"><div><h2 className="font-medium">商品事实中心</h2><p className="text-xs text-[var(--muted)] mt-1">生成只使用已确认事实；冲突内容必须人工选择。</p></div></div><div className="grid md:grid-cols-2 gap-3 mt-4">{facts.map(f=><div key={f.id} className={`rounded-xl border p-4 ${f.status==='confirmed'?'border-emerald-200':f.status==='conflict'?'border-red-300 bg-red-50/30':'border-amber-200'}`}><div className="flex justify-between"><b className="text-sm">{f.label}</b><span className="text-xs">{f.status==='confirmed'?'已确认':f.status==='conflict'?'存在冲突':'待确认'}</span></div><p className="text-sm mt-2 whitespace-pre-wrap">{f.value||'尚未填写'}</p><div className="text-[10px] text-[var(--muted)] mt-2">来源：{f.source_type} {f.source_ref}</div>{f.conflict_values?.length>0&&<div className="mt-2 text-xs text-red-700">冲突值：{f.conflict_values.join(' / ')}</div>}<div className="flex gap-2 mt-3"><button className="btn-secondary text-xs" onClick={async()=>{const value=prompt(`修改${f.label}`,f.value);if(value===null)return;await productionApi.saveFact(productId,{fact_key:f.fact_key,label:f.label,value,source_type:'manual',source_ref:'人工编辑'});setFacts(await productionApi.facts(productId))}}>编辑</button>{f.status!=='confirmed'&&<button className="btn-primary text-xs" onClick={async()=>{await productionApi.confirmFact(productId,f.id,f.value);setFacts(await productionApi.facts(productId))}}>确认作为正式事实</button>}</div></div>)}</div></section>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 panel p-6 space-y-4">
          <h2 className="font-medium">商品描述</h2>
          <p className="text-sm leading-relaxed whitespace-pre-wrap text-[var(--text)]/90">
            {product.description || '暂无描述'}
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
            <InfoBlock label="品牌" value={product.brand_name} />
            <InfoBlock label="规格" value={product.specifications} />
            <InfoBlock label="核心成分" value={product.ingredients} />
            <InfoBlock label="使用方法" value={product.usage_method} />
          </div>

          {allImages.length > 0 && (
            <>
              <h2 className="font-medium pt-2 flex items-center gap-2">
                <ImageIcon size={16} /> 图片素材
              </h2>
              <div className="flex flex-wrap gap-3">
                {allImages.map((url, i) => (
                  <img
                    key={`${url}-${i}`}
                    src={mediaUrl(url)}
                    alt=""
                    className="w-28 h-28 object-cover rounded-lg border border-[var(--border)]"
                  />
                ))}
              </div>
            </>
          )}

          <div className="border-t border-[var(--border)] pt-4 space-y-3">
            <h2 className="font-medium flex items-center gap-2"><FileText size={16} /> 商品 / 品牌素材库</h2>
            <div className="grid grid-cols-1 sm:grid-cols-[180px_1fr_auto] gap-2">
              <select className="input-select" value={assetType} onChange={(e) => setAssetType(e.target.value)}>
                <option value="product_image">产品图片</option>
                <option value="brand_asset">品牌素材</option>
                <option value="certificate">证书</option>
                <option value="test_report">检测报告</option>
                <option value="design_skill">设计方法论 / Skill</option>
              </select>
              <input className="input" value={assetDescription} onChange={(e) => setAssetDescription(e.target.value)} placeholder="素材说明，便于 Agent 理解和调用" />
              <label className="btn-primary inline-flex items-center justify-center gap-2 cursor-pointer">
                {uploadingAsset ? <Loader2 className="animate-spin" size={14} /> : <Upload size={14} />}
                上传
                <input type="file" multiple className="hidden" onChange={(e) => uploadAssets(e.target.files)} />
              </label>
            </div>
            <p className="text-xs text-[var(--muted)]">上传后可纠正 AI 识别结果；锁定表示生成必须使用，排除表示永不参与自动选择。</p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {assets.length === 0 && <div className="sm:col-span-2 rounded-xl border border-dashed border-[var(--border)] p-8 text-center text-sm text-[var(--muted)]">暂未上传素材；后续测试时可在这里直接上传并设置角色。</div>}
              {assets.map((asset) => (
                <div key={asset.id} className={`rounded-xl border p-3 ${asset.excluded ? 'border-red-200 bg-red-50/50 opacity-70' : asset.locked ? 'border-emerald-300 bg-emerald-50/40' : 'border-[var(--border)]'}`}>
                  <div className="flex gap-3">{asset.mime_type.startsWith('image/') ? <a href={mediaUrl(asset.file_url)} target="_blank" rel="noreferrer"><img src={mediaUrl(asset.file_url)} className="w-20 h-20 rounded-lg object-cover border border-[var(--border)]" /></a> : <div className="w-20 h-20 rounded-lg bg-[#f1efe9] grid place-items-center"><FileText size={20} /></div>}<div className="min-w-0 flex-1"><div className="text-sm font-medium truncate">{asset.name}</div><div className="text-[10px] text-[var(--muted)] mt-1">{asset.description || '无说明'}</div><select className="input-select w-full mt-2 text-xs" value={asset.material_role || 'auto'} onChange={(event) => updateAsset(asset, { material_role: event.target.value })}><option value="auto">AI 自动识别</option><option value="product">商品正面图</option><option value="package">套装/礼盒图</option><option value="detail">侧面/细节图</option><option value="texture">质地微距</option><option value="scenario">使用场景</option><option value="ingredient">成分素材</option><option value="logo">品牌 Logo</option><option value="brand">品牌视觉素材</option><option value="reference">设计参考图</option></select></div></div>
                  <div className="flex items-center justify-between mt-3 text-xs"><label className="flex items-center gap-1.5"><input type="checkbox" checked={asset.locked} disabled={asset.excluded} onChange={(event) => updateAsset(asset, { locked: event.target.checked })} />锁定使用</label><label className="flex items-center gap-1.5 text-red-700"><input type="checkbox" checked={asset.excluded} onChange={(event) => updateAsset(asset, { excluded: event.target.checked, locked: event.target.checked ? false : asset.locked })} />排除素材</label><label className="flex items-center gap-1">优先级<input type="number" min="0" max="9" className="w-12 rounded border border-[var(--border)] px-1 py-0.5" value={asset.priority} onChange={(event) => updateAsset(asset, { priority: Number(event.target.value) })} /></label></div>
                  {asset.mime_type.startsWith('image/')&&<button className="btn-secondary w-full justify-center mt-3" onClick={()=>setMaskEditing(asset)}>在线画笔编辑商品蒙版</button>}
                  {asset.mime_type.startsWith('image/')&&<button className="btn-secondary w-full justify-center mt-2" onClick={()=>setRegionEditing(asset)}>可视化编辑Logo/文字保护区</button>}
                  {asset.mime_type.startsWith('image/') && <label className="block text-xs mt-3">质检基准用途<select className="input-select w-full mt-1" value={asset.benchmark_role || 'none'} onChange={(event)=>updateAsset(asset,{benchmark_role:event.target.value})}><option value="none">不是基准图</option><option value="product_front">商品正面标准图</option><option value="package">包装标准图</option><option value="set_composition">套装组成标准图</option><option value="color">包装颜色标准图</option></select></label>}
                  {asset.mime_type.startsWith('image/')&&<div className="mt-3 rounded-lg bg-[var(--bg-elevated)] p-2"><div className="text-[10px] text-[var(--muted)]">商品保护：{asset.protection?.mask_url?`${asset.protection.mask_source==='manual'?'人工':'自动'}蒙版`:'未设置蒙版'} · Logo/文字区 {asset.protection?.protected_regions?.length||0}</div><div className="flex flex-wrap gap-1.5 mt-2"><button className="btn-secondary text-[10px]" onClick={async()=>{const saved=await productApi.autoMask(productId,asset.id);setAssets(current=>current.map(item=>item.id===saved.id?saved:item))}}>生成商品蒙版</button><button className="btn-secondary text-[10px]" onClick={async()=>{try{const saved=await productApi.analyzeProtection(productId,asset.id);setAssets(current=>current.map(item=>item.id===saved.id?saved:item))}catch(e){setError('保护区识别失败，请确认真实视觉模型已配置')}}}>识别Logo/文字保护区</button><label className="btn-secondary text-[10px] cursor-pointer">上传人工蒙版<input type="file" accept="image/*" className="hidden" onChange={async e=>{const file=e.target.files?.[0];if(!file)return;const saved=await productApi.uploadMask(productId,asset.id,file);setAssets(current=>current.map(item=>item.id===saved.id?saved:item))}}/></label></div>{asset.protection?.position&&<div className="grid grid-cols-2 gap-2 mt-2 text-[10px]"><label>缩放<input type="range" min="0.2" max="1" step="0.02" value={asset.protection.position.scale} onChange={e=>updateAsset(asset,{protection:{...asset.protection,position:{...asset.protection.position!,scale:Number(e.target.value)}}})}/></label><label>旋转<input type="range" min="-180" max="180" value={asset.protection.position.rotation} onChange={e=>updateAsset(asset,{protection:{...asset.protection,position:{...asset.protection.position!,rotation:Number(e.target.value)}}})}/></label></div>}</div>}
                  {asset.protection?.position&&<div className="grid grid-cols-2 gap-2 mt-2 text-[10px]"><label>水平位置<input type="range" min="0" max="1" step="0.01" value={asset.protection.position.x} onChange={e=>updateAsset(asset,{protection:{...asset.protection,position:{...asset.protection.position!,x:Number(e.target.value)}}})}/></label><label>垂直位置<input type="range" min="0" max="1" step="0.01" value={asset.protection.position.y} onChange={e=>updateAsset(asset,{protection:{...asset.protection,position:{...asset.protection.position!,y:Number(e.target.value)}}})}/></label><label><input type="checkbox" checked={Boolean(asset.protection.preserve_shadow)} onChange={e=>updateAsset(asset,{protection:{...asset.protection,preserve_shadow:e.target.checked}})}/>保留原阴影</label><label><input type="checkbox" checked={Boolean(asset.protection.preserve_reflection)} onChange={e=>updateAsset(asset,{protection:{...asset.protection,preserve_reflection:e.target.checked}})}/>保留原倒影</label><button className="btn-secondary col-span-2" onClick={()=>updateAsset(asset,{protection:{...asset.protection,position:{x:.5,y:.5,scale:.72,rotation:0}}})}>恢复默认位置</button></div>}
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">
            <h2 className="font-medium">生成记录</h2>
          </div>
          <div className="divide-y divide-[var(--border)]">
            {gens.length === 0 && (
              <div className="px-5 py-8 text-center text-sm text-[var(--muted)]">
                尚无生成记录
              </div>
            )}
            {gens.map((g) => (
              <Link
                key={g.id}
                to={`/generations/${g.id}`}
                className="flex items-center justify-between px-5 py-3 hover:bg-[var(--bg-elevated)]"
              >
                <div>
                  <div className="text-sm font-medium">#{g.id}</div>
                  <div className="text-xs text-[var(--muted)]">
                    {new Date(g.created_at).toLocaleString()}
                  </div>
                </div>
                <StatusBadge status={g.status} />
              </Link>
            ))}
          </div>
        </div>
      </div>
      {maskEditing&&<MaskEditorModal imageUrl={mediaUrl(maskEditing.file_url)} maskUrl={maskEditing.protection?.mask_url?mediaUrl(maskEditing.protection.mask_url):undefined} onClose={()=>setMaskEditing(null)} onSave={async file=>{const saved=await productApi.uploadMask(productId,maskEditing.id,file);setAssets(current=>current.map(item=>item.id===saved.id?saved:item));setMaskEditing(null)}}/>}
      {regionEditing&&<ProtectionRegionEditor imageUrl={mediaUrl(regionEditing.file_url)} initial={regionEditing.protection?.protected_regions||[]} onClose={()=>setRegionEditing(null)} onSave={async regions=>{await updateAsset(regionEditing,{protection:{...regionEditing.protection,protected_regions:regions}});setRegionEditing(null)}}/>}
    </div>
  );
}

function InfoBlock({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-[var(--bg-elevated)] p-3">
      <div className="text-xs text-[var(--muted)] mb-1">{label}</div>
      <div className="whitespace-pre-wrap">{value || '未填写'}</div>
    </div>
  );
}
