import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  ArrowLeft,
  Loader2,
  RefreshCw,
  Sparkles,
  Users,
  CheckCircle2,
  XCircle,
  Clock,
  History,
  ArrowUp,
  ArrowDown,
  Save,
  Download,
  Printer,
  ShieldCheck,
  Database,
  FileText,
  Image as ImageIcon,
  Palette,
  Timer,
  Check,
  Wrench,
  X,
  Award,
} from 'lucide-react';
import { apiUrl, generationApi, mediaUrl } from '../api/client';
import type { EditHistory, Generation, ImageReview, LearnedDesignProfile } from '../types';
import { SECTION_LABELS } from '../types';

const AGENT_STEPS = [
  { key: 'product_understanding', label: '商品理解 Agent' },
  { key: 'consumer_analysis', label: '消费者分析 Agent' },
  { key: 'marketing_strategy', label: '营销策略 Agent' },
  { key: 'detail_page', label: '详情页生成 Agent' },
];

const REVIEW_REASONS = ['商品变形', '包装文字错误', '不符合品牌调性', '构图不好', '色彩不合适', '质感不足', '卖点不突出', '内容违规'];
const REVIEW_LABELS: Record<string, string> = { usable: '可使用', needs_edit: '需修改', rejected: '不可使用', final: '最终采用' };

