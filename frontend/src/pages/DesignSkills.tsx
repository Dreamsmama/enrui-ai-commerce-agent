import { useEffect, useState, type FormEvent } from 'react';
import { Check, Loader2, Palette, Trash2, X } from 'lucide-react';
import { designSkillApi, productApi } from '../api/client';
import type { DesignSkill, DesignSkillCreate, Product, SkillCandidate } from '../types';

const scopes = [
  { value: 'general', label: '租户通用' },
  { value: 'category', label: '指定品类' },
  { value: 'brand', label: '指定品牌' },
  { value: 'product', label: '指定商品' },
] as const;

const initial: DesignSkillCreate = {
  name: '', scope: 'brand', category: '', brand_name: '', product_id: null,
  description: '', design_principles: '', module_guidance: '', visual_rules: '',
  copy_rules: '', negative_rules: '', primary_color: '#1f7258', accent_color: '#dceee5', enabled: true,
};

export default function DesignSkillsPage() {
  const [skills, setSkills] = useState<DesignSkill[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [candidates, setCandidates] = useState<SkillCandidate[]>([]);
  const [form, setForm] = useState<DesignSkillCreate>(initial);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [editingCandidate,setEditingCandidate]=useState<number|null>(null);
  const [versions,setVersions]=useState<Record<number,Array<{version:number;change_note:string;created_at:string;is_current:boolean}>>>({});

  async function load() {
    const [skillRows, productRows, candidateRows] = await Promise.all([designSkillApi.list(), productApi.list(), designSkillApi.candidates()]);
    setSkills(skillRows);
    setProducts(productRows);
    setCandidates(candidateRows);
  }

  useEffect(() => { load().catch(() => setError('加载设计 Skill 失败')); }, []);

  function field<K extends keyof DesignSkillCreate>(key: K, value: DesignSkillCreate[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true); setError('');
    try {
      if(editingCandidate) await designSkillApi.updateCandidate(editingCandidate,form); else await designSkillApi.create(form);
      setForm(initial);
      setEditingCandidate(null);
      await load();
    } catch (err) {
      console.error(err); setError('保存失败，请检查作用范围对应的信息是否填写完整');
    } finally { setSaving(false); }
  }

  async function remove(id: number) {
    if (!confirm('删除该设计 Skill？')) return;
    await designSkillApi.remove(id); await load();
  }

  return <div className="space-y-6 animate-fade-in">
    <header>
      <h1 className="font-display text-3xl tracking-tight">设计师 Skill</h1>
      <p className="mt-1 text-sm text-[var(--muted)]">按 通用 → 品类 → 品牌 → 商品 自动叠加，越具体的规则优先级越高</p>
    </header>
    {error && <div className="rounded-lg border border-red-200 bg-red-50 text-red-700 px-4 py-3 text-sm">{error}</div>}
    {candidates.some((item) => item.status === 'pending') && <section className="panel overflow-hidden"><div className="panel-header"><div><h2 className="font-medium">AI 学习候选 Skill</h2><p className="text-xs text-[var(--muted)] mt-1">先编辑核对，再发布为正式规则。</p></div></div><div className="divide-y divide-[var(--border)]">{candidates.filter((item) => item.status === 'pending').map((candidate) => <div key={candidate.id} className="p-5 flex flex-col md:flex-row md:items-center gap-4"><div className="flex-1"><div className="font-medium text-sm">{candidate.name}</div><div className="text-xs text-[var(--muted)] mt-1">{candidate.brand_name || candidate.category} · {candidate.sample_count} 个样本 · 置信度 {Math.round(candidate.confidence * 100)}%</div><p className="text-xs leading-5 mt-2">{candidate.payload.visual_rules || candidate.payload.design_principles}</p></div><div className="flex gap-2"><button className="btn-secondary" onClick={()=>{setForm(candidate.payload);setEditingCandidate(candidate.id);window.scrollTo({top:document.body.scrollHeight,behavior:'smooth'})}}>编辑候选</button><button className="btn-primary" onClick={async () => { await designSkillApi.publishCandidate(candidate.id); await load(); }}><Check size={14}/>审核并发布</button><button className="btn-secondary" onClick={async () => { await designSkillApi.rejectCandidate(candidate.id); await load(); }}><X size={14}/>暂不采用</button></div></div>)}</div></section>}
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <form className="panel p-6 space-y-4" onSubmit={submit}>
        <h2 className="font-medium flex items-center gap-2"><Palette size={18} /> 新建设计 Skill</h2>
        <div className="grid grid-cols-2 gap-3">
          <label className="field"><span>Skill 名称</span><input required value={form.name} onChange={(e) => field('name', e.target.value)} placeholder="百雀羚东方草本详情页" /></label>
          <label className="field"><span>作用范围</span><select className="input-select" value={form.scope} onChange={(e) => field('scope', e.target.value as DesignSkillCreate['scope'])}>{scopes.map((scope) => <option key={scope.value} value={scope.value}>{scope.label}</option>)}</select></label>
        </div>
        {form.scope === 'category' && <label className="field"><span>适用品类</span><input required value={form.category} onChange={(e) => field('category', e.target.value)} placeholder="护肤套装" /></label>}
        {form.scope === 'brand' && <label className="field"><span>适用品牌</span><input required value={form.brand_name} onChange={(e) => field('brand_name', e.target.value)} placeholder="百雀羚" /></label>}
        {form.scope === 'product' && <label className="field"><span>适用商品</span><select required className="input-select" value={form.product_id || ''} onChange={(e) => field('product_id', Number(e.target.value) || null)}><option value="">请选择商品</option>{products.map((product) => <option key={product.id} value={product.id}>{product.name}</option>)}</select></label>}
        <label className="field"><span>Skill 说明</span><input value={form.description} onChange={(e) => field('description', e.target.value)} placeholder="适合东方草本、成熟肌抗老套装" /></label>
        <label className="field"><span>设计原则</span><textarea rows={3} value={form.design_principles} onChange={(e) => field('design_principles', e.target.value)} placeholder="商品占画面主体，东方留白，强调温润与可信赖感…" /></label>
        <label className="field"><span>模块指导</span><textarea rows={3} value={form.module_guidance} onChange={(e) => field('module_guidance', e.target.value)} placeholder="首屏套装全景；第二屏核心抗皱卖点；第三屏成分依据…" /></label>
        <label className="field"><span>视觉规则</span><textarea rows={3} value={form.visual_rules} onChange={(e) => field('visual_rules', e.target.value)} placeholder="米白底、草木绿点缀、避免科技蓝与强促销红…" /></label>
        <label className="field"><span>文案规则</span><textarea rows={2} value={form.copy_rules} onChange={(e) => field('copy_rules', e.target.value)} placeholder="短标题、功效有依据、语气温润克制…" /></label>
        <label className="field"><span>禁止事项</span><textarea rows={2} value={form.negative_rules} onChange={(e) => field('negative_rules', e.target.value)} placeholder="不得虚构成分，不使用绝对化抗皱承诺…" /></label>
        <div className="grid grid-cols-2 gap-3">
          <label className="field"><span>主色</span><input type="color" value={form.primary_color} onChange={(e) => field('primary_color', e.target.value)} /></label>
          <label className="field"><span>辅助色</span><input type="color" value={form.accent_color} onChange={(e) => field('accent_color', e.target.value)} /></label>
        </div>
        <button className="btn-primary" disabled={saving}>{saving && <Loader2 className="animate-spin" size={16} />}{editingCandidate?'保存候选修改':'保存 Skill'}</button>
      </form>
      <div className="panel overflow-hidden">
        <div className="panel-header"><h2 className="font-medium">已配置 Skill（{skills.length}）</h2></div>
        <div className="divide-y divide-[var(--border)] max-h-[780px] overflow-auto">
          {skills.length === 0 && <div className="px-5 py-10 text-center text-sm text-[var(--muted)]">暂无自定义 Skill，将使用平台通用设计规则</div>}
          {skills.map((skill) => <div key={skill.id} className="px-5 py-4 flex flex-wrap justify-between gap-3">
            <div className="min-w-0">
              <div className="font-medium text-sm flex items-center gap-2"><span className="w-3 h-3 rounded-full" style={{ background: skill.primary_color }} />{skill.name}</div>
              <div className="text-xs text-[var(--muted)] mt-1">{scopes.find((scope) => scope.value === skill.scope)?.label}{skill.brand_name ? ` · ${skill.brand_name}` : ''}{skill.category ? ` · ${skill.category}` : ''}{skill.product_id ? ` · 商品 #${skill.product_id}` : ''}</div>
              <p className="text-xs text-[var(--muted)] mt-2 line-clamp-3">{skill.design_principles || skill.visual_rules || skill.description}</p>
            </div>
            <div className="shrink-0 flex flex-col gap-2"><button className="btn-secondary text-xs" onClick={async()=>setVersions({...versions,[skill.id]:await designSkillApi.versions(skill.id)})}>v{skill.version} 历史</button><button className="text-red-600 p-1" onClick={() => remove(skill.id)}><Trash2 size={16} /></button></div>
            {versions[skill.id]&&<div className="basis-full mt-3 rounded-lg bg-[var(--bg-elevated)] p-3">{versions[skill.id].map(v=><div key={v.version} className="flex justify-between text-xs py-1"><span>v{v.version} · {v.change_note} {v.is_current?'（当前）':''}</span>{!v.is_current&&<button className="text-[var(--accent)]" onClick={async()=>{await designSkillApi.rollback(skill.id,v.version);await load();setVersions({...versions,[skill.id]:await designSkillApi.versions(skill.id)})}}>回滚到此版本</button>}</div>)}</div>}
          </div>)}
        </div>
      </div>
    </div>
  </div>;
}
