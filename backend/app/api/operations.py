"""Non-canvas production operations: readiness, tasks, billing and approvals."""
from __future__ import annotations
from datetime import datetime
from typing import Optional
import uuid
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import AuthContext, current_auth
from app.config import get_settings
from app.database import get_db
from app.models import ApprovalIssue, BrandVisualProfile, CanvasNode, CreativeGeneration, CreativePlan, CreativeProject, DetailPageTemplate, KnowledgeDocument, Product, ProductAsset, ProjectReview, ProviderBillingRecord, QualityRuleSet, StoryboardModule
from app.services.quality_pipeline import inspect_source

router = APIRouter(prefix="/operations", tags=["operations"])

class Ids(BaseModel): ids: list[int] = Field(default_factory=list)
class ReviewAction(BaseModel):
    action: str
    note: str = ""
    module_id: Optional[int] = None
    assignee_id: str = ""
    due_at: Optional[datetime] = None
    blocks_finalize: bool = True

def _notify_review(project:CreativeProject,action:str,note:str)->dict:
    url=get_settings().approval_webhook_url
    if not url:return {"status":"not_configured"}
    text=f"项目「{project.name}」审核状态更新：{action}"+(f"\n说明：{note}" if note else "")
    try:
        payload={"msgtype":"text","text":{"content":text}} if "qyapi.weixin.qq.com" in url else {"msg_type":"text","content":{"text":text}}
        response=httpx.post(url,json=payload,timeout=10);response.raise_for_status();return {"status":"sent"}
    except Exception as exc:return {"status":"failed","message":str(exc)[:200]}

def _readiness(product: Product, db: Session, tenant_id: str) -> dict:
    assets = db.query(ProductAsset).filter(ProductAsset.product_id == product.id, ProductAsset.tenant_id == tenant_id, ProductAsset.excluded.is_(False)).all()
    brand_docs = db.query(KnowledgeDocument).filter(KnowledgeDocument.tenant_id == tenant_id, KnowledgeDocument.brand_name == product.brand_name).count()
    brand_visual = db.query(BrandVisualProfile).filter(BrandVisualProfile.tenant_id == tenant_id, BrandVisualProfile.brand_name == product.brand_name).first()
    fields = [
        ("product_images", "商品原图", bool(product.image_urls) or any(a.material_role in {"product", "package"} for a in assets), True),
        ("ingredients", "成分资料", bool(product.ingredients.strip()), True),
        ("specifications", "规格与套装组成", bool(product.specifications.strip()), True),
        ("usage_method", "使用方法", bool(product.usage_method.strip()), False),
        ("brand", "品牌资料", bool(product.brand_name.strip()) and bool(brand_visual or brand_docs), True),
        ("benchmarks", "质检基准图", any(a.benchmark_role != "none" for a in assets), False),
    ]
    items = [{"key": key, "label": label, "complete": complete, "required": required} for key, label, complete, required in fields]
    required = [item for item in items if item["required"]]
    score = round(sum(item["complete"] for item in required) / len(required) * 100)
    return {"product_id": product.id, "score": score, "status": "ready" if score == 100 else "blocked", "items": items, "missing_required": [i["label"] for i in required if not i["complete"]]}

