import { useEffect, useState, type FormEvent } from 'react';
import { BookOpen, Loader2, Trash2, Upload } from 'lucide-react';
import { knowledgeApi, productApi } from '../api/client';
import type { KnowledgeDoc, Product } from '../types';

const DOC_TYPES = [
  { value: 'product_manual', label: '产品说明书' },
  { value: 'brand_material', label: '品牌资料' },
  { value: 'historical_detail', label: '历史详情页' },
  { value: 'general', label: '通用资料' },
];

export default function KnowledgePage() {
  const [docs, setDocs] = useState<KnowledgeDoc[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const [title, setTitle] = useState('');
  const [docType, setDocType] = useState('product_manual');
  const [content, setContent] = useState('');
  const [productId, setProductId] = useState<string>('');
  const [brandName, setBrandName] = useState('');

  async function load() {
    const [d, p] = await Promise.all([knowledgeApi.list(), productApi.list()]);
    setDocs(d);
    setProducts(p);
  }

  useEffect(() => {
    (async () => {
      try {
        await load();
      } catch (e) {
        console.error(e);
        setError('加载知识库失败');
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!title.trim() || !content.trim()) {
      setError('请填写标题与内容');
      return;
    }
    setSaving(true);
    setError('');
    try {
      await knowledgeApi.create({
        title: title.trim(),
        doc_type: docType,
        content: content.trim(),
        product_id: productId ? Number(productId) : null,
        brand_name: brandName.trim(),
      });
      setTitle('');
      setContent('');
      await load();
    } catch (err) {
      console.error(err);
      setError('保存失败（嵌入向量需要可用的 Embedding API）');
    } finally {
      setSaving(false);
    }
  }

  async function onUpload(file: File | null) {
    if (!file) return;
    setSaving(true);
    setError('');
    try {
      await knowledgeApi.upload(file, {
        title: file.name,
        doc_type: docType,
        product_id: productId ? Number(productId) : undefined,
        brand_name: brandName.trim(),
      });
      await load();
    } catch (err) {
      console.error(err);
      setError('上传失败');
    } finally {
      setSaving(false);
    }
  }

  async function remove(id: number) {
    if (!confirm('删除该知识库文档？')) return;
    await knowledgeApi.remove(id);
    await load();
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-[var(--muted)]">
        <Loader2 className="animate-spin mr-2" size={20} /> 加载中…
      </div>
    );
  }

  return (
    <div className="space-y-6 animate-fade-in">
      <header>
        <h1 className="font-display text-3xl tracking-tight">商品知识库</h1>
        <p className="mt-1 text-sm text-[var(--muted)]">
          上传说明书 / 品牌资料 / 历史详情页，文本切片 + Embedding 向量检索，生成时自动引用
        </p>
      </header>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 text-red-700 px-4 py-3 text-sm">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <form className="panel p-6 space-y-4" onSubmit={onSubmit}>
          <h2 className="font-medium flex items-center gap-2">
            <BookOpen size={18} /> 添加知识文档
          </h2>
          <label className="field">
            <span>标题</span>
            <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="例如：XX保温杯产品说明书" />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="field">
              <span>文档类型</span>
              <select className="input-select" value={docType} onChange={(e) => setDocType(e.target.value)}>
                {DOC_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>关联商品（可选）</span>
              <select className="input-select" value={productId} onChange={(e) => setProductId(e.target.value)}>
                <option value="">全局知识库</option>
                {products.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <label className="field">
            <span>关联品牌（品牌资料建议填写）</span>
            <input value={brandName} onChange={(e) => setBrandName(e.target.value)} placeholder="例如：百雀羚；同品牌商品生成时自动继承" />
          </label>
          <label className="field">
            <span>文本内容</span>
            <textarea
              rows={8}
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder="粘贴产品规格、品牌故事、历史详情页文案…"
            />
          </label>
          <div className="flex flex-wrap gap-3">
            <button type="submit" className="btn-primary" disabled={saving}>
              {saving ? <Loader2 className="animate-spin" size={16} /> : null}
              切片并入库
            </button>
            <label className="btn-secondary inline-flex items-center gap-2 cursor-pointer">
              <Upload size={16} />
              上传文件
              <input
                type="file"
                accept=".txt,.md,.csv,.json,.log"
                className="hidden"
                onChange={(e) => onUpload(e.target.files?.[0] || null)}
              />
            </label>
          </div>
        </form>

        <div className="panel overflow-hidden">
          <div className="panel-header">
            <h2 className="font-medium">已入库文档（{docs.length}）</h2>
          </div>
          <div className="divide-y divide-[var(--border)] max-h-[560px] overflow-auto">
            {docs.length === 0 && (
              <div className="px-5 py-10 text-center text-sm text-[var(--muted)]">
                暂无文档，生成时将仅基于商品输入信息
              </div>
            )}
            {docs.map((d) => (
              <div key={d.id} className="px-5 py-4 flex gap-3 justify-between">
                <div className="min-w-0">
                  <div className="font-medium text-sm truncate">{d.title}</div>
                  <div className="text-xs text-[var(--muted)] mt-1">
                    {DOC_TYPES.find((t) => t.value === d.doc_type)?.label || d.doc_type}
                    {' · '}
                    {d.chunk_count} 切片
                    {d.product_id ? ` · 商品 #${d.product_id}` : d.brand_name ? ` · 品牌：${d.brand_name}` : ' · 全局'}
                    {' · '}
                    {new Date(d.created_at).toLocaleString()}
                  </div>
                  <p className="text-xs text-[var(--muted)] mt-2 line-clamp-2">
                    {d.content.slice(0, 120)}…
                  </p>
                </div>
                <button
                  className="text-red-600 hover:text-red-700 shrink-0 p-1"
                  onClick={() => remove(d.id)}
                >
                  <Trash2 size={16} />
                </button>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
