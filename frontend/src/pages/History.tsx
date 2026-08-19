import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  CheckCircle2,
  Clock,
  Loader2,
  Trash2,
  XCircle,
  Package,
  Wand2,
} from 'lucide-react';
import { generationApi, productApi } from '../api/client';
import type { GenerationListItem, Product } from '../types';

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
      <Icon size={12} className={status === 'running' ? 'animate-spin' : ''} />
      {conf.label}
    </span>
  );
}

export default function HistoryPage() {
  const [tab, setTab] = useState<'products' | 'generations'>('products');
  const [products, setProducts] = useState<Product[]>([]);
  const [gens, setGens] = useState<GenerationListItem[]>([]);
  const [loading, setLoading] = useState(true);

  async function load() {
    const [p, g] = await Promise.all([productApi.list(), generationApi.list()]);
    setProducts(p);
    setGens(g);
  }

  useEffect(() => {
    (async () => {
      try {
        await load();
      } catch (e) {
        console.error(e);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  async function deleteProduct(id: number) {
    if (!confirm('删除商品及其所有生成记录？')) return;
    await productApi.remove(id);
    await load();
  }

  async function deleteGen(id: number) {
    if (!confirm('删除该生成记录？')) return;
    await generationApi.remove(id);
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
        <h1 className="font-display text-3xl tracking-tight">历史管理</h1>
        <p className="mt-1 text-sm text-[var(--muted)]">查看与删除商品项目、生成记录</p>
      </header>

      <div className="flex gap-1 p-1 rounded-lg bg-[var(--bg-elevated)] border border-[var(--border)] w-fit">
        <button
          className={`px-4 py-1.5 text-sm rounded-md inline-flex items-center gap-2 ${
            tab === 'products' ? 'bg-white shadow-sm' : 'text-[var(--muted)]'
          }`}
          onClick={() => setTab('products')}
        >
          <Package size={14} /> 商品项目
        </button>
        <button
          className={`px-4 py-1.5 text-sm rounded-md inline-flex items-center gap-2 ${
            tab === 'generations' ? 'bg-white shadow-sm' : 'text-[var(--muted)]'
          }`}
          onClick={() => setTab('generations')}
        >
          <Wand2 size={14} /> 生成记录
        </button>
      </div>

      <div className="panel overflow-hidden">
        {tab === 'products' ? (
          <table className="w-full text-sm">
            <thead className="bg-[var(--bg-elevated)] text-[var(--muted)] text-left">
              <tr>
                <th className="px-5 py-3 font-medium">商品</th>
                <th className="px-5 py-3 font-medium">类别</th>
                <th className="px-5 py-3 font-medium">价格</th>
                <th className="px-5 py-3 font-medium">生成次数</th>
                <th className="px-5 py-3 font-medium">创建时间</th>
                <th className="px-5 py-3 font-medium"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--border)]">
              {products.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-5 py-10 text-center text-[var(--muted)]">
                    暂无商品
                  </td>
                </tr>
              )}
              {products.map((p) => (
                <tr key={p.id} className="hover:bg-[var(--bg-elevated)]/60">
                  <td className="px-5 py-3">
                    <Link to={`/products/${p.id}`} className="font-medium text-[var(--accent)] hover:underline">
                      {p.name}
                    </Link>
                  </td>
                  <td className="px-5 py-3 text-[var(--muted)]">{p.category || '—'}</td>
                  <td className="px-5 py-3">¥{p.price}</td>
                  <td className="px-5 py-3">{p.generation_count}</td>
                  <td className="px-5 py-3 text-[var(--muted)]">
                    {new Date(p.created_at).toLocaleString()}
                  </td>
                  <td className="px-5 py-3 text-right">
                    <button
                      className="text-red-600 hover:text-red-700 p-1"
                      onClick={() => deleteProduct(p.id)}
                      title="删除"
                    >
                      <Trash2 size={16} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-[var(--bg-elevated)] text-[var(--muted)] text-left">
              <tr>
                <th className="px-5 py-3 font-medium">ID</th>
                <th className="px-5 py-3 font-medium">商品</th>
                <th className="px-5 py-3 font-medium">状态</th>
                <th className="px-5 py-3 font-medium">时间</th>
                <th className="px-5 py-3 font-medium"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--border)]">
              {gens.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-5 py-10 text-center text-[var(--muted)]">
                    暂无生成记录
                  </td>
                </tr>
              )}
              {gens.map((g) => (
                <tr key={g.id} className="hover:bg-[var(--bg-elevated)]/60">
                  <td className="px-5 py-3">
                    <Link to={`/generations/${g.id}`} className="text-[var(--accent)] hover:underline">
                      #{g.id}
                    </Link>
                  </td>
                  <td className="px-5 py-3">{g.product_name || `商品 #${g.product_id}`}</td>
                  <td className="px-5 py-3">
                    <StatusBadge status={g.status} />
                  </td>
                  <td className="px-5 py-3 text-[var(--muted)]">
                    {new Date(g.created_at).toLocaleString()}
                  </td>
                  <td className="px-5 py-3 text-right">
                    <button
                      className="text-red-600 hover:text-red-700 p-1"
                      onClick={() => deleteGen(g.id)}
                    >
                      <Trash2 size={16} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
