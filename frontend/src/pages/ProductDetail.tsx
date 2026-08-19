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
import { generationApi, mediaUrl, productApi } from '../api/client';
import type { GenerationListItem, Product, ProductAsset } from '../types';

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
  const [assetType, setAssetType] = useState('product_image');
  const [assetDescription, setAssetDescription] = useState('');
  const [uploadingAsset, setUploadingAsset] = useState(false);

  async function load() {
    const [p, g, a] = await Promise.all([
      productApi.get(productId),
      generationApi.list(productId),
      productApi.listAssets(productId),
    ]);
    setProduct(p);
    setGens(g);
    setAssets(a);
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
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {assets.map((asset) => (
                <a key={asset.id} href={mediaUrl(asset.file_url)} target="_blank" rel="noreferrer" className="rounded-lg border border-[var(--border)] p-3 hover:bg-[var(--bg-elevated)]">
                  <div className="text-sm font-medium truncate">{asset.name}</div>
                  <div className="text-xs text-[var(--muted)]">{asset.asset_type} · {asset.description || '无说明'}</div>
                </a>
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