export default function GenerationEditor() {
  const { id } = useParams();
  const generationId = Number(id);

  const [gen, setGen] = useState<Generation | null>(null);
  const [edits, setEdits] = useState<EditHistory[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState('');
  const [view, setView] = useState<'visual' | 'preview' | 'markdown' | 'basis' | 'agents'>('visual');
  const [activeSection, setActiveSection] = useState('title');
  const [moduleDrafts, setModuleDrafts] = useState<Record<string, string>>({});
  const [moduleOrder, setModuleOrder] = useState<string[]>(Object.keys(SECTION_LABELS));
  const [imageReviews, setImageReviews] = useState<ImageReview[]>([]);
  const [learnedProfile, setLearnedProfile] = useState<LearnedDesignProfile | null>(null);
  const [reviewDraft, setReviewDraft] = useState<{ moduleKey: string; status: 'needs_edit' | 'rejected'; reasons: string[] } | null>(null);

  const refresh = useCallback(async () => {
    const g = await generationApi.get(generationId);
    setGen(g);
    if (g.status === 'completed' && g.detail_page_sections) {
      const raw = g.detail_page_sections;
      const drafts = Object.fromEntries(
        Object.keys(SECTION_LABELS).map((key) => [key, typeof raw[key] === 'string' ? raw[key] : '']),
      );
      const savedOrder = Array.isArray(raw._module_order)
        ? raw._module_order.filter((key): key is string => typeof key === 'string')
        : Object.keys(SECTION_LABELS);
      setModuleDrafts(drafts);
      setModuleOrder(savedOrder);
    }
    if (g.status === 'completed') {
      const [e, reviews, profile] = await Promise.all([
        generationApi.edits(generationId),
        generationApi.imageReviews(generationId),
        generationApi.learnedProfile(g.product_id),
      ]);
      setEdits(e); setImageReviews(reviews); setLearnedProfile(profile);
    }
    return g;
  }, [generationId]);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;

    (async () => {
      try {
        const g = await refresh();
        if (cancelled) return;
        if (g.status === 'pending' || g.status === 'running') {
          timer = window.setInterval(async () => {
            try {
              const latest = await refresh();
              if (latest.status === 'completed' || latest.status === 'failed') {
                window.clearInterval(timer);
              }
            } catch (e) {
              console.error(e);
            }
          }, 2000);
        }
      } catch (e) {
        console.error(e);
        if (!cancelled) setError('加载失败');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
      if (timer) window.clearInterval(timer);
    };
  }, [refresh]);

  const markdown = useMemo(() => gen?.detail_page_markdown || '', [gen]);

  async function runEdit(payload: Parameters<typeof generationApi.edit>[1]) {
    setEditing(true);
    setError('');
    try {
      const updated = await generationApi.edit(generationId, payload);
      setGen(updated);
      const e = await generationApi.edits(generationId);
      setEdits(e);
    } catch (err) {
      console.error(err);
      setError('编辑失败，请检查 LLM 配置或稍后重试');
    } finally {
      setEditing(false);
    }
  }

  function moveModule(key: string, direction: -1 | 1) {
    setModuleOrder((current) => {
      const index = current.indexOf(key);
      const nextIndex = index + direction;
      if (index < 0 || nextIndex < 0 || nextIndex >= current.length) return current;
      const next = [...current];
      [next[index], next[nextIndex]] = [next[nextIndex], next[index]];
      return next;
    });
  }

  async function saveModules() {
    setEditing(true);
    setError('');
    try {
      const updated = await generationApi.updateModules(generationId, moduleDrafts, moduleOrder);
      setGen(updated);
      setEdits(await generationApi.edits(generationId));
    } catch (err) {
      console.error(err);
      setError('模块保存失败');
    } finally {
      setEditing(false);
    }
  }

  async function retryGeneration() {
    setEditing(true);
    setError('');
    try {
      await generationApi.retry(generationId);
      window.location.reload();
    } catch (err) {
      console.error(err);
      setError('任务重试失败');
      setEditing(false);
    }
  }

  async function submitImageReview(moduleKey: string, status: ImageReview['status'], reasons: string[] = []) {
    setEditing(true); setError('');
    try {
      const review = await generationApi.reviewImage(generationId, moduleKey, { status, reasons });
      setImageReviews((current) => [...current.filter((item) => item.module_key !== moduleKey), review]);
      setReviewDraft(null);
      let attempts = 0;
      const timer = window.setInterval(async () => {
        attempts += 1;
        try {
          const [reviews, profile] = await Promise.all([
            generationApi.imageReviews(generationId),
            generationApi.learnedProfile(gen.product_id),
          ]);
          setImageReviews(reviews); setLearnedProfile(profile);
          const current = reviews.find((item) => item.module_key === moduleKey);
          if (current?.learning_status === 'completed' || current?.learning_status === 'failed' || attempts >= 20) window.clearInterval(timer);
        } catch { if (attempts >= 20) window.clearInterval(timer); }
      }, 3000);
    } catch (err) {
      console.error(err); setError('图片评价保存失败');
    } finally { setEditing(false); }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-[var(--muted)]">
        <Loader2 className="animate-spin mr-2" size={20} /> 加载中…
      </div>
    );
  }

  if (!gen) {
    return <div className="text-[var(--muted)]">记录不存在</div>;
  }

  const isRunning = gen.status === 'pending' || gen.status === 'running';
  const agentResults = (gen.agent_results || {}) as Record<string, unknown>;
  const qualityCheck = agentResults.quality_check as
    | { score: number; passed: boolean; warnings: Array<{ message: string }>; disclaimer: string; fact_coverage?: { ingredients?: { provided: string[]; matched: string[]; not_mentioned: string[]; status: string } } }
    | undefined;
  const visualModules = (agentResults.visual_modules || []) as Array<{
    key: string; title: string; image_url: string; status: string;
  }>;
  const longImageUrl = agentResults.long_image_url as string | undefined;
  const executionTrace = agentResults.execution_trace as {
    status?: string; current_stage?: string | null; total_duration_ms?: number;
    steps?: Array<{ key: string; label?: string; status: string; duration_ms: number }>;
  } | undefined;
  const generationBasis = agentResults.generation_basis as {
    product?: { id: number; name: string; brand_name: string; category: string; fields_used: Array<{ name: string; value: string }> };
    assets?: { product_images: string[]; detail_images: string[]; files: Array<{ id: number; name: string; type: string; url: string }> };
    brand_documents?: Array<{ id: number; title: string; brand_name: string; chunks: number }>;
    rag?: { method: string; hits: Array<{ document_title: string; doc_type: string; scope: string; chunk_index: number; score: number | null; excerpt: string }> };
    skill_chain?: Array<{ level: string; name: string; primary_color?: string; accent_color?: string; design_principles?: string; visual_rules?: string; copy_rules?: string; negative_rules?: string }>;
  } | undefined;

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center gap-3 text-sm text-[var(--muted)]">
        <Link
          to={`/products/${gen.product_id}`}
          className="inline-flex items-center gap-1 hover:text-[var(--text)]"
        >
          <ArrowLeft size={16} /> 返回商品
        </Link>
      </div>

      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl tracking-tight">详情页编辑器</h1>
          <p className="mt-1 text-sm text-[var(--muted)] flex items-center gap-2">
            生成记录 #{gen.id}
            <StatusPill status={gen.status} />
          </p>
        </div>
        <div className="no-print flex flex-wrap gap-2">
          {gen.status === 'completed' && (
            <>
              <a className="btn-secondary inline-flex items-center gap-2" href={apiUrl(`/generations/${gen.id}/export/markdown`)}>
                <Download size={14} /> Markdown
              </a>
              <button className="btn-primary inline-flex items-center gap-2" onClick={() => window.print()}>
                <Printer size={14} /> 导出 PDF
              </button>
            </>
          )}
          <div className="flex gap-1 p-1 rounded-lg bg-[var(--bg-elevated)] border border-[var(--border)]">
          {(
            [
              ['visual', '视觉详情页'],
              ['preview', '文案模块'],
              ['markdown', 'Markdown'],
              ['basis', '生成依据'],
              ['agents', 'Agent 结果'],
            ] as const
          ).map(([k, label]) => (
            <button
              key={k}
              className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
                view === k ? 'bg-white shadow-sm text-[var(--text)]' : 'text-[var(--muted)]'
              }`}
              onClick={() => setView(k)}
            >
              {label}
            </button>
          ))}
          </div>
        </div>
      </header>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 text-red-700 px-4 py-3 text-sm">
          {error}
        </div>
      )}

      {isRunning && (
        <div className="panel p-6">
          <div className="flex items-center gap-2 mb-4">
            <Loader2 className="animate-spin text-[var(--accent)]" size={18} />
            <span className="font-medium">多模态 Agent Workflow 执行中…</span>
          </div>
          <ol className="space-y-3">
            {AGENT_STEPS.map((step, i) => (
              <li key={step.key} className="flex items-center gap-3 text-sm">
                <span className="w-6 h-6 rounded-full bg-[var(--accent-soft)] text-[var(--accent)] flex items-center justify-center text-xs font-medium">
                  {i + 1}
                </span>
                <span>{step.label}</span>
                <span className="text-[var(--muted)] text-xs">
                  {executionTrace?.steps?.some((item) => item.key === step.key)
                    ? '已完成'
                    : executionTrace?.current_stage === step.key ? '处理中…' : '等待中'}
                </span>
              </li>
            ))}
          </ol>
        </div>
      )}

      {gen.status === 'failed' && (
        <div className="rounded-xl border border-red-200 bg-red-50 text-red-700 px-5 py-4">
          生成失败：{gen.error_message || '未知错误'}
          {gen.attempt_count < gen.max_attempts && (
            <button className="btn-secondary ml-3" disabled={editing} onClick={retryGeneration}>
              重试（{gen.attempt_count}/{gen.max_attempts}）
            </button>
          )}
        </div>
      )}

      {gen.status === 'completed' && (
        <div className="print-layout grid grid-cols-1 lg:grid-cols-[240px_1fr] gap-6">
          <aside className="no-print space-y-4">
            {qualityCheck && (
              <div className={`panel p-4 ${qualityCheck.passed ? 'border-green-200' : 'border-amber-300'}`}>
                <h3 className="font-medium flex items-center gap-2"><ShieldCheck size={15} /> 质量检查 {qualityCheck.score}分</h3>
                {qualityCheck.warnings.length > 0 ? (
                  <ul className="mt-2 text-xs text-amber-700 space-y-1">
                    {qualityCheck.warnings.map((warning, index) => <li key={index}>• {warning.message}</li>)}
                  </ul>
                ) : <p className="mt-2 text-xs text-green-700">未发现规则风险</p>}
                {qualityCheck.fact_coverage?.ingredients?.provided.length ? <div className="mt-3 text-[11px] space-y-1">
                  <div className="text-green-700">已覆盖：{qualityCheck.fact_coverage.ingredients.matched.join('、') || '无'}</div>
                  {qualityCheck.fact_coverage.ingredients.not_mentioned.length > 0 && <div className="text-[var(--muted)]">未提及：{qualityCheck.fact_coverage.ingredients.not_mentioned.join('、')}</div>}
                </div> : null}
                <p className="mt-2 text-[11px] text-[var(--muted)]">{qualityCheck.disclaimer}</p>
              </div>
            )}
            <div className="panel p-4 space-y-2">
              <h3 className="text-xs font-medium uppercase tracking-wider text-[var(--muted)] mb-2">
                模块操作
              </h3>
              <select
                className="input-select w-full"
                value={activeSection}
                onChange={(e) => setActiveSection(e.target.value)}
              >
                {Object.entries(SECTION_LABELS).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
              <button
                className="btn-secondary w-full justify-center inline-flex items-center gap-2"
                disabled={editing}
                onClick={() =>
                  runEdit({
                    action: 'regenerate_section',
                    section: activeSection,
                    instruction: `重新生成${SECTION_LABELS[activeSection]}`,
                  })
                }
              >
                {editing ? <Loader2 className="animate-spin" size={14} /> : <RefreshCw size={14} />}
                重新生成该模块
              </button>
            </div>

            <div className="panel p-4 space-y-2">
              <h3 className="text-xs font-medium uppercase tracking-wider text-[var(--muted)] mb-2">
                模块排序
              </h3>
              {moduleOrder.map((key, index) => (
                <div key={key} className="flex items-center justify-between gap-2 text-sm">
                  <button className="truncate hover:text-[var(--accent)]" onClick={() => setActiveSection(key)}>
                    {SECTION_LABELS[key] || key}
                  </button>
                  <div className="flex gap-1">
                    <button className="btn-secondary p-1" disabled={index === 0} onClick={() => moveModule(key, -1)}>
                      <ArrowUp size={12} />
                    </button>
                    <button className="btn-secondary p-1" disabled={index === moduleOrder.length - 1} onClick={() => moveModule(key, 1)}>
                      <ArrowDown size={12} />
                    </button>
                  </div>
                </div>
              ))}
              <button className="btn-primary w-full justify-center inline-flex items-center gap-2 mt-2" disabled={editing} onClick={saveModules}>
                <Save size={14} /> 保存模块组合
              </button>
            </div>

            <div className="panel p-4 space-y-2">
              <h3 className="text-xs font-medium uppercase tracking-wider text-[var(--muted)] mb-2">
                快捷优化
              </h3>
              <button
                className="btn-secondary w-full justify-center inline-flex items-center gap-2"
                disabled={editing}
                onClick={() =>
                  runEdit({
                    action: 'regenerate_section',
                    section: 'title',
                    instruction: '重新生成更吸引点击的电商标题',
                  })
                }
              >
                <RefreshCw size={14} /> 重新生成标题
              </button>
              <button
                className="btn-secondary w-full justify-center inline-flex items-center gap-2"
                disabled={editing}
                onClick={() =>
                  runEdit({
                    action: 'regenerate_section',
                    section: 'selling_points',
                    instruction: '优化卖点表达，更突出转化',
                  })
                }
              >
                <Sparkles size={14} /> 优化卖点
              </button>
              <button
                className="btn-secondary w-full justify-center inline-flex items-center gap-2"
                disabled={editing}
                onClick={() =>
                  runEdit({
                    action: 'optimize_tone',
                    instruction: '语气更专业、更有说服力、适合电商转化',
                  })
                }
              >
                <Sparkles size={14} /> 优化语气
              </button>
              <button
                className="btn-primary w-full justify-center inline-flex items-center gap-2"
                disabled={editing}
                onClick={() =>
                  runEdit({
                    action: 'change_audience',
                    target_audience: '年轻用户',
                  })
                }
              >
                <Users size={14} /> 更适合年轻用户
              </button>
            </div>

            {edits.length > 0 && (
              <div className="panel p-4">
                <h3 className="text-xs font-medium uppercase tracking-wider text-[var(--muted)] mb-3 flex items-center gap-1">
                  <History size={12} /> 修改记录
                </h3>
                <ul className="space-y-2 max-h-48 overflow-auto">
                  {edits.map((e) => (
                    <li key={e.id} className="text-xs text-[var(--muted)] border-b border-[var(--border)] pb-2">
                      <div className="text-[var(--text)] font-medium">
                        {e.action}
                        {e.section ? ` · ${SECTION_LABELS[e.section] || e.section}` : ''}
                      </div>
                      <div>{new Date(e.created_at).toLocaleString()}</div>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </aside>

          <div className="print-content panel overflow-hidden">
            {view === 'visual' ? (
              <div className="bg-[var(--bg-elevated)] p-5 min-h-[480px]">
                <div className="no-print mx-auto max-w-[750px] mb-4 rounded-xl border border-[var(--border)] bg-white p-4">
                  <div className="flex items-start justify-between gap-4">
                    <div><h3 className="font-medium">设计偏好自动学习</h3><p className="mt-1 text-xs text-[var(--muted)]">你只需要判断图片是否可用，系统会后台分析构图、色彩和风格，不要求审核 Skill。</p></div>
                    {learnedProfile ? <div className="text-right shrink-0"><div className="text-sm font-medium">{learnedProfile.sample_count} 个样本</div><div className="text-xs text-[var(--muted)]">置信度 {(learnedProfile.confidence * 100).toFixed(0)}% · {learnedProfile.status === 'stable' ? '稳定' : '观察中'}</div></div> : <span className="text-xs text-[var(--muted)] shrink-0">尚无样本</span>}
                  </div>
                </div>
                {longImageUrl && (
                  <div className="no-print flex justify-end mb-4">
                    <a className="btn-primary inline-flex items-center gap-2" href={mediaUrl(longImageUrl)} download>
                      <Download size={14} /> 下载详情长图
                    </a>
                  </div>
                )}
                {visualModules.length > 0 ? (
                  <div className="mx-auto max-w-[750px] space-y-4">
                    {visualModules.map((module) => {
                      const review = imageReviews.find((item) => item.module_key === module.key);
                      const draft = reviewDraft?.moduleKey === module.key ? reviewDraft : null;
                      return <figure key={module.key} className="bg-white shadow-sm overflow-hidden">
                        <img src={mediaUrl(module.image_url)} alt={module.title} className="w-full h-auto block" />
                        <figcaption className="no-print px-4 py-3">
                          <div className="flex flex-wrap items-center justify-between gap-3">
                            <div><div className="text-sm font-medium">{module.title}</div>{review && <div className="text-xs text-[var(--muted)] mt-1">已标记：{REVIEW_LABELS[review.status]} · {review.learning_status === 'completed' ? '已学习' : review.learning_status === 'failed' ? '学习失败' : '后台分析中'}</div>}</div>
                            <div className="flex flex-wrap gap-2">
                              <button disabled={editing} className={`btn-secondary text-xs ${review?.status === 'usable' ? 'border-green-500 text-green-700' : ''}`} onClick={() => submitImageReview(module.key, 'usable')}><Check size={13} /> 可使用</button>
                              <button disabled={editing} className={`btn-secondary text-xs ${review?.status === 'needs_edit' ? 'border-amber-500 text-amber-700' : ''}`} onClick={() => setReviewDraft({ moduleKey: module.key, status: 'needs_edit', reasons: review?.reasons || [] })}><Wrench size={13} /> 需修改</button>
                              <button disabled={editing} className={`btn-secondary text-xs ${review?.status === 'rejected' ? 'border-red-500 text-red-700' : ''}`} onClick={() => setReviewDraft({ moduleKey: module.key, status: 'rejected', reasons: review?.reasons || [] })}><X size={13} /> 不可用</button>
                              <button disabled={editing} className={`btn-primary text-xs ${review?.status === 'final' ? 'ring-2 ring-amber-400' : ''}`} onClick={() => submitImageReview(module.key, 'final')}><Award size={13} /> 最终采用</button>
                            </div>
                          </div>
                          {draft && <div className="mt-3 rounded-lg bg-[var(--bg-elevated)] p-3"><div className="text-xs font-medium mb-2">可选原因（点选即可，不需要写说明）</div><div className="flex flex-wrap gap-2">{REVIEW_REASONS.map((reason) => <button key={reason} className={`px-2.5 py-1 rounded-full border text-xs ${draft.reasons.includes(reason) ? 'bg-[var(--accent-soft)] border-[var(--accent)] text-[var(--accent)]' : 'border-[var(--border)]'}`} onClick={() => setReviewDraft({ ...draft, reasons: draft.reasons.includes(reason) ? draft.reasons.filter((item) => item !== reason) : [...draft.reasons, reason] })}>{reason}</button>)}</div><div className="mt-3 flex gap-2"><button className="btn-primary text-xs" onClick={() => submitImageReview(module.key, draft.status, draft.reasons)}>确认</button><button className="btn-secondary text-xs" onClick={() => setReviewDraft(null)}>取消</button></div></div>}
                        </figcaption>
                      </figure>;
                    })}
                  </div>
                ) : (
                  <div className="py-20 text-center text-[var(--muted)]">
                    尚未生成视觉模块。请确认商品已上传产品图片后重新生成。
                  </div>
                )}
              </div>
            ) : view === 'basis' ? (
              <div className="p-6 space-y-6">
                {!generationBasis ? <div className="py-16 text-center text-[var(--muted)]">旧生成记录没有追踪数据，请重新生成一次。</div> : <>
                  <section className="panel p-5">
                    <h3 className="font-medium flex items-center gap-2"><Database size={17} /> 商品资料</h3>
                    <div className="mt-3 text-sm"><strong>{generationBasis.product?.name}</strong><span className="text-[var(--muted)]"> · {generationBasis.product?.brand_name} · {generationBasis.product?.category}</span></div>
                    <div className="mt-3 grid gap-3">
                      {generationBasis.product?.fields_used.filter((field) => field.value).map((field) => <div key={field.name} className="rounded-lg bg-[var(--bg-elevated)] p-3"><div className="text-xs font-medium text-[var(--accent)]">{field.name}</div><p className="mt-1 text-xs text-[var(--muted)] whitespace-pre-wrap line-clamp-4">{field.value}</p></div>)}
                    </div>
                  </section>

                  <section className="panel p-5">
                    <h3 className="font-medium flex items-center gap-2"><ImageIcon size={17} /> 商品图片与素材</h3>
                    <div className="mt-3 flex flex-wrap gap-3">
                      {[...(generationBasis.assets?.product_images || []), ...(generationBasis.assets?.detail_images || [])].map((url, index) => <img key={`${url}-${index}`} src={mediaUrl(url)} className="w-24 h-24 rounded-lg object-cover border border-[var(--border)]" />)}
                    </div>
                    {generationBasis.assets?.files.map((file) => <div key={file.id} className="mt-2 text-xs text-[var(--muted)]">{file.type} · {file.name}</div>)}
                  </section>

                  <section className="panel p-5">
                    <h3 className="font-medium flex items-center gap-2"><FileText size={17} /> 品牌知识</h3>
                    <div className="mt-3 space-y-2">{generationBasis.brand_documents?.length ? generationBasis.brand_documents.map((doc) => <div key={doc.id} className="rounded-lg border border-[var(--border)] p-3 text-sm"><div className="font-medium">{doc.title}</div><div className="text-xs text-[var(--muted)] mt-1">品牌：{doc.brand_name} · {doc.chunks} 个切片 · 强制继承</div></div>) : <p className="text-sm text-[var(--muted)]">未命中品牌专属文档</p>}</div>
                  </section>

                  <section className="panel p-5">
                    <h3 className="font-medium flex items-center gap-2"><Database size={17} /> RAG 命中切片</h3>
                    <p className="mt-1 text-xs text-[var(--muted)]">检索方式：{generationBasis.rag?.method === 'vector' ? '向量相似度' : '关键词回退'}</p>
                    <div className="mt-3 space-y-3">{generationBasis.rag?.hits.map((hit, index) => <div key={`${hit.document_title}-${hit.chunk_index}`} className="rounded-lg bg-[var(--bg-elevated)] p-3"><div className="flex justify-between gap-3 text-sm"><span className="font-medium">{index + 1}. {hit.document_title}</span><span className="text-[var(--accent)] shrink-0">{hit.score == null ? '关键词命中' : `相似度 ${(hit.score * 100).toFixed(1)}%`}</span></div><div className="text-xs text-[var(--muted)] mt-1">{hit.scope} · 切片 #{hit.chunk_index + 1}</div><p className="text-xs mt-2 leading-relaxed">{hit.excerpt}</p></div>)}</div>
                  </section>

                  <section className="panel p-5">
                    <h3 className="font-medium flex items-center gap-2"><Palette size={17} /> 设计 Skill 合并链</h3>
                    <p className="mt-1 text-xs text-[var(--muted)]">按展示顺序叠加，后面的规则优先级更高。</p>
                    <div className="mt-3 space-y-3">{generationBasis.skill_chain?.map((skill, index) => <div key={`${skill.level}-${skill.name}`} className="rounded-lg border border-[var(--border)] p-3"><div className="flex items-center gap-2 text-sm font-medium"><span className="w-6 h-6 rounded-full bg-[var(--accent-soft)] text-[var(--accent)] flex items-center justify-center text-xs">{index + 1}</span>{skill.name}<span className="text-xs text-[var(--muted)]">{skill.level}</span>{skill.primary_color && <span className="w-4 h-4 rounded-full border" style={{ background: skill.primary_color }} />}</div>{skill.design_principles && <p className="mt-2 text-xs"><strong>设计：</strong>{skill.design_principles}</p>}{skill.visual_rules && <p className="mt-1 text-xs"><strong>视觉：</strong>{skill.visual_rules}</p>}{skill.copy_rules && <p className="mt-1 text-xs"><strong>文案：</strong>{skill.copy_rules}</p>}{skill.negative_rules && <p className="mt-1 text-xs text-amber-700"><strong>禁止：</strong>{skill.negative_rules}</p>}</div>)}</div>
                  </section>

                  <section className="panel p-5">
                    <h3 className="font-medium flex items-center gap-2"><Timer size={17} /> Agent 执行耗时</h3>
                    <div className="mt-3 space-y-2">{executionTrace?.steps?.map((step) => <div key={step.key} className="flex justify-between text-sm border-b border-[var(--border)] pb-2"><span>{step.label || AGENT_STEPS.find((item) => item.key === step.key)?.label || step.key}</span><span className="text-[var(--muted)]">{(step.duration_ms / 1000).toFixed(1)} 秒</span></div>)}</div>
                    <div className="mt-3 text-sm font-medium">总耗时：{((executionTrace?.total_duration_ms || 0) / 1000).toFixed(1)} 秒</div>
                  </section>
                </>}
              </div>
            ) : view === 'agents' ? (
              <div className="p-6 space-y-6">
                {AGENT_STEPS.map((step) => {
                  const data = agentResults[step.key];
                  if (!data) return null;
                  return (
                    <div key={step.key}>
                      <h3 className="font-medium mb-2">{step.label}</h3>
                      <pre className="text-xs bg-[var(--bg-elevated)] rounded-lg p-4 overflow-auto max-h-72 border border-[var(--border)]">
                        {JSON.stringify(data, null, 2)}
                      </pre>
                    </div>
                  );
                })}
                {gen.marketing_copy && (
                  <div>
                    <h3 className="font-medium mb-2">营销文案</h3>
                    <p className="text-sm leading-relaxed whitespace-pre-wrap">{gen.marketing_copy}</p>
                  </div>
                )}
                {gen.main_image_copy && (
                  <div>
                    <h3 className="font-medium mb-2">主图文案建议</h3>
                    <div className="prose-commerce text-sm">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{gen.main_image_copy}</ReactMarkdown>
                    </div>
                  </div>
                )}
              </div>
            ) : view === 'markdown' ? (
              <pre className="p-6 text-sm whitespace-pre-wrap font-mono leading-relaxed overflow-auto min-h-[480px]">
                {markdown}
              </pre>
            ) : view === 'preview' ? (
              <div className="p-6 space-y-4 min-h-[480px]">
                {moduleOrder.map((key) => (
                  <section key={key} className={`rounded-xl border p-4 ${activeSection === key ? 'border-[var(--accent)]' : 'border-[var(--border)]'}`}>
                    <div className="flex items-center justify-between mb-2">
                      <h3 className="font-medium">{SECTION_LABELS[key] || key}</h3>
                      <button className="text-xs text-[var(--accent)]" onClick={() => setActiveSection(key)}>编辑</button>
                    </div>
                    <textarea
                      className="w-full min-h-32 rounded-lg border border-[var(--border)] bg-white p-3 text-sm leading-relaxed"
                      value={moduleDrafts[key] || ''}
                      onChange={(e) => setModuleDrafts((current) => ({ ...current, [key]: e.target.value }))}
                    />
                    <div className="prose-commerce text-sm mt-3 rounded-lg bg-[var(--bg-elevated)] p-4">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{moduleDrafts[key] || ''}</ReactMarkdown>
                    </div>
                  </section>
                ))}
              </div>
            ) : (
              <div className="p-8 prose-commerce min-h-[480px]">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
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