@router.get("/products/{product_id}/readiness")
def readiness(product_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    product = db.query(Product).filter(Product.id == product_id, Product.tenant_id == auth.tenant_id).first()
    if not product: raise HTTPException(404, "商品不存在")
    return _readiness(product, db, auth.tenant_id)

@router.get("/products/{product_id}/image-admission")
def image_admission(product_id:int,db:Session=Depends(get_db),auth:AuthContext=Depends(current_auth)):
    product=db.query(Product).filter_by(id=product_id,tenant_id=auth.tenant_id).first()
    if not product:raise HTTPException(404,"商品不存在")
    assets=db.query(ProductAsset).filter_by(product_id=product_id,tenant_id=auth.tenant_id).all();sources=[{"url":url,"label":f"商品原图 {i+1}"} for i,url in enumerate(product.image_urls or [])]+[{"url":a.file_url,"label":a.name,"asset_id":a.id} for a in assets if a.mime_type.startswith("image/") and not a.excluded]
    results=[{**source,"inspection":inspect_source(source["url"])} for source in sources]
    return {"status":"passed" if results and all(x["inspection"]["status"]=="passed" for x in results) else "review","images":results,"missing_roles":[role for role in ["product_front","package","set_composition"] if not any(a.benchmark_role==role for a in assets)]}

@router.get("/templates/recommendations")
def recommend_templates(product_id: int, platform: str = "", db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    product = db.query(Product).filter(Product.id == product_id, Product.tenant_id == auth.tenant_id).first()
    if not product: raise HTTPException(404, "商品不存在")
    category = (product.category or "").lower(); shape = "套装" if any(k in product.name for k in ["套装", "礼盒", "组合"]) else "单品"
    rows = db.query(DetailPageTemplate).filter(DetailPageTemplate.tenant_id == auth.tenant_id, DetailPageTemplate.enabled.is_(True)).all()
    ranked = []
    for row in rows:
        score, reasons = 20, []
        if row.category and (row.category.lower() in category or category in row.category.lower()): score += 45; reasons.append("品类匹配")
        if platform and row.platform == platform: score += 20; reasons.append("平台匹配")
        if row.brand_name and row.brand_name == product.brand_name: score += 10; reasons.append("品牌历史匹配")
        titles = " ".join(str(m.get("title", "")) for m in row.modules)
        if shape in titles or shape == "单品": score += 5; reasons.append(f"适合{shape}")
        ranked.append({"template": row, "score": min(100, score), "reasons": reasons or ["通用结构"]})
    ranked.sort(key=lambda item: (item["score"], item["template"].approved_count, item["template"].usage_count), reverse=True)
    return [{"template_id": x["template"].id, "name": x["template"].name, "score": x["score"], "reasons": x["reasons"], "module_count": len(x["template"].modules), "platform": x["template"].platform, "category": x["template"].category} for x in ranked[:8]]

@router.get("/templates/{template_id}/performance")
def template_performance(template_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    row = db.query(DetailPageTemplate).filter(DetailPageTemplate.id == template_id, DetailPageTemplate.tenant_id == auth.tenant_id).first()
    if not row: raise HTTPException(404, "模板不存在")
    return {"usage_count": row.usage_count, "completed_count": row.completed_count, "approved_count": row.approved_count, "success_rate": round(row.completed_count / row.usage_count * 100, 1) if row.usage_count else 0, "adoption_rate": round(row.approved_count / row.usage_count * 100, 1) if row.usage_count else 0, "average_revision_rounds": round(row.total_revision_rounds / row.completed_count, 1) if row.completed_count else 0}

@router.get("/tasks/detail/{task_id}")
def task_detail(task_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    row = db.query(CreativeGeneration).filter(CreativeGeneration.id == task_id, CreativeGeneration.tenant_id == auth.tenant_id).first()
    if not row: raise HTTPException(404, "任务不存在")
    return {"id": row.id, "project_id": row.project_id, "action": row.action, "prompt": row.prompt, "provider": row.provider, "status": row.status, "duration_ms": row.duration_ms, "result_node_ids": row.result_node_ids, "error_message": row.error_message, "diagnostic": (row.context_snapshot or {}).get("diagnostic"), "context_snapshot": row.context_snapshot, "created_at": row.created_at, "updated_at": row.updated_at}

@router.post("/tasks/cancel")
def cancel_tasks(payload: Ids, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    rows = db.query(CreativeGeneration).filter(CreativeGeneration.id.in_(payload.ids), CreativeGeneration.tenant_id == auth.tenant_id, CreativeGeneration.status.in_(["pending", "running"])).all()
    for row in rows: row.status = "cancelled"; row.error_message = "用户取消"
    db.commit(); return {"updated": len(rows)}

@router.post("/tasks/retry")
def retry_tasks(payload: Ids, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    from app.api.creative import retry_creative_generation
    rows = db.query(CreativeGeneration).filter(CreativeGeneration.id.in_(payload.ids), CreativeGeneration.tenant_id == auth.tenant_id, CreativeGeneration.status == "failed").all()
    results = []
    for row in rows:
        try:
            retry_creative_generation(row.project_id, row.id, db, auth); results.append({"id": row.id, "status": "retried"})
        except Exception as exc:
            results.append({"id": row.id, "status": "failed", "error": str(getattr(exc, "detail", exc))})
    return {"results": results}

@router.get("/tasks/statistics")
def task_statistics(db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    rows = db.query(CreativeGeneration).filter(CreativeGeneration.tenant_id == auth.tenant_id).all()
    errors = {}; durations = [r.duration_ms for r in rows if r.duration_ms is not None]
    for row in rows:
        if row.status == "failed":
            code = ((row.context_snapshot or {}).get("diagnostic") or {}).get("code", "unknown"); errors[code] = errors.get(code, 0) + 1
    return {"error_breakdown": errors, "average_duration_ms": round(sum(durations)/len(durations)) if durations else 0, "p95_duration_ms": sorted(durations)[max(0, int(len(durations)*.95)-1)] if durations else 0, "cancelled": sum(r.status == "cancelled" for r in rows)}

@router.get("/billing/status")
def billing_status(db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    settings = get_settings(); records = db.query(ProviderBillingRecord).filter(ProviderBillingRecord.tenant_id == auth.tenant_id).all()
    return {"configured": bool(settings.volc_billing_api_url and settings.volc_billing_api_token), "source": "provider_bill" if records else "estimated", "record_count": len(records), "amount_cny": round(sum(r.amount_cny for r in records), 2), "latest_date": max((r.billing_date for r in records), default=None)}

@router.post("/billing/sync")
async def sync_billing(db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    settings = get_settings()
    if not settings.volc_billing_api_url or not settings.volc_billing_api_token: raise HTTPException(400, "请先配置 VOLC_BILLING_API_URL 和 VOLC_BILLING_API_TOKEN")
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(settings.volc_billing_api_url, headers={"Authorization": f"Bearer {settings.volc_billing_api_token}"}, params={"account_id": settings.volc_billing_account_id})
    if response.status_code >= 400: raise HTTPException(502, f"火山账单接口返回 {response.status_code}")
    body = response.json(); items = body.get("items") or body.get("data", {}).get("items") or []
    synced = 0
    for item in items:
        external_id = str(item.get("id") or item.get("bill_id") or uuid.uuid4().hex)
        if db.query(ProviderBillingRecord).filter_by(tenant_id=auth.tenant_id, provider="volcengine_ark", external_id=external_id).first(): continue
        db.add(ProviderBillingRecord(tenant_id=auth.tenant_id, provider="volcengine_ark", external_id=external_id, billing_date=str(item.get("date") or item.get("billing_date") or datetime.utcnow().date()), model=str(item.get("model") or ""), amount_cny=float(item.get("amount_cny") or item.get("amount") or 0), usage=item.get("usage") or {}, raw=item)); synced += 1
    db.commit(); return {"synced": synced, "received": len(items)}

FLOW = {"draft": {"submit": "submitted"}, "submitted": {"approve": "operational_approved", "approve_conditional": "operational_approved", "reject": "changes_requested"}, "changes_requested": {"resubmit": "submitted"}, "operational_approved": {"finalize": "finalized", "reject": "changes_requested"}}
@router.get("/projects/{project_id}/reviews")
def reviews(project_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    project = db.query(CreativeProject).filter(CreativeProject.id == project_id, CreativeProject.tenant_id == auth.tenant_id).first()
    if not project: raise HTTPException(404, "项目不存在")
    rows = db.query(ProjectReview).filter(ProjectReview.project_id == project_id, ProjectReview.tenant_id == auth.tenant_id).order_by(ProjectReview.created_at.desc()).all()
    return {"status": project.review_status, "round": project.review_round, "history": [{"id": r.id, "action": r.action, "from_status": r.from_status, "to_status": r.to_status, "note": r.note, "actor_role": r.actor_role, "created_at": r.created_at} for r in rows]}

@router.post("/projects/{project_id}/reviews")
def review_action(project_id: int, payload: ReviewAction, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    project = db.query(CreativeProject).filter(CreativeProject.id == project_id, CreativeProject.tenant_id == auth.tenant_id).first()
    if not project: raise HTTPException(404, "项目不存在")
    next_status = FLOW.get(project.review_status, {}).get(payload.action)
    if not next_status: raise HTTPException(400, f"当前状态不允许 {payload.action}")
    if payload.action in {"submit","resubmit"}:
        modules=db.query(StoryboardModule).filter_by(project_id=project.id,tenant_id=auth.tenant_id).all();missing=[m.title for m in modules if m.required and m.status!="approved"]
        open_issues=db.query(ApprovalIssue).filter_by(project_id=project.id,tenant_id=auth.tenant_id,status="open").count()
        low=[];vision_missing=[];vision_blocked=[];protected_text_blocked=[]
        product=db.query(Product).filter_by(id=project.product_id,tenant_id=auth.tenant_id).first();rule_set=db.query(QualityRuleSet).filter_by(tenant_id=auth.tenant_id,category=product.category).first();thresholds=(rule_set.thresholds if rule_set else {"hero":85,"product_showcase":82,"texture":75,"ingredient":75,"scenario":72,"information":80});has_protected_text=any((asset.protection or {}).get("protected_regions") for asset in db.query(ProductAsset).filter_by(product_id=product.id,tenant_id=auth.tenant_id).all())
        for module in modules:
            node=db.query(CanvasNode).filter_by(id=module.final_node_id or module.preview_node_id).first() if (module.final_node_id or module.preview_node_id) else None
            if node and (node.data.get("quality_scores") or {}).get("total",100)<65:low.append(module.title)
            if module.required and node:
                vision=node.data.get("vision_quality");suite=node.data.get("vision_quality_suite") or {}
                if not vision or not suite.get("is_real_model"):vision_missing.append(module.title)
                elif suite.get("status")=="blocked" or min(vision.get("product_consistency",0),vision.get("brand_match",0),vision.get("commercial_aesthetic",0))<int(thresholds.get(module.module_type,75)):vision_blocked.append(module.title)
                if has_protected_text and (node.data.get("protected_text_check") or {}).get("status")!="passed":protected_text_blocked.append(module.title)
        if missing or open_issues or low or vision_missing or vision_blocked or protected_text_blocked:raise HTTPException(409,{"message":"提交前质量门槛未通过","missing_required":missing,"open_issues":open_issues,"low_quality":low,"vision_quality_missing":vision_missing,"vision_quality_blocked":vision_blocked,"protected_text_blocked":protected_text_blocked})
    if payload.action in {"approve", "approve_conditional", "reject"} and auth.role not in {"owner", "admin", "operator"}: raise HTTPException(403, "仅运营负责人可以审核")
    if payload.action=="approve_conditional" and not payload.note.strip():raise HTTPException(400,"有条件通过必须填写交付前需修复的事项")
    if payload.action == "finalize" and auth.role not in {"owner", "admin"}: raise HTTPException(403, "仅负责人可以定稿")
    if payload.action=="finalize":
        open_issues=db.query(ApprovalIssue).filter_by(project_id=project.id,tenant_id=auth.tenant_id,status="open",blocks_finalize=True).count()
        conditional=db.query(ProjectReview).filter_by(project_id=project.id,tenant_id=auth.tenant_id,action="approve_conditional").order_by(ProjectReview.created_at.desc()).first()
        if open_issues:raise HTTPException(409,{"message":"有条件通过的修改项尚未验收，不能定稿","open_issues":open_issues,"conditional_note":conditional.note if conditional else ""})
    if payload.action in {"approve", "finalize"}:
        latest_submit=db.query(ProjectReview).filter(ProjectReview.project_id==project.id,ProjectReview.action.in_(["submit","resubmit"])).order_by(ProjectReview.created_at.desc()).first()
        if latest_submit and latest_submit.actor_id==auth.user_id: raise HTTPException(403,"提交人不能审核或定稿自己的项目")
    previous = project.review_status
    if payload.action=="approve_conditional":
        target=db.query(StoryboardModule).filter_by(id=payload.module_id,project_id=project.id,tenant_id=auth.tenant_id).first() if payload.module_id else None
        if not target:target=db.query(StoryboardModule).filter_by(project_id=project.id,tenant_id=auth.tenant_id).order_by(StoryboardModule.required.desc(),StoryboardModule.sort_order).first()
        if not target:raise HTTPException(409,"项目没有可挂载条件修改项的页面")
        db.add(ApprovalIssue(tenant_id=auth.tenant_id,project_id=project.id,module_id=target.id,source_node_id=target.final_node_id or target.preview_node_id,issue_type="有条件通过修改项",severity="medium",action="manual_refine",note=payload.note,region={},assignee_id=payload.assignee_id,due_at=payload.due_at,blocks_finalize=payload.blocks_finalize,created_by=auth.user_id))
    if payload.action in {"submit", "resubmit", "finalize"}:
        from app.api.production import create_project_snapshot
        create_project_snapshot(project.id, payload.action, db, auth)
    if payload.action in {"submit", "resubmit"}: project.review_round += 1
    project.review_status = next_status; project.status = "completed" if next_status == "finalized" else project.status
    db.add(ProjectReview(tenant_id=auth.tenant_id, project_id=project.id, round=project.review_round, action=payload.action, from_status=previous, to_status=next_status, note=payload.note, actor_id=auth.user_id, actor_role=auth.role))
    plan = db.query(CreativePlan).filter(CreativePlan.project_id == project.id).first()
    source_template_id = (plan.strategy or {}).get("source_template_id") if plan else None
    if source_template_id:
        template = db.query(DetailPageTemplate).filter(DetailPageTemplate.id == source_template_id).first()
        if template and payload.action == "finalize": template.completed_count += 1; template.approved_count += 1; template.total_revision_rounds += project.review_round
    db.commit();notification=_notify_review(project,payload.action,payload.note);return {"status": project.review_status, "round": project.review_round,"notification":notification}
