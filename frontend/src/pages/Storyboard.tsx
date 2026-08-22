import { useCallback, useEffect, useMemo, useState, type MouseEvent } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Check, CircleStop, Download, Eye, Image as ImageIcon, Loader2, Palette, Play, Plus, RefreshCw, SlidersHorizontal, Sparkles, Trash2, WandSparkles, X } from 'lucide-react';
import { creativeApi, mediaUrl, operationsApi, productionApi } from '../api/client';
import ComplianceModal from '../components/ComplianceModal';
import StyleBatchModal from '../components/StyleBatchModal';
import type { StyleVersion } from '../components/StyleBatchModal';
import DirectEditModal, { type DirectEditState } from '../components/DirectEditModal';
import type { CanvasNodeRecord, ComplianceReport, CreativePlan, CreativeProject, StoryboardBatchJob, StoryboardModule } from '../types';

const METHOD_LABELS: Record<string, string> = {
  ai_image: 'AI视觉生成',
  template: '模板排版',
  manual: '设计师精修',
};

export default function StoryboardPage() {
  const projectId = Number(useParams().id);
  const [project, setProject] = useState<CreativeProject | null>(null);
  const [plan, setPlan] = useState<CreativePlan | null>(null);
  const [modules, setModules] = useState<StoryboardModule[]>([]);
  const [nodes, setNodes] = useState<Record<string, CanvasNodeRecord>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [generatingId, setGeneratingId] = useState<number | null>(null);
  const [batchRunning, setBatchRunning] = useState(false);
  const [batchCompleted, setBatchCompleted] = useState(0);
  const [batchTotal, setBatchTotal] = useState(0);
  const [batchJob, setBatchJob] = useState<StoryboardBatchJob | null>(null);
  const [failedIds, setFailedIds] = useState<number[]>([]);
  const [exporting, setExporting] = useState(false);
  const [exportResult, setExportResult] = useState<{ long_image_url: string; module_count: number; missing_modules: string[] } | null>(null);
  const [complianceReport, setComplianceReport] = useState<ComplianceReport | null>(null);
  const [showStyleBatch, setShowStyleBatch] = useState(false);
  const [directEditingModule, setDirectEditingModule] = useState<StoryboardModule | null>(null);
  const [editingModule, setEditingModule] = useState<StoryboardModule | null>(null);
  const [editValues, setEditValues] = useState({ headline: '', subtitle: '', zoom: 1, offset_x: 0, offset_y: 0 });
  const [applyingEdit, setApplyingEdit] = useState(false);
  const [error, setError] = useState('');
  const [review,setReview]=useState<{status:string;round:number;history:Array<{id:number;action:string;note:string;actor_role:string;created_at:string}>}|null>(null);
  const [snapshots,setSnapshots]=useState<Array<{id:number;version:number;trigger:string;diff:{change_count:number;changes:Array<Record<string,unknown>>};created_at:string}>>([]);
  const [qualitySummary,setQualitySummary]=useState<{status:string;score:number;scored_count:number;module_count:number;issues:Array<{module_id:number;severity:string;message:string;suggestion:string}>}|null>(null);
  const [approvalIssues,setApprovalIssues]=useState<Array<{id:number;module_id:number;source_node_id:string|null;resolved_node_id:string|null;issue_type:string;severity:string;action:string;note:string;region?:{x:number;y:number;width:number;height:number};status:string;created_at:string}>>([]);
  const [productLock,setProductLock]=useState<'strict'|'balanced'|'creative'>('strict');
  const [variationAxis,setVariationAxis]=useState<'composition'|'scene'|'color'|'model'|'lighting'>('composition');
  const [markingModule,setMarkingModule]=useState<number|null>(null);
  const [dragStart,setDragStart]=useState<{x:number;y:number}|null>(null);
  const [markedRegion,setMarkedRegion]=useState<{x:number;y:number;width:number;height:number}|null>(null);
  const [regression,setRegression]=useState<{status:string;case_count:number;passed:number;failed:number}|null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [projectRow, nodeRows, latestBatch, reviewRow,snapshotRows,qualityRow,issueRows] = await Promise.all([creativeApi.get(projectId), creativeApi.nodes(projectId), creativeApi.latestBatch(projectId),operationsApi.projectReviews(projectId),productionApi.snapshots(projectId),creativeApi.qualitySummary(projectId),creativeApi.approvalIssues(projectId)]);
      setProject(projectRow);
      setReview(reviewRow);
      setSnapshots(snapshotRows);
      setQualitySummary(qualityRow);
      setApprovalIssues(issueRows);
      setNodes(Object.fromEntries(nodeRows.map((node) => [node.id, node])));
      let planRow: CreativePlan;
      try {
        planRow = await creativeApi.getPlan(projectId);
      } catch {
        planRow = await creativeApi.generatePlan(projectId);
      }
      setPlan(planRow);
      setModules(planRow.modules);
      if (latestBatch) {
        setBatchJob(latestBatch);
        setBatchCompleted(latestBatch.completed + latestBatch.failed);
        setBatchTotal(latestBatch.total);
        setFailedIds(latestBatch.module_results.filter((item) => item.status === 'failed').map((item) => item.module_id));
        setBatchRunning(['pending', 'running'].includes(latestBatch.status));
      }
    } catch (err) {
      console.error(err);
      setError('详情页策划加载失败，请稍后重试。');
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    if (!batchRunning) return;
    const timer = window.setInterval(async () => {
      try {
        const job = await creativeApi.latestBatch(projectId);
        if (!job) return;
        setBatchJob(job); setBatchCompleted(job.completed + job.failed); setBatchTotal(job.total);
        setFailedIds(job.module_results.filter((item) => item.status === 'failed').map((item) => item.module_id));
        if (job.completed + job.failed > 0) {
          const [planRow, nodeRows] = await Promise.all([creativeApi.getPlan(projectId), creativeApi.nodes(projectId)]);
          setPlan(planRow); setModules(planRow.modules); setNodes(Object.fromEntries(nodeRows.map((node) => [node.id, node])));
        }
        if (!['pending', 'running'].includes(job.status)) {
          setBatchRunning(false);
          if (job.failed) setError(`${job.failed} 个模块生成失败，可点击“重试失败模块”。`);
        }
      } catch (err) {
        console.error(err);
      }
    }, 2000);
    return () => window.clearInterval(timer);
  }, [batchRunning, projectId]);

  const readyCount = useMemo(() => modules.filter((module) => module.preview_node_id).length, [modules]);

  function updateModule(id: number, values: Partial<StoryboardModule>) {
    setModules((current) => current.map((module) => module.id === id ? { ...module, ...values } : module));
  }

  function moveModule(index: number, offset: number) {
    const target = index + offset;
    if (target < 0 || target >= modules.length) return;
    setModules((current) => {
      const next = [...current];
      [next[index], next[target]] = [next[target], next[index]];
      return next.map((module, moduleIndex) => ({ ...module, sort_order: moduleIndex + 1 }));
    });
  }

  async function confirmPlan() {
    setSaving(true); setError('');
    try {
      const next = await creativeApi.updatePlanModules(projectId, modules.map((module, index) => ({
        sort_order: index + 1,
        module_type: module.module_type,
        title: module.title,
        objective: module.objective,
        content_guidance: module.content_guidance,
        visual_direction: module.visual_direction,
        production_method: module.production_method,
        required: module.required,
      })));
      setPlan(next); setModules(next.modules);
    } catch (err) {
      console.error(err); setError('策划保存失败；已有图片的模块请直接在当前列表调整。');
    } finally { setSaving(false); }
  }

  async function generatePreview(module: StoryboardModule, quiet = false) {
    setGeneratingId(module.id); setError('');
    try {
      const result = await creativeApi.generate(projectId, {
        prompt: `${module.objective}。${module.content_guidance}。${module.visual_direction}`,
        action: `详情页·${module.title}`,
        selected_node_ids: [],
        auto_select_materials: true,
        module_id: module.id,
        count: 1,
        product_lock: productLock,
        variation_axis: variationAxis,
        generation_stage: 'preview',
      });
      const node = result.nodes[0];
      if (node) {
        setNodes((current) => ({ ...current, [node.id]: node }));
        updateModule(module.id, { preview_node_id: node.id, status: 'preview_ready' });
        setFailedIds((current) => current.filter((id) => id !== module.id));
      }
      return Boolean(node);
    } catch (err) {
      console.error(err);
      setFailedIds((current) => current.includes(module.id) ? current : [...current, module.id]);
      if (!quiet) setError(`${module.title}生成失败，请稍后重试。`);
      return false;
    } finally { setGeneratingId(null); }
  }

  function point(event:MouseEvent<HTMLElement>){const box=event.currentTarget.getBoundingClientRect();return{x:Math.max(0,Math.min(1,(event.clientX-box.left)/box.width)),y:Math.max(0,Math.min(1,(event.clientY-box.top)/box.height))};}

  async function generateAllPending(retryFailedOnly = false) {
    const targets = modules.filter((module) => retryFailedOnly ? failedIds.includes(module.id) : !module.preview_node_id);
    if (!targets.length) return;
    setError(''); setFailedIds([]);
    try {
      const job = await creativeApi.createBatch(projectId, targets.map((module) => module.id));
      setBatchJob(job); setBatchRunning(true); setBatchCompleted(job.completed + job.failed); setBatchTotal(job.total);
    } catch (err) {
      console.error(err); setError('后台批量任务创建失败，请稍后重试。');
    }
  }

  async function stopBatch() {
    if (!batchJob) return;
    try { setBatchJob(await creativeApi.stopBatch(projectId, batchJob.id)); }
    catch (err) { console.error(err); setError('停止任务失败，请稍后重试。'); }
  }

  async function previewLongImage() {
    setExporting(true); setError('');
    try {
      await creativeApi.visionQualitySummary(projectId);
      const report = await creativeApi.compliance(projectId);
      try { report.product_consistency = await creativeApi.productConsistency(projectId); }
      catch { report.product_consistency = { status: 'unavailable', checked_count: 0, issues: [], message: '视觉理解模型暂时不可用，请人工核对商品一致性。' }; }
      setComplianceReport(report);
    } catch (err) {
      console.error(err); setError('合规检查失败，请稍后重试。');
    } finally { setExporting(false); }
  }

  async function confirmComplianceAndPreview() {
    setExporting(true); setError('');
    try { setExportResult(await creativeApi.exportStoryboard(projectId, true)); setComplianceReport(null); }
    catch (err) { console.error(err); setError('请至少完成一个模块后再预览整套详情页。'); }
    finally { setExporting(false); }
  }

  async function applyStyle(values: { name: string; primary_color: string; accent_color: string; typography: string; whitespace: number; copy_density: number }) { const next=await creativeApi.applyStyle(projectId,values); setPlan(next); setModules(next.modules); setNodes(Object.fromEntries((await creativeApi.nodes(projectId)).map(node=>[node.id,node]))); setShowStyleBatch(false); }
  async function rollbackStyle(versionId: string) { const next=await creativeApi.rollbackStyle(projectId,versionId); setPlan(next); setModules(next.modules); setShowStyleBatch(false); }

  async function selectVersion(module: StoryboardModule, nodeId: string, approve = false) {
    setError('');
    try {
      const updated = await creativeApi.selectModuleVersion(projectId, module.id, nodeId, approve);
      updateModule(module.id, updated);
    } catch (err) {
      console.error(err); setError(`${module.title}版本保存失败，请重试。`);
    }
  }

  function openQuickEdit(module: StoryboardModule) {
    setDirectEditingModule(module);
    setEditValues({ headline: module.title, subtitle: '', zoom: 1, offset_x: 0, offset_y: 0 });
  }

  async function saveDirectEdit(values: DirectEditState) {
    if (!directEditingModule?.preview_node_id) return;
    const node = await creativeApi.quickEditModule(projectId, directEditingModule.id, { node_id: directEditingModule.preview_node_id, ...values });
    setNodes((current) => ({ ...current, [node.id]: node }));
    updateModule(directEditingModule.id, { preview_node_id: node.id, final_node_id: null, status: 'preview_ready' });
    setDirectEditingModule(null);
  }

  async function applyQuickEdit() {
    if (!editingModule?.preview_node_id) return;
    setApplyingEdit(true); setError('');
    try {
      const node = await creativeApi.quickEditModule(projectId, editingModule.id, { node_id: editingModule.preview_node_id, ...editValues });
      setNodes((current) => ({ ...current, [node.id]: node }));
      updateModule(editingModule.id, { preview_node_id: node.id, final_node_id: null, status: 'preview_ready' });
      setEditingModule(null);
    } catch (err) {
      console.error(err); setError('快速编辑失败，请确认当前图片已保存在本地素材库。');
    } finally { setApplyingEdit(false); }
  }

  function addModule() {
    const temporaryId = -Date.now();
    setModules((current) => [...current, {
      id: temporaryId, project_id: projectId, sort_order: current.length + 1,
      module_type: 'custom', title: '自定义模块', objective: '说明本模块希望消费者理解什么',
      content_guidance: '', visual_direction: '延续整套详情页视觉语言', production_method: 'ai_image',
      required: false, status: 'planned', preview_node_id: null, final_node_id: null,
      created_at: '', updated_at: '',
    }]);
  }

  if (loading) return <div className="h-72 grid place-items-center"><Loader2 className="animate-spin text-[var(--accent)]" /></div>;
  if (!project || !plan) return <div className="panel p-10 text-center text-red-700">{error || '项目不存在'}</div>;

  const understanding = plan.product_understanding;
  const strategy = plan.strategy;
  async function actReview(action:string){
    const needsNote=['reject','finalize','approve_conditional'].includes(action);
    const note=needsNote?prompt(action==='finalize'?'请确认定稿风险；如无风险请填“已确认无未解决风险”':action==='approve_conditional'?'请填写交付前必须修复的小问题':'请填写驳回原因')||'':'';
    if(needsNote&&!note)return;
    setError('');
    let extra:undefined|{module_id?:number;assignee_id?:string;due_at?:string|null;blocks_finalize?:boolean};
    if(action==='approve_conditional'){
      const target=prompt(`请输入需修改的页面序号（1-${modules.length}）`,'1');if(!target)return;const module=modules[Number(target)-1];if(!module){setError('页面序号无效');return}const assignee=prompt('请输入负责人ID或姓名','')||'';const due=prompt('请输入截止时间，例如 2026-08-30 18:00','')||'';extra={module_id:module.id,assignee_id:assignee,due_at:due?new Date(due).toISOString():null,blocks_finalize:confirm('该问题未解决时是否阻止最终定稿？')};
    }
    try{await operationsApi.reviewAction(projectId,action,note,extra);setReview(await operationsApi.projectReviews(projectId));setSnapshots(await productionApi.snapshots(projectId));await load();}
    catch(err:any){setError(err?.response?.data?.detail||'审核操作未通过，请先处理页面中标记的问题。');}
  }

  return <div className="max-w-7xl mx-auto space-y-6 animate-fade-in pb-16">
    <header className="flex items-start justify-between gap-5">
      <div><Link to="/creative-projects" className="text-xs text-[var(--muted)] flex items-center gap-1 mb-3"><ArrowLeft size={13} />返回项目</Link><div className="text-xs font-medium text-[var(--accent)] mb-2">DETAIL PAGE AGENT</div><h1 className="font-display text-4xl">详情页策划与 Storyboard</h1><p className="text-sm text-[var(--muted)] mt-2">AI先规划整套详情页，再逐屏确认视觉方向；无需从空白画布开始。</p></div>
      <div className="flex gap-2"><button className="btn-secondary shrink-0" onClick={()=>setShowStyleBatch(true)} disabled={readyCount===0}><Palette size={15}/>整套风格</button><button className="btn-primary shrink-0" onClick={previewLongImage} disabled={exporting || readyCount === 0}>{exporting ? <Loader2 size={15} className="animate-spin" /> : <Eye size={15} />}预览整套详情页</button><Link to={`/creative-projects/${projectId}`} className="btn-secondary shrink-0"><WandSparkles size={15} />高级画布</Link></div>
    </header>

    {error && <div className="rounded-xl bg-red-50 border border-red-100 px-4 py-3 text-sm text-red-700">{error}</div>}
    {qualitySummary&&<section className="panel p-4"><div className="flex flex-wrap items-center gap-3"><div className={`w-12 h-12 rounded-full grid place-items-center font-semibold ${qualitySummary.status==='passed'?'bg-emerald-50 text-emerald-800':'bg-amber-50 text-amber-800'}`}>{qualitySummary.score}</div><div className="flex-1"><div className="font-medium">整套详情页质量稳定性</div><div className="text-xs text-[var(--muted)] mt-1">已评分 {qualitySummary.scored_count}/{qualitySummary.module_count} 屏 · {qualitySummary.status==='passed'?'可进入审核':'存在需修正的低质量页面'}</div></div></div>{qualitySummary.issues.length>0&&<div className="mt-3 space-y-2">{qualitySummary.issues.map((issue,index)=><div key={`${issue.module_id}-${index}`} className="rounded-lg bg-red-50 text-red-800 p-3 text-xs"><b>{issue.message}</b><span className="ml-2">{issue.suggestion}</span></div>)}</div>}</section>}
    <section className="panel p-4 flex flex-wrap items-end gap-3"><label className="text-xs">商品锁定强度<select className="input block mt-1" value={productLock} onChange={event=>setProductLock(event.target.value as typeof productLock)}><option value="strict">严格保持（推荐）</option><option value="balanced">允许轻微调整</option><option value="creative">创意重构</option></select></label><label className="text-xs">候选图差异<select className="input block mt-1" value={variationAxis} onChange={event=>setVariationAxis(event.target.value as typeof variationAxis)}><option value="composition">构图差异</option><option value="scene">场景差异</option><option value="color">色调差异</option><option value="model">模特差异</option><option value="lighting">光影差异</option></select></label><div className="text-xs text-[var(--muted)] flex-1">先用预览级多候选确认方向，选中后再单独进行高清交付和二次质检。</div><button className="btn-secondary" onClick={async()=>setRegression(await creativeApi.qualityRegression(projectId))}>运行质量回归</button>{regression&&<span className={`text-xs rounded-full px-3 py-2 ${regression.status==='passed'?'bg-emerald-50 text-emerald-800':'bg-red-50 text-red-800'}`}>{regression.passed}/{regression.case_count} 通过</span>}</section>
    {review&&<section className="panel p-4 flex flex-wrap items-center gap-3"><div className="flex-1"><div className="font-medium">项目审核 · 第 {review.round} 轮</div><div className="text-xs text-[var(--muted)] mt-1">当前状态：{({draft:'设计中',submitted:'待运营审核',changes_requested:'已驳回待修改',operational_approved:'运营已通过，待负责人定稿',finalized:'已定稿锁定'} as Record<string,string>)[review.status]||review.status}</div></div>{review.status==='draft'&&<button className="btn-primary" onClick={()=>actReview('submit')}>设计师提交并冻结快照</button>}{review.status==='changes_requested'&&<button className="btn-primary" onClick={()=>actReview('resubmit')}>修改后重新提交</button>}{review.status==='submitted'&&<><button className="btn-primary" onClick={()=>actReview('approve')}>运营审核通过</button><button className="btn-secondary text-red-700" onClick={()=>actReview('reject')}>驳回修改</button></>}{review.status==='operational_approved'&&<><button className="btn-primary" onClick={()=>actReview('finalize')}>负责人定稿并锁定</button><button className="btn-secondary text-red-700" onClick={()=>actReview('reject')}>退回修改</button></>}{review.history.length>0&&<details className="w-full text-xs"><summary className="cursor-pointer text-[var(--accent)]">审核记录（{review.history.length}）</summary><div className="mt-2 space-y-1">{review.history.map(h=><div key={h.id}>{new Date(h.created_at).toLocaleString()} · {h.actor_role} · {h.action}{h.note?`：${h.note}`:''}</div>)}</div></details>}{snapshots.length>0&&<details className="w-full text-xs"><summary className="cursor-pointer text-[var(--accent)]">提交快照与版本差异（{snapshots.length}）</summary><div className="mt-2 space-y-2">{snapshots.map(s=><div className="rounded-lg bg-[var(--bg-elevated)] p-3" key={s.id}><b>v{s.version} · {s.trigger}</b><span className="ml-2 text-[var(--muted)]">{new Date(s.created_at).toLocaleString()} · {s.diff.change_count} 项变化</span>{s.diff.changes.length>0&&<pre className="mt-2 whitespace-pre-wrap text-[10px]">{JSON.stringify(s.diff.changes,null,2)}</pre>}</div>)}</div></details>}</section>}

    {approvalIssues.length>0&&<section className="panel p-5"><h2 className="font-medium">驳回修改与前后版对比</h2><div className="mt-4 grid lg:grid-cols-2 gap-4">{approvalIssues.map(issue=>{const module=modules.find(item=>item.id===issue.module_id);const currentId=issue.resolved_node_id||module?.preview_node_id||null;const before=issue.source_node_id?nodes[issue.source_node_id]:null;const after=currentId?nodes[currentId]:null;return <div key={issue.id} className="rounded-xl border border-[var(--border)] p-3"><div className="flex items-center justify-between gap-2 text-xs"><b>{module?.title||`模块 ${issue.module_id}`} · {issue.issue_type}</b><span className={`rounded-full px-2 py-1 ${issue.status==='resolved'?'bg-emerald-50 text-emerald-800':'bg-amber-50 text-amber-800'}`}>{issue.status==='resolved'?'已解决':'待修改'}</span></div><div className="grid grid-cols-2 gap-2 mt-3">{[[before,'驳回版'],[after,'修改版']].map(([node,label])=><div key={String(label)}><div className="aspect-[3/4] rounded-lg bg-[#f1efe9] overflow-hidden grid place-items-center">{(node as CanvasNodeRecord|null)?.data.image_url?<img src={mediaUrl(String((node as CanvasNodeRecord).data.image_url))} className="w-full h-full object-cover"/>:<span className="text-[10px] text-[var(--muted)]">待产生</span>}</div><div className="text-center text-[10px] text-[var(--muted)] mt-1">{String(label)}</div></div>)}</div>{issue.status!=='resolved'&&currentId&&currentId!==issue.source_node_id&&<button className="btn-primary w-full justify-center mt-3" onClick={async()=>{await creativeApi.resolveIssue(projectId,issue.id,currentId);await load()}}><Check size={14}/>确认修改版已解决</button>}</div>})}</div></section>}

    {approvalIssues.some(issue=>issue.status==='open'&&issue.region&&issue.region.width>0)&&<section className="panel p-4"><div className="font-medium">框选局部重绘</div><div className="mt-3 flex flex-wrap gap-2">{approvalIssues.filter(issue=>issue.status==='open'&&issue.region&&issue.region.width>0).map(issue=><button key={issue.id} className="btn-primary" onClick={async()=>{setError('');try{await creativeApi.regionalRegenerate(projectId,issue.id);await load()}catch(err:any){const detail=err?.response?.data?.detail;setError(typeof detail==='string'?detail:(detail?.message||'局部重绘失败'))}}}><WandSparkles size={14}/>执行 {modules.find(module=>module.id===issue.module_id)?.title} 局部重绘</button>)}</div></section>}

    {review?.status==='submitted'&&<div className="flex justify-end"><button className="btn-secondary text-amber-800" onClick={()=>actReview('approve_conditional')}>有条件通过（保留小修改项）</button></div>}

    <section className="grid lg:grid-cols-[1fr_1.2fr] gap-5">
      <div className="panel p-5"><div className="flex items-center gap-2 font-medium"><Sparkles size={17} className="text-[var(--accent)]" />AI商品理解</div><div className="grid grid-cols-2 gap-x-5 gap-y-4 mt-5 text-sm">{[
        ['商品', understanding.name], ['品牌', understanding.brand], ['品类', understanding.category], ['商品原图', `${understanding.image_count || 0} 张`],
      ].map(([label, value]) => <div key={String(label)}><div className="text-[11px] text-[var(--muted)]">{String(label)}</div><div className="mt-1 font-medium">{String(value || '待补充')}</div></div>)}</div><div className="mt-5 pt-4 border-t border-[var(--border)]"><div className="text-[11px] text-[var(--muted)]">目标用户</div><p className="text-sm leading-6 mt-1">{String(understanding.target_users || '待补充')}</p><div className="text-[11px] text-[var(--muted)] mt-3">商品价值</div><p className="text-sm leading-6 mt-1">{String(understanding.core_value || '待补充')}</p></div></div>
      <div className="panel p-5"><div className="flex items-center gap-2 font-medium"><Check size={17} className="text-[var(--accent)]" />AI详情页策略</div><p className="mt-4 text-sm leading-7">{String(strategy.narrative || '')}</p><div className="rounded-xl bg-[#f3f6f4] p-4 mt-4 text-xs leading-6 text-[#4f625c]">视觉规则：{String(strategy.visual_tone || '')}</div><div className="flex flex-wrap gap-2 mt-4"><span className="rounded-full bg-[#f1eee8] px-3 py-1.5 text-xs">{project.platform}</span><span className="rounded-full bg-[#f1eee8] px-3 py-1.5 text-xs">建议 {modules.length} 屏</span>{Array.isArray(strategy.matched_skills) && strategy.matched_skills.map((skill) => <span key={String(skill)} className="rounded-full bg-emerald-50 text-emerald-800 px-3 py-1.5 text-xs">Skill · {String(skill)}</span>)}</div></div>
    </section>

    <section className="panel overflow-hidden">
      <div className="p-5 border-b border-[var(--border)] flex flex-wrap items-center justify-between gap-4"><div><h2 className="font-medium text-lg">详情页 Storyboard</h2><p className="text-xs text-[var(--muted)] mt-1">先调整模块和叙事顺序，再逐屏生成预览。已完成 {readyCount}/{modules.length}</p>{batchRunning && <div className="mt-3 w-72 max-w-full"><div className="flex justify-between text-[10px] text-[var(--muted)] mb-1"><span>正在生成整套详情页</span><span>{batchCompleted}/{batchTotal}</span></div><div className="h-1.5 rounded-full bg-[#e8e5de] overflow-hidden"><div className="h-full bg-[var(--accent)] transition-all" style={{ width: `${batchTotal ? batchCompleted / batchTotal * 100 : 0}%` }} /></div></div>}</div><div className="flex flex-wrap gap-2"><button className="btn-secondary" onClick={addModule} disabled={plan.status !== 'draft' || batchRunning}><Plus size={14} />增加模块</button>{plan.status === 'draft' && <button className="btn-primary" disabled={saving} onClick={confirmPlan}>{saving ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />}确认详情页策划</button>}{plan.status !== 'draft' && !batchRunning && readyCount < modules.length && <button className="btn-primary" onClick={() => generateAllPending(false)}><Play size={14} />一键生成剩余 {modules.length - readyCount} 屏</button>}{batchRunning && <button className="btn-secondary" onClick={stopBatch}><CircleStop size={14} />生成完当前屏后停止</button>}{!batchRunning && failedIds.length > 0 && <button className="btn-secondary text-red-700" onClick={() => generateAllPending(true)}><RefreshCw size={14} />重试失败模块 ({failedIds.length})</button>}</div></div>
      <div className="divide-y divide-[var(--border)]">{modules.map((module, index) => { const preview = module.preview_node_id ? nodes[module.preview_node_id] : null; const context = preview?.data.context_summary as { material_strategy?: string; materials?: Array<{ id: string; label?: string; role?: string; reason?: string }> } | undefined; const quality=preview?.data.quality_scores as {total:number;product_consistency:number;brand_match:number;commercial_aesthetic:number;recommendation:string}|undefined; const materials = context?.materials || []; const versions = Object.values(nodes).filter((node) => Number(node.data.storyboard_module_id) === module.id).sort((left, right) => String(left.created_at || '').localeCompare(String(right.created_at || ''))); const generating = generatingId === module.id || (batchRunning && batchJob?.current_module_id === module.id); return <article id={`module-${module.id}`} key={module.id} className="grid lg:grid-cols-[70px_250px_1fr_210px] gap-4 p-5 items-start scroll-mt-6">
        <div className="flex lg:flex-col items-center gap-2"><span className="w-10 h-10 rounded-full bg-[#e8f2ef] text-[var(--accent)] grid place-items-center font-medium">{String(index + 1).padStart(2, '0')}</span><div className="flex lg:flex-col"><button className="p-1 text-[var(--muted)] disabled:opacity-25" disabled={index === 0 || plan.status !== 'draft'} onClick={() => moveModule(index, -1)}><ArrowUp size={15} /></button><button className="p-1 text-[var(--muted)] disabled:opacity-25" disabled={index === modules.length - 1 || plan.status !== 'draft'} onClick={() => moveModule(index, 1)}><ArrowDown size={15} /></button></div></div>
        <div><div className={`aspect-[3/4] rounded-xl bg-[#f1efe9] border border-[var(--border)] overflow-hidden grid place-items-center relative ${markingModule===module.id?'cursor-crosshair':''}`} onMouseDown={event=>{if(markingModule!==module.id)return;const p=point(event);setDragStart(p);setMarkedRegion({x:p.x,y:p.y,width:0,height:0})}} onMouseMove={event=>{if(markingModule!==module.id||!dragStart)return;const p=point(event);setMarkedRegion({x:Math.min(p.x,dragStart.x),y:Math.min(p.y,dragStart.y),width:Math.abs(p.x-dragStart.x),height:Math.abs(p.y-dragStart.y)})}} onMouseUp={()=>setDragStart(null)}>{preview?.data.image_url ? <img src={mediaUrl(String(preview.data.image_url))} className="w-full h-full object-cover pointer-events-none" /> : generating ? <div className="text-center text-xs text-[var(--muted)] px-5"><Loader2 className="animate-spin mx-auto mb-3 text-[var(--accent)]" />{module.production_method === 'template' ? '正在快速排版' : 'Seedream正在生成'}<br />{module.production_method === 'template' ? '通常几秒完成' : '通常需要1–2分钟'}</div> : <div className="text-center text-xs text-[var(--muted)]"><ImageIcon size={22} className="mx-auto mb-2 opacity-50" />等待生成视觉预览</div>}{markingModule===module.id&&markedRegion&&<div className="absolute border-2 border-red-500 bg-red-500/15 pointer-events-none" style={{left:`${markedRegion.x*100}%`,top:`${markedRegion.y*100}%`,width:`${markedRegion.width*100}%`,height:`${markedRegion.height*100}%`}}/>}<span className="absolute top-2 left-2 rounded-full bg-white/90 px-2 py-1 text-[10px]">{METHOD_LABELS[module.production_method] || module.production_method}</span><span className="absolute top-2 right-2 rounded-full bg-white/90 px-2 py-1 text-[10px]">{module.status === 'approved' ? '已确认' : preview ? '待确认' : '待生成'}</span></div>{versions.length > 1 && <div className="mt-2 flex items-center gap-1.5 overflow-x-auto pb-1"><span className="text-[10px] text-[var(--muted)] shrink-0">版本</span>{versions.map((version, versionIndex) => <button key={version.id} title={`${version.data.auto_shortlisted?'自动入选 · ':''}切换至版本 ${versionIndex + 1}`} onClick={() => selectVersion(module, version.id)} className={`w-7 h-7 rounded-md text-[10px] border shrink-0 ${module.preview_node_id === version.id ? 'bg-[var(--accent)] text-white border-[var(--accent)]' : version.data.auto_shortlisted?'bg-emerald-50 border-emerald-300':'bg-white border-[var(--border)]'}`}>{versionIndex + 1}</button>)}</div>}</div>
        <div className="space-y-3"><div className="flex items-center gap-2"><input className="input font-medium flex-1" value={module.title} disabled={plan.status !== 'draft'} onChange={(event) => updateModule(module.id, { title: event.target.value })} />{module.required && <span className="text-[10px] rounded-full bg-amber-50 text-amber-800 px-2 py-1">推荐保留</span>}</div><div><div className="text-[11px] text-[var(--muted)] mb-1">本屏要解决什么</div><textarea className="input w-full min-h-16 resize-none text-sm" value={module.objective} disabled={plan.status !== 'draft'} onChange={(event) => updateModule(module.id, { objective: event.target.value })} /></div><div><div className="text-[11px] text-[var(--muted)] mb-1">内容依据</div><p className="text-xs leading-5 text-[#646159]">{module.content_guidance || '待补充'}</p></div><div><div className="text-[11px] text-[var(--muted)] mb-1">视觉方向</div><p className="text-xs leading-5 text-[#646159]">{module.visual_direction}</p></div>{materials.length > 0 && <div className="rounded-xl bg-[#f4f7f5] p-3"><div className="text-[11px] font-medium text-[#35584d]">智能素材依据</div><p className="text-[10px] text-[var(--muted)] mt-1">{context?.material_strategy}</p><div className="flex flex-wrap gap-1.5 mt-2">{materials.map((material) => <span key={material.id} title={material.reason} className="rounded-full bg-white border border-[#dce7e1] px-2 py-1 text-[10px]">{material.label || material.role} · {material.role}</span>)}</div></div>}</div>
        <div className="space-y-2"><button className="btn-primary w-full justify-center" disabled={generating || batchRunning || plan.status === 'draft'} onClick={() => generatePreview(module)}>{generating ? <Loader2 size={14} className="animate-spin" /> : preview ? <RefreshCw size={14} /> : <Sparkles size={14} />}{preview ? '换一个方向' : module.production_method === 'template' ? '快速生成排版' : '生成本屏预览'}</button>{quality&&<div className={`rounded-lg p-2 text-[10px] ${quality.total>=82?'bg-emerald-50 text-emerald-800':quality.total>=65?'bg-amber-50 text-amber-800':'bg-red-50 text-red-800'}`}><b>质量 {quality.total}</b><div className="grid grid-cols-3 mt-1"><span>商品 {quality.product_consistency}</span><span>品牌 {quality.brand_match}</span><span>审美 {quality.commercial_aesthetic}</span></div></div>}{failedIds.includes(module.id) && <div className="rounded-lg bg-red-50 text-red-700 px-3 py-2 text-[10px] text-center">本屏上次生成失败</div>}{preview && <button className="btn-secondary w-full justify-center" onClick={() => openQuickEdit(module)}><SlidersHorizontal size={14} />快速编辑</button>}{preview&&quality?.recommendation!=='accept'&&<button className="btn-secondary w-full justify-center" onClick={async()=>{setGeneratingId(module.id);try{await creativeApi.retryByQuality(projectId,preview.id);await load()}finally{setGeneratingId(null)}}}><RefreshCw size={14}/>按质检建议重试</button>}{preview&&<button className="btn-secondary w-full justify-center text-red-700" onClick={async()=>{const issue=prompt('驳回原因：商品变形 / 包装文字错误 / 品牌不符 / 构图不好 / 光影不自然 / 质感不足 / 卖点不突出 / 页面重复','商品变形');if(!issue)return;await creativeApi.rejectModule(projectId,module.id,{issue_type:issue,severity:['商品变形','包装文字错误'].includes(issue)?'high':'medium',action:'regenerate',note:''});updateModule(module.id,{status:'needs_revision'})}}>驳回并创建修改任务</button>}{preview && <button className="btn-secondary w-full justify-center" onClick={() => selectVersion(module, preview.id, true)}><Check size={14} />{module.status === 'approved' ? '已确认并保存' : '确认当前版本'}</button>}{versions.length > 1 && <div className="text-center text-[10px] text-[var(--muted)]">共 {versions.length} 个历史版本，可随时切换</div>}{plan.status === 'draft' && !module.required && <button className="w-full text-xs text-red-600 py-2 flex items-center justify-center gap-1" onClick={() => setModules((current) => current.filter((item) => item.id !== module.id))}><Trash2 size={13} />删除模块</button>}</div>
        {preview&&<div className="lg:col-start-4 space-y-2"><button className={`btn-secondary w-full justify-center text-red-700 ${markingModule===module.id?'ring-2 ring-red-300':''}`} onClick={async()=>{if(markingModule!==module.id){setMarkingModule(module.id);setMarkedRegion(null);return}const issue=prompt('请填写框选区域的问题','商品变形');if(!issue)return;await creativeApi.rejectModule(projectId,module.id,{issue_type:issue,severity:['商品变形','包装文字错误'].includes(issue)?'high':'medium',action:'regional_regenerate',note:'审核人已框选问题区域',region:markedRegion||undefined});setMarkingModule(null);setMarkedRegion(null);await load()}}>{markingModule===module.id?'确认框选并提交':'框选区域驳回'}</button><button className="btn-secondary w-full justify-center" onClick={async()=>{setGeneratingId(module.id);try{const node=await creativeApi.finalizeHd(projectId,preview.id);setNodes(current=>({...current,[node.id]:node}));updateModule(module.id,{preview_node_id:node.id,final_node_id:node.id,status:'approved'});setQualitySummary(await creativeApi.qualitySummary(projectId))}catch(err:any){setError(err?.response?.data?.detail?.message||err?.response?.data?.detail||'高清交付质检未通过')}finally{setGeneratingId(null)}}}><Download size={14}/>高清交付并二次质检</button></div>}
      </article>; })}</div>
      <div className="p-5 bg-[#f7f5f0] flex items-center justify-between"><div className="text-xs text-[var(--muted)]">确认所有核心模块后，可进入高级画布继续自由探索、精修与交付。</div><Link to={`/creative-projects/${projectId}`} className="btn-secondary">高级画布<ArrowRight size={14} /></Link></div>
    </section>
    {exportResult && <div className="fixed inset-0 z-50 bg-black/55 p-5 overflow-auto" onClick={() => setExportResult(null)}><div className="max-w-4xl mx-auto bg-white rounded-2xl overflow-hidden" onClick={(event) => event.stopPropagation()}><div className="sticky top-0 bg-white/95 backdrop-blur border-b border-[var(--border)] p-4 flex items-center justify-between z-10"><div><div className="font-medium">整套详情页预览</div><div className="text-xs text-[var(--muted)] mt-1">已合成 {exportResult.module_count} 个模块{exportResult.missing_modules.length > 0 ? `，另有 ${exportResult.missing_modules.length} 个待生成` : ''}</div></div><div className="flex gap-2"><a className="btn-primary" href={mediaUrl(exportResult.long_image_url)} download><Download size={14} />下载长图</a><button className="btn-secondary" onClick={() => setExportResult(null)}><X size={14} />关闭</button></div></div><div className="bg-[#e9e7e1] p-6"><img src={mediaUrl(exportResult.long_image_url)} className="w-full max-w-[750px] mx-auto shadow-xl" /></div>{exportResult.missing_modules.length > 0 && <div className="p-4 text-xs text-amber-800 bg-amber-50">待生成模块：{exportResult.missing_modules.join('、')}</div>}</div></div>}
    {editingModule?.preview_node_id && <div className="fixed inset-0 z-50 bg-black/55 p-5 overflow-auto" onClick={() => setEditingModule(null)}><div className="max-w-5xl mx-auto bg-white rounded-2xl overflow-hidden grid lg:grid-cols-[1fr_380px]" onClick={(event) => event.stopPropagation()}><div className="bg-[#e8e6e0] p-6 grid place-items-center"><img src={mediaUrl(String(nodes[editingModule.preview_node_id]?.data.image_url || ''))} className="max-h-[78vh] shadow-xl" /></div><div className="p-6 space-y-5"><div className="flex justify-between"><div><h3 className="font-medium text-lg">快速编辑 · {editingModule.title}</h3><p className="text-xs text-[var(--muted)] mt-1">不调用模型，保存后自动成为新版本。</p></div><button onClick={() => setEditingModule(null)}><X size={18} /></button></div><label className="block text-sm">主标题<input className="input w-full mt-2" value={editValues.headline} onChange={(event) => setEditValues({ ...editValues, headline: event.target.value })} /></label><label className="block text-sm">副标题<input className="input w-full mt-2" placeholder="可选" value={editValues.subtitle} onChange={(event) => setEditValues({ ...editValues, subtitle: event.target.value })} /></label>{[['画面缩放', 'zoom', 1, 2, 0.05], ['水平位置', 'offset_x', -1, 1, 0.05], ['垂直位置', 'offset_y', -1, 1, 0.05]].map(([label, key, min, max, step]) => <label key={String(key)} className="block text-sm">{String(label)}<div className="flex items-center gap-3 mt-2"><input type="range" className="flex-1" min={Number(min)} max={Number(max)} step={Number(step)} value={editValues[key as keyof typeof editValues] as number} onChange={(event) => setEditValues({ ...editValues, [key as string]: Number(event.target.value) })} /><span className="text-xs w-10 text-right">{Number(editValues[key as keyof typeof editValues]).toFixed(2)}</span></div></label>)}<div className="rounded-xl bg-amber-50 text-amber-800 p-3 text-xs">快速编辑会将文案覆盖到图片底部；原图不会被覆盖，可在版本列表随时切回。</div><button className="btn-primary w-full justify-center" onClick={applyQuickEdit} disabled={applyingEdit}>{applyingEdit ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}保存为新版本</button></div></div></div>}
    {complianceReport && <ComplianceModal report={complianceReport} loading={exporting} onClose={() => setComplianceReport(null)} onContinue={confirmComplianceAndPreview} />}
    {showStyleBatch && <StyleBatchModal versions={((strategy.style_versions as StyleVersion[] | undefined) || [])} onClose={()=>setShowStyleBatch(false)} onApply={applyStyle} onRollback={rollbackStyle}/>}
    {directEditingModule?.preview_node_id && <DirectEditModal imageUrl={mediaUrl(String(nodes[directEditingModule.preview_node_id]?.data.image_url || ''))} title={directEditingModule.title} materials={Object.values(nodes).filter(node=>['product','product_image','reference','brand_asset','detail_image'].includes(node.node_type)&&Boolean(node.data.image_url)).map(node=>({id:node.id,imageUrl:mediaUrl(String(node.data.image_url)),label:String(node.data.label||'素材')}))} onClose={()=>setDirectEditingModule(null)} onSave={saveDirectEdit}/>}
  </div>;
}
