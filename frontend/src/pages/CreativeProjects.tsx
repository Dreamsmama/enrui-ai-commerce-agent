import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ArrowRight, Image, Layers3, Loader2, Megaphone, PackageCheck, Plus, Sparkles } from 'lucide-react';
import { creativeApi, mediaUrl, productApi } from '../api/client';
import type { CreativeProject, Product } from '../types';

const TASKS = [
  {
    id: 'full_detail', title: '整套商品详情页', icon: Layers3, platform: '天猫', width: 750, height: 1000,
    description: 'AI理解商品、规划整套结构并逐屏生成 Storyboard',
    brief: '为当前商品策划并制作一套完整电商详情页。先基于商品资料、品牌知识、品类 Skill 和平台规则规划模块与叙事顺序，再逐屏生成视觉预览；保持商品、包装和所有事实信息准确。',
  },
  {
    id: 'detail_hero', title: '详情页首屏', icon: Image, platform: '天猫', width: 750, height: 1000,
    description: '突出商品主体、品牌气质与第一核心卖点',
    brief: '设计商品详情页首屏。保持商品包装、瓶型、标签文字和套装数量准确；商品作为绝对视觉主体；结合品牌视觉语言呈现第一核心卖点；构图适合电商首屏，文案简短克制。',
  },
  {
    id: 'selling_point', title: '核心卖点模块', icon: PackageCheck, platform: '天猫', width: 750, height: 1000,
    description: '围绕单个卖点生成可替换的详情模块',
    brief: '设计详情页核心卖点模块。围绕一个明确且有商品资料依据的利益点展开；保持商品主体准确；视觉层级清楚，适合与其他详情模块纵向组合；避免绝对化、医疗化表达。',
  },
  {
    id: 'social', title: '小红书种草图', icon: Megaphone, platform: '小红书', width: 1242, height: 1660,
    description: '生成更生活化、更具分享感的内容视觉',
    brief: '设计小红书种草视觉。保持商品包装准确，强调真实使用场景、生活方式和分享感；品牌识别清晰但不过度广告化；画面自然、精致、便于社交平台阅读。',
  },
  {
    id: 'free', title: '自由视觉探索', icon: Layers3, platform: '天猫', width: 1000, height: 1000,
    description: '组合多张参考素材，探索构图和风格方向',
    brief: '围绕当前商品进行自由视觉探索。保持商品主体准确，结合商品知识、品牌素材、历史设计偏好和选择的参考图片，生成多个有明显差异的构图与风格方向。',
  },
];

