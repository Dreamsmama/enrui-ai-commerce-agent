import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Package,
  Wand2,
  BookOpen,
  ArrowRight,
  Loader2,
  CheckCircle2,
  XCircle,
  Clock,
} from 'lucide-react';
import { dashboardApi, productApi } from '../api/client';
import type { DashboardStats, Product } from '../types';

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

export default function Dashboard() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [s, p] = await Promise.all([dashboardApi.stats(), productApi.list()]);
        if (!cancelled) {
          setStats(s);
          setProducts(p);
        }
      } catch (e) {
        if (!cancelled) setError('无法连接后端，请确认 FastAPI 已启动');
        console.error(e);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-[var(--muted)]">
        <Loader2 className="animate-spin mr-2" size={20} /> 加载中…
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 text-red-700 px-5 py-4">
        {error}
      </div>
    );
  }

  const cards = [
    { label: '商品数量', value: stats?.product_count ?? 0, icon: Package, tone: 'teal' },
    { label: '生成次数', value: stats?.generation_count ?? 0, icon: Wand2, tone: 'amber' },
    { label: '知识库文档', value: stats?.knowledge_doc_count ?? 0, icon: BookOpen, tone: 'slate' },
  ];

  return (
    <div className="space-y-8 animate-fade-in">
      <header className="flex items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl tracking-tight">工作台</h1>
          <p className="mt-1 text-[var(--muted)] text-sm">
            AI 商品详情页生成助手 · 多模态 Agent Workflow
          </p>
        </div>
        <Link to="/products/new" className="btn-primary inline-flex items-center gap-2">
          创建商品 <ArrowRight size={16} />
        </Link>
      </header>

      <section className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {cards.map((c) => (
          <div key={c.label} className="stat-card">
            <div className="flex items-center justify-between">
              <span className="text-sm text-[var(--muted)]">{c.label}</span>
              <c.icon size={18} className="text-[var(--accent)] opacity-80" />
            </div>
            <div className="mt-3 font-display text-4xl tracking-tight tabular-nums">
              {c.value}
            </div>
          </div>
        ))}
      </section>

      <section className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="panel">
          <div className="panel-header">
            <h2 className="font-medium">最近任务</h2>
            <Link to="/history" className="text-sm text-[var(--accent)] hover:underline">
              查看全部
            </Link>
          </div>
          <div className="divide-y divide-[var(--border)]">
            {(stats?.recent_tasks?.length ?? 0) === 0 && (
              <div className="px-5 py-10 text-center text-sm text-[var(--muted)]">
                暂无生成任务，去创建一个商品吧
              </div>
            )}
            {stats?.recent_tasks.map((t) => (
              <Link
                key={t.id}
                to={`/generations/${t.id}`}
                className="flex items-center justify-between px-5 py-3.5 hover:bg-[var(--bg-elevated)] transition-colors"
              >
                <div className="min-w-0">
                  <div className="text-sm font-medium truncate">
                    {t.product_name || `商品 #${t.product_id}`}
                  </div>
                  <div className="text-xs text-[var(--muted)] mt-0.5">
                    #{t.id} · {new Date(t.created_at).toLocaleString()}
                  </div>
                </div>
                <StatusBadge status={t.status} />
              </Link>
            ))}
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">
            <h2 className="font-medium">商品列表</h2>
            <Link to="/products/new" className="text-sm text-[var(--accent)] hover:underline">
              新建
            </Link>
          </div>
          <div className="divide-y divide-[var(--border)]">
            {products.length === 0 && (
              <div className="px-5 py-10 text-center text-sm text-[var(--muted)]">
                还没有商品
              </div>
            )}
            {products.slice(0, 8).map((p) => (
              <Link
                key={p.id}
                to={`/products/${p.id}`}
                className="flex items-center justify-between px-5 py-3.5 hover:bg-[var(--bg-elevated)] transition-colors"
              >
                <div className="min-w-0">
                  <div className="text-sm font-medium truncate">{p.name}</div>
                  <div className="text-xs text-[var(--muted)] mt-0.5">
                    {p.category || '未分类'} · ¥{p.price} · 生成 {p.generation_count} 次
                  </div>
                </div>
                <ArrowRight size={16} className="text-[var(--muted)] shrink-0" />
              </Link>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
