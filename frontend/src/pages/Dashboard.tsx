import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  AlertCircle,
  ArrowRight,
  CheckCircle2,
  CircleDot,
  FolderKanban,
  Image,
  Loader2,
  Play,
  Plus,
  RotateCcw,
} from 'lucide-react';
import { dashboardApi } from '../api/client';
import type { DashboardStats } from '../types';

const reviewLabels: Record<string, string> = {
  draft: '制作中',
  submitted: '待审核',
  operational_approved: '待定稿',
  changes_requested: '需修改',
  finalized: '已定稿',
};

export default function Dashboard() {
  const [data, setData] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    dashboardApi.stats()
      .then((result) => { if (!cancelled) setData(result); })
      .catch((reason) => {
        console.error(reason);
        if (!cancelled) setError('工作台数据加载失败，请确认服务和云端数据库连接正常');
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  if (loading) {
    return <div className="flex items-center justify-center h-64 text-[var(--muted)]"><Loader2 className="animate-spin mr-2" size={20} />加载工作台…</div>;
  }
  if (error || !data) {
    return <div className="rounded-xl border border-red-200 bg-red-50 text-red-700 px-5 py-4">{error || '工作台暂无数据'}</div>;
  }

  const cards = [
    { label: '创意项目', value: data.summary.project_count, note: `已生成 ${data.summary.generated_images} 张单屏图片`, icon: FolderKanban, to: '/creative-projects' },
    { label: '进行中项目', value: data.summary.in_progress_projects, note: '尚未完成或定稿', icon: CircleDot, to: '/creative-projects' },
    { label: '已完成页面', value: data.summary.completed_pages, note: '已有可用单屏结果', icon: Image, to: '/creative-projects' },
    { label: '失败任务', value: data.summary.failed_tasks, note: data.summary.failed_tasks ? '进入任务中心诊断处理' : '当前没有失败任务', icon: AlertCircle, to: '/task-center?status=attention' },
  ];

  return <div className="space-y-7 animate-fade-in">
    <header className="flex flex-wrap items-end justify-between gap-4">
      <div>
        <div className="text-xs font-medium text-[var(--accent)] mb-2">CREATIVE WORKSPACE</div>
        <h1 className="font-display text-4xl tracking-tight">工作台</h1>
        <p className="mt-2 text-sm text-[var(--muted)]">查看当前租户的详情页制作进度，并继续下一项工作。</p>
      </div>
      <div className="flex flex-wrap gap-2">
        {data.last_project && <Link to={data.last_project.path} className="btn-secondary"><RotateCcw size={15} />进入上次编辑</Link>}
        <Link to="/products/new" className="btn-primary"><Plus size={15} />创建商品</Link>
      </div>
    </header>

    <section className="grid sm:grid-cols-2 xl:grid-cols-4 gap-4">
      {cards.map((card) => <Link key={card.label} to={card.to} className="panel p-5 hover:border-[var(--accent)] transition-colors group">
        <div className="flex items-center justify-between text-sm text-[var(--muted)]"><span>{card.label}</span><card.icon size={18} className={card.value && card.label === '失败任务' ? 'text-red-600' : 'text-[var(--accent)]'} /></div>
        <div className="font-display text-4xl mt-3 tabular-nums">{card.value}</div>
        <div className="text-[11px] text-[var(--muted)] mt-2 flex items-center justify-between"><span>{card.note}</span><ArrowRight size={13} className="opacity-0 group-hover:opacity-100" /></div>
      </Link>)}
    </section>

    <section className="panel overflow-hidden">
      <div className="panel-header flex items-center justify-between">
        <div><h2 className="font-medium">最近创意项目</h2><p className="text-xs text-[var(--muted)] mt-1">按最近更新时间排序</p></div>
        <Link to="/creative-projects" className="text-sm text-[var(--accent)] hover:underline">查看全部</Link>
      </div>
      {data.recent_projects.length === 0 ? <div className="px-5 py-12 text-center text-sm text-[var(--muted)]">还没有创意项目，先创建商品并开始第一个设计任务。</div> :
        <div className="divide-y divide-[var(--border)]">{data.recent_projects.map((project) => {
          const progress = project.total_pages ? Math.round(project.completed_pages / project.total_pages * 100) : 0;
          return <Link key={project.id} to={project.path} className="grid md:grid-cols-[1fr_220px_110px] gap-4 items-center px-5 py-4 hover:bg-[var(--bg-elevated)] transition-colors">
            <div className="min-w-0"><div className="font-medium text-sm truncate">{project.name}</div><div className="text-xs text-[var(--muted)] mt-1">{project.product_name} · {project.platform} · {new Date(project.updated_at).toLocaleString()}</div></div>
            <div><div className="flex justify-between text-[11px] text-[var(--muted)] mb-1"><span>详情页进度</span><span>{project.completed_pages}/{project.total_pages || 0}</span></div><div className="h-1.5 bg-[#e8e5de] rounded-full overflow-hidden"><div className="h-full bg-[var(--accent)] rounded-full" style={{ width: `${progress}%` }} /></div></div>
            <div className="flex justify-end items-center gap-2 text-xs text-[var(--accent)]"><span>{reviewLabels[project.review_status] || '继续制作'}</span><ArrowRight size={14} /></div>
          </Link>;
        })}</div>}
    </section>

    <section className="panel overflow-hidden">
      {data.todos.length === 0 ?
        <div className="flex items-center gap-3 px-5 py-4 text-sm text-[var(--muted)]"><CheckCircle2 size={18} className="text-emerald-700 shrink-0" /><span><strong className="font-medium text-[var(--text)]">待处理事项</strong> · 当前没有失败、阻塞或缺少素材的项目</span></div> : <>
          <div className="panel-header"><h2 className="font-medium">待处理事项</h2><p className="text-xs text-[var(--muted)] mt-1">仅显示需要立即处理的问题，不包含正常制作进度</p></div>
          <div className="divide-y divide-[var(--border)]">{data.todos.slice(0, 6).map((todo) => <Link key={todo.project_id} to={todo.path} className="flex items-center justify-between gap-4 px-5 py-4 hover:bg-[var(--bg-elevated)]">
            <div className="min-w-0"><div className="text-sm font-medium truncate">{todo.project_name}</div><div className={`text-xs mt-1 ${todo.kind === 'failed' || todo.kind === 'blocked' ? 'text-red-700' : 'text-amber-700'}`}>{todo.title}</div></div>
            <span className="btn-secondary text-xs shrink-0"><Play size={12} />{todo.action_label}</span>
          </Link>)}</div>
        </>}
    </section>
  </div>;
}