export default function CreativeProjectsPage() {
  const navigate = useNavigate();
  const [projects, setProjects] = useState<CreativeProject[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [productId, setProductId] = useState('');
  const [taskId, setTaskId] = useState('full_detail');
  const [extraBrief, setExtraBrief] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => { Promise.all([creativeApi.list(), productApi.list()]).then(([projectRows, productRows]) => { setProjects(projectRows); setProducts(productRows); if (productRows.length) setProductId(String(productRows[0].id)); }); }, []);
  const product = products.find((item) => String(item.id) === productId);
  const task = TASKS.find((item) => item.id === taskId) || TASKS[0];
  const productReadiness = useMemo(() => product ? [
    { label: '商品图', ready: product.image_urls.length > 0 },
    { label: '品牌', ready: Boolean(product.brand_name) },
    { label: '卖点描述', ready: Boolean(product.description) },
    { label: '成分', ready: Boolean(product.ingredients) },
  ] : [], [product]);

  async function createProject() {
    if (!product) return;
    setSaving(true);
    try {
      const project = await creativeApi.create({
        product_id: product.id,
        name: `${product.name} · ${task.title}`,
        brief: `${task.brief}\n\n商品：${product.name}\n品牌：${product.brand_name}\n品类：${product.category}${extraBrief.trim() ? `\n\n本次补充要求：${extraBrief.trim()}` : ''}`,
        platform: task.platform,
        output_width: task.width,
        output_height: task.height,
      });
      navigate(task.id === 'full_detail' ? `/creative-projects/${project.id}/storyboard` : `/creative-projects/${project.id}?welcome=1`);
    } finally { setSaving(false); }
  }

  return <div className="space-y-7 animate-fade-in max-w-7xl mx-auto">
    <header><div className="text-xs font-medium text-[var(--accent)] mb-2">DESIGNER WORKSPACE</div><h1 className="font-display text-4xl">开始一个真实设计任务</h1><p className="mt-2 text-sm text-[var(--muted)]">系统自动准备商品、品牌和历史设计偏好，你只需要选择今天要完成什么。</p></header>

    <section className="panel overflow-hidden">
      <div className="grid lg:grid-cols-[300px_1fr]">
        <div className="p-6 bg-[#f1eee7] border-r border-[var(--border)]">
          <div className="text-xs font-medium text-[var(--muted)] mb-3">1 · 选择商品</div>
          <select className="input-select w-full" value={productId} onChange={(event) => setProductId(event.target.value)}>{products.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select>
          {product && <div className="mt-5"><div className="rounded-2xl bg-white border border-[var(--border)] overflow-hidden"><img src={mediaUrl(product.image_urls[0] || '')} className="w-full h-44 object-contain bg-white" /><div className="p-4"><div className="font-medium line-clamp-2">{product.name}</div><div className="text-xs text-[var(--muted)] mt-1">{product.brand_name} · {product.category}</div></div></div><div className="mt-4 space-y-2">{productReadiness.map((item) => <div key={item.label} className="flex items-center justify-between text-xs"><span>{item.label}</span><span className={item.ready ? 'text-emerald-700' : 'text-amber-700'}>{item.ready ? '已准备' : '待补充'}</span></div>)}</div></div>}
        </div>

        <div className="p-6 lg:p-8">
          <div className="text-xs font-medium text-[var(--muted)] mb-3">2 · 选择任务</div>
          <div className="grid md:grid-cols-2 gap-3">{TASKS.map((item) => { const Icon = item.icon; const active = taskId === item.id; return <button key={item.id} type="button" onClick={() => setTaskId(item.id)} className={`text-left rounded-2xl border-2 p-4 transition-all ${active ? 'border-[var(--accent)] bg-[#edf5f2] shadow-sm' : 'border-[var(--border)] hover:border-[#9ebbb1] bg-white'}`}><div className="flex items-start gap-3"><span className={`w-10 h-10 rounded-xl grid place-items-center ${active ? 'bg-[var(--accent)] text-white' : 'bg-[#f1eee8]'}`}><Icon size={19} /></span><span><span className="font-medium block">{item.title}</span><span className="text-xs text-[var(--muted)] mt-1 block leading-5">{item.description}</span><span className="text-[11px] text-[var(--muted)] mt-2 block">{item.platform} · {item.width}×{item.height}</span></span></div></button>; })}</div>
          <div className="mt-6"><label className="text-xs font-medium text-[var(--muted)]">3 · 有特别要求吗？（可不填）</label><textarea className="input w-full min-h-24 mt-2 resize-none" value={extraBrief} onChange={(event) => setExtraBrief(event.target.value)} placeholder="例如：七夕礼赠场景、减少文字、增加水润光影……" /></div>
          <div className="mt-5 rounded-xl bg-[#f7f5f0] px-4 py-3 text-xs text-[var(--muted)] flex items-start gap-2"><Sparkles size={15} className="text-[var(--accent)] shrink-0 mt-0.5" /><span>进入后自动带入商品图、品牌素材、商品知识和已学习的设计偏好，不需要手动配置知识库或 Skill。</span></div>
          <button className="btn-primary w-full justify-center mt-5 py-3" disabled={saving || !product} onClick={createProject}>{saving ? <Loader2 size={16} className="animate-spin" /> : <Sparkles size={16} />}{task.id === 'full_detail' ? 'AI策划整套详情页' : '准备素材并进入工作台'}<ArrowRight size={16} /></button>
        </div>
      </div>
    </section>

    <section><div className="flex items-center justify-between mb-4"><div><h2 className="font-medium text-lg">最近项目</h2><p className="text-xs text-[var(--muted)] mt-1">默认进入详情页策划与 Storyboard，高级画布仍可随时打开</p></div><span className="text-xs text-[var(--muted)]">共 {projects.length} 个</span></div><div className="grid sm:grid-cols-2 xl:grid-cols-3 gap-4">{projects.map((project) => <Link key={project.id} to={`/creative-projects/${project.id}/storyboard`} className="panel p-5 hover:border-[var(--accent)] hover:-translate-y-0.5 transition-all group"><div className="flex justify-between gap-3"><div className="font-medium line-clamp-2">{project.name}</div><ArrowRight size={16} className="text-[var(--muted)] group-hover:text-[var(--accent)] shrink-0" /></div><p className="mt-3 text-xs text-[var(--muted)] line-clamp-2 leading-5">{project.brief || '暂无设计目标'}</p><div className="mt-4 pt-3 border-t border-[var(--border)] text-[11px] text-[var(--muted)]">{project.platform} · {project.output_width}×{project.output_height} · {new Date(project.updated_at).toLocaleDateString()}</div></Link>)}{!projects.length && <div className="panel p-10 text-center text-sm text-[var(--muted)] sm:col-span-2 xl:col-span-3"><Plus size={22} className="mx-auto mb-2" />选择商品和设计任务，创建第一个项目。</div>}</div></section>
  </div>;
}
