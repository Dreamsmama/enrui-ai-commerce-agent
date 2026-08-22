import { NavLink, Outlet } from 'react-router-dom';
import {
  LayoutDashboard,
  PackagePlus,
  History,
  BookOpen,
  Sparkles,
  Palette,
  PanelsTopLeft,
  Activity,
  LayoutTemplate,
  Factory,
  ShieldCheck,
} from 'lucide-react';

const nav = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/products/new', label: '创建商品', icon: PackagePlus },
  { to: '/history', label: '历史管理', icon: History },
  { to: '/knowledge', label: '知识库', icon: BookOpen },
  { to: '/brand-visuals', label: '品牌视觉', icon: Palette },
  { to: '/design-skills', label: '设计 Skill', icon: Palette },
  { to: '/detail-templates', label: '详情页模板', icon: LayoutTemplate },
  { to: '/production', label: '批量生产看板', icon: Factory },
  { to: '/creative-projects', label: 'AI 创作工作台', icon: PanelsTopLeft },
  { to: '/task-center', label: '任务与费用', icon: Activity },
  { to: '/quality', label: '质量与审核', icon: ShieldCheck },
];

export default function Layout() {
  if (!localStorage.getItem('access_token')) {
    window.location.href = '/login';
    return null;
  }
  return (
    <div className="min-h-screen flex bg-[var(--bg)] text-[var(--text)]">
      <aside className="w-60 shrink-0 border-r border-[var(--border)] bg-[var(--panel)] flex flex-col">
        <div className="px-5 py-6 border-b border-[var(--border)]">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-lg bg-[var(--accent)] text-white flex items-center justify-center">
              <Sparkles size={18} />
            </div>
            <div>
              <div className="font-display text-lg leading-tight tracking-tight">Enrui AI</div>
              <div className="text-xs text-[var(--muted)]">Commerce Agent</div>
            </div>
          </div>
        </div>
        <nav className="flex-1 p-3 space-y-1">
          {nav.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors ${
                  isActive
                    ? 'bg-[var(--accent-soft)] text-[var(--accent)] font-medium'
                    : 'text-[var(--muted)] hover:bg-[var(--bg-elevated)] hover:text-[var(--text)]'
                }`
              }
            >
              <item.icon size={18} />
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="p-4 border-t border-[var(--border)] text-xs text-[var(--muted)]">
          多模态 Agent · RAG · 电商详情页
        </div>
      </aside>
      <main className="flex-1 overflow-auto">
        <div className="max-w-6xl mx-auto px-8 py-8">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
