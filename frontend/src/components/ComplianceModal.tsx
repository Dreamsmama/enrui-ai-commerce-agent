import { AlertTriangle, Check, FileText, Image as ImageIcon, ShieldCheck, X } from 'lucide-react';
import type { ComplianceReport } from '../types';

export default function ComplianceModal({ report, onClose, onContinue, loading }: { report: ComplianceReport; onClose: () => void; onContinue: () => void; loading: boolean }) {
  const visual = report.visual_quality;
  const consistency = report.product_consistency;
  return (
    <div className="fixed inset-0 z-50 bg-black/55 p-5 overflow-auto" onClick={onClose}>
      <div className="max-w-3xl mx-auto bg-white rounded-2xl overflow-hidden" onClick={(event) => event.stopPropagation()}>
        <div className="p-5 border-b border-[var(--border)] flex justify-between">
          <div className="flex gap-3">
            <div className={`w-11 h-11 rounded-full grid place-items-center ${report.status === 'blocked' ? 'bg-red-50 text-red-700' : 'bg-emerald-50 text-emerald-700'}`}>{report.status === 'blocked' ? <AlertTriangle /> : <ShieldCheck />}</div>
            <div><h3 className="font-medium text-lg">导出前质量检查 · {report.score}分</h3><p className="text-xs text-[var(--muted)] mt-1">内容高风险 {report.high_count} 项 · 图片高风险 {visual?.high_count || 0} 项</p></div>
          </div>
          <button onClick={onClose}><X size={18} /></button>
        </div>
        <div className="p-5 space-y-5 max-h-[60vh] overflow-auto">
          <section><h4 className="text-sm font-medium flex items-center gap-2"><FileText size={15} />内容与知识依据</h4><div className="space-y-3 mt-3">
            {report.issues.length === 0 && <div className="rounded-xl bg-emerald-50 text-emerald-800 p-4 flex items-center gap-2 text-sm"><Check size={17} />未发现明显内容风险。</div>}
            {report.issues.map((issue, index) => <div key={`${issue.module_id}-${index}`} className={`rounded-xl border p-4 ${issue.severity === 'high' ? 'border-red-200 bg-red-50/50' : 'border-amber-200 bg-amber-50/50'}`}><div className="flex justify-between gap-3"><div className="text-sm font-medium">{issue.module_title} · “{issue.claim}”</div><Risk severity={issue.severity} /></div><p className="text-xs leading-5 mt-2">{issue.message}</p>{issue.sources.length > 0 && <div className="flex flex-wrap gap-2 mt-3">{issue.sources.map((source) => <span key={source.id} className="rounded-full bg-white px-2 py-1 text-[10px] border"><FileText size={10} className="inline mr-1" />{source.title}</span>)}</div>}</div>)}
          </div></section>
          <section><h4 className="text-sm font-medium flex items-center gap-2"><ImageIcon size={15} />图片质量</h4><div className="space-y-3 mt-3">
            {visual && visual.issues.length === 0 && <div className="rounded-xl bg-emerald-50 text-emerald-800 p-4 flex items-center gap-2 text-sm"><Check size={17} />已检查 {visual.checked_count} 张图片，未发现明显技术质量问题。</div>}
            {visual?.issues.map((issue, index) => <div key={`${issue.module_id}-${index}`} className={`rounded-xl border p-4 ${issue.severity === 'high' ? 'border-red-200 bg-red-50/50' : 'border-amber-200 bg-amber-50/50'}`}><div className="flex justify-between gap-3"><div className="text-sm font-medium">{issue.module_title}</div><Risk severity={issue.severity} /></div><p className="text-xs leading-5 mt-2">{issue.message}</p></div>)}
          </div></section>
          <section><h4 className="text-sm font-medium flex items-center gap-2"><ShieldCheck size={15} />商品一致性视觉对比</h4><div className="space-y-3 mt-3">{consistency?.status === 'unavailable' && <div className="rounded-xl bg-amber-50 text-amber-800 p-4 text-sm">{consistency.message}</div>}{consistency && consistency.status !== 'unavailable' && consistency.issues.length === 0 && <div className="rounded-xl bg-emerald-50 text-emerald-800 p-4 text-sm"><Check size={17} className="inline mr-2"/>已对比商品原图与 {consistency.checked_count} 张生成结果，未发现明显商品事实偏差。</div>}{consistency?.issues.map((issue, index) => <div key={index} className={`rounded-xl border p-4 ${issue.severity === 'high' ? 'border-red-200 bg-red-50/50' : 'border-amber-200 bg-amber-50/50'}`}><div className="flex justify-between"><div className="text-sm font-medium">生成图 #{issue.output_index} · {issue.field}</div><Risk severity={issue.severity}/></div><p className="text-xs leading-5 mt-2">{issue.message}（置信度 {Math.round(issue.confidence * 100)}%）</p></div>)}</div></section>
        </div>
        <div className="p-5 bg-[#f7f5f0] border-t border-[var(--border)] flex items-center justify-between gap-4"><p className="text-xs text-[var(--muted)]">继续表示已人工确认内容及图片风险；系统不会替代品牌法务与设计审核。</p><div className="flex gap-2 shrink-0"><button className="btn-secondary" onClick={onClose}>返回修改</button><button className="btn-primary" disabled={loading} onClick={onContinue}>{report.status === 'blocked' ? '确认风险并预览' : '继续预览长图'}</button></div></div>
      </div>
    </div>
  );
}

function Risk({ severity }: { severity: 'high' | 'medium' }) {
  return <span className={`text-[10px] rounded-full px-2 py-1 ${severity === 'high' ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-800'}`}>{severity === 'high' ? '高风险' : '需复核'}</span>;
}
