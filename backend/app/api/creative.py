"""Creative projects and lightweight infinite-canvas APIs."""

from __future__ import annotations

import mimetypes
import uuid
import time
import asyncio
from io import BytesIO
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from PIL import Image, ImageOps
from sqlalchemy.orm import Session

from app.auth import AuthContext, current_auth
from app.database import SessionLocal, get_db
from app.models import ApprovalIssue, BrandVisualProfile, CanvasNode, CreativeBatchJob, CreativeFeedback, CreativeGeneration, CreativePlan, CreativeProject, DesignSkill, KnowledgeDocument, LearnedDesignProfile, Product, ProductAsset, ProductFact, QualityRegressionRun, QualityRuleSet, RegressionSample, StoryboardModule
from app.schemas import (
    CanvasNodeCreate,
    CanvasNodeOut,
    CanvasSaveRequest,
    CreativeGenerateRequest,
    CreativeFeedbackCreate,
    CreativeFeedbackOut,
    CreativeGenerationOut,
    CreativePlanOut,
    CreativeProjectCreate,
    CreativeProjectOut,
    StoryboardModuleCreate,
    StoryboardBatchCreate,
    StoryboardModuleOut,
    StoryboardModuleSelectionRequest,
    StoryboardQuickEditRequest,
    StoryboardStyleRequest,
    StoryboardUpdateRequest,
)
from app.services.design_learning import REVIEW_WEIGHTS, analyze_creative_feedback
from app.services.compliance import check_storyboard_compliance
from app.services.visual_quality import check_visual_quality
from app.services.product_consistency import compare_product_images
from app.services.quality_pipeline import apply_generation_controls, inspect_source, repair_instruction, score_output, validate_and_rewrite_prompt
from app.services.generation_diagnostics import diagnose_generation_error
from app.services.image_generation import get_image_provider
from app.services.storage import get_storage
from app.services.visual_renderer import render_quick_edit, render_storyboard_template, render_style_adjustment
from app.services.image_postprocess import contact_sheet, duplicate_report, hard_lock_product, regional_composite, restore_protected_regions
from app.services.vision_quality import compare_protected_text, review_commercial_suite
from app.config import get_settings

router = APIRouter(prefix="/creative-projects", tags=["creative-projects"])


def _batch_out(job: CreativeBatchJob) -> dict:
    return {"id": job.id, "project_id": job.project_id, "status": job.status, "module_ids": job.module_ids, "module_results": job.module_results, "total": job.total, "completed": job.completed, "failed": job.failed, "current_module_id": job.current_module_id, "stop_requested": job.stop_requested, "created_at": job.created_at, "updated_at": job.updated_at}


def _run_storyboard_batch(job_id: str, tenant_id: str, user_id: str, role: str, email: str, tenant_name: str) -> None:
    db = SessionLocal()
    try:
        job = db.query(CreativeBatchJob).filter(CreativeBatchJob.id == job_id).first()
        if not job:
            return
        job.status = "running"; db.commit()
        auth = AuthContext(user_id=user_id, tenant_id=tenant_id, role=role, email=email, tenant_name=tenant_name)
        for module_id in job.module_ids:
            db.refresh(job)
            if job.stop_requested:
                job.status = "stopped"; job.current_module_id = None; db.commit(); return
            module = db.query(StoryboardModule).filter(StoryboardModule.id == module_id, StoryboardModule.project_id == job.project_id, StoryboardModule.tenant_id == tenant_id).first()
            if not module:
                job.failed += 1
                job.module_results = [*job.module_results, {"module_id": module_id, "status": "failed", "error": "模块不存在"}]
                db.commit(); continue
            job.current_module_id = module_id; db.commit()
            payload = CreativeGenerateRequest(prompt=f"{module.objective}。{module.content_guidance}。{module.visual_direction}", action=f"详情页·{module.title}", selected_node_ids=[], auto_select_materials=True, module_id=module.id, count=1)
            try:
                generate_variants(job.project_id, payload, db, auth)
                job.completed += 1
                job.module_results = [*job.module_results, {"module_id": module_id, "status": "completed"}]
            except Exception as exc:
                job.failed += 1
                detail = getattr(exc, "detail", str(exc))
                job.module_results = [*job.module_results, {"module_id": module_id, "status": "failed", "error": str(detail)}]
            db.commit()
        job.current_module_id = None
        job.status = "completed_with_errors" if job.failed else "completed"
        db.commit()
    finally:
        db.close()


def _project(db: Session, project_id: int, tenant_id: str) -> CreativeProject:
    row = db.query(CreativeProject).filter(CreativeProject.id == project_id, CreativeProject.tenant_id == tenant_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="创作项目不存在")
    return row

def _editable(project: CreativeProject) -> None:
    if project.review_status == "finalized":
        raise HTTPException(status_code=409, detail="项目已定稿锁定，请复制为新项目后再修改")


def _material_role(node: CanvasNode) -> str:
    explicit = str(node.data.get("material_role") or node.data.get("asset_type") or "").lower()
    label = f"{node.data.get('label', '')} {node.data.get('description', '')} {explicit}".lower()
    rules = [
        ("logo", ["logo", "标志", "商标"]), ("texture", ["质地", "膏体", "液体", "微距", "texture"]),
        ("scenario", ["场景", "人物", "浴室", "梳妆", "scene", "生活方式"]), ("ingredient", ["成分", "草本", "植物", "ingredient"]),
        ("package", ["套装", "组合", "礼盒", "全家福", "package", "组合展示"]), ("detail", ["细节", "侧面", "背面", "detail"]),
    ]
    for role, keywords in rules:
        if any(keyword in label for keyword in keywords):
            return role
    if node.node_type == "brand_asset":
        return "brand"
    if node.node_type in {"product", "product_image"}:
        return "product"
    return "reference"


def _smart_materials(module: StoryboardModule | None, nodes: list[CanvasNode], explicit: list[CanvasNode]) -> tuple[list[CanvasNode], str, dict[str, str]]:
    source_types = {"product", "product_image", "reference", "brand_asset", "detail_image"}
    available = [node for node in nodes if node.data.get("image_url") and node.node_type in source_types and not node.data.get("excluded")]
    available.sort(key=lambda node: (not bool(node.data.get("locked")), -int(node.data.get("priority") or 0)))
    by_role: dict[str, list[CanvasNode]] = {}
    for node in available:
        by_role.setdefault(_material_role(node), []).append(node)
    product_nodes = by_role.get("package", []) + by_role.get("product", []) + by_role.get("detail", [])
    module_type = module.module_type if module else "general"
    preferences = {
        "hero": ["package", "product", "brand"], "product_showcase": ["package", "product", "detail"],
        "texture": ["texture", "detail", "product"], "ingredients": ["ingredient", "product", "texture"],
        "scenario": ["scenario", "reference", "product"], "brand": ["logo", "brand", "package"],
        "usage": ["detail", "product", "scenario"], "specification": ["package", "detail", "product"],
    }.get(module_type, ["product", "package", "reference"])
    selected: list[CanvasNode] = []
    reasons: dict[str, str] = {}
    for node in available:
        if node.data.get("locked") and len(selected) < 4:
            selected.append(node); reasons[node.id] = "设计师已锁定，生成时必须使用"
    for role in preferences:
        for node in by_role.get(role, []):
            if node not in selected and len(selected) < 4:
                selected.append(node); reasons[node.id] = f"识别为{role}素材，适合{module.title if module else '当前任务'}"
    for node in explicit:
        if node.data.get("image_url") and node not in selected:
            selected.append(node); reasons[node.id] = "设计师手动指定参考"
    if not selected:
        selected = product_nodes[:3] or available[:3]
        for node in selected:
            reasons[node.id] = "作为商品基础素材自动补充"
    return selected, f"按{module.title if module else '生成任务'}智能匹配：{' → '.join(preferences)}", reasons


def _module_specs(product: Product) -> list[dict]:
    category = (product.category or "").lower()
    has_color = any(keyword in category for keyword in ["气垫", "粉底", "口红", "唇", "眼影", "彩妆"])
    specs = [
        ("hero", "产品首屏", "建立第一视觉印象，表达商品定位与第一核心卖点", "商品完整组合、品牌名、核心利益点", "商品为绝对主体，大留白，品牌色控制", "ai_image", True),
        ("product_showcase", "产品组合展示", "准确说明套装组成与产品关系", "展示全部商品、规格与组合关系", "稳定商业棚拍或轻场景，避免包装变形", "ai_image", True),
        ("pain_point", "用户痛点", "让目标消费者快速产生需求共鸣", product.target_users or "结合目标人群提炼2至3个真实痛点", "信息图式表达，减少夸张前后对比", "template", False),
        ("selling_points", "核心卖点", "集中解释最重要的产品价值", product.description or "从商品资料提取有依据的核心卖点", "一个模块只讲一个结论，商品与文案层级清楚", "template", True),
        ("texture", "质地细节", "展示产品质地、肤感或结构细节", "产品局部、质地联想与使用感受", "微距特写、水润光影、保持真实材质", "ai_image", True),
        ("ingredients", "成分功效", "用有依据的信息解释成分和利益点", product.ingredients or "只使用已录入的成分资料", "成分素材与产品并置，禁止虚构检测与专利", "template", True),
        ("technology", "科技/机理表达", "辅助解释产品作用逻辑", "根据品牌调性决定草本、分子或实验室表达", "品牌偏自然时弱化分子科技，避免伪科学", "template", False),
        ("scenario", "使用场景", "帮助消费者代入日常使用情境", product.target_users or "根据目标人群选择真实生活场景", "人物或空间作为辅助，商品识别必须清晰", "ai_image", False),
        ("usage", "使用方法", "降低理解和使用门槛", product.usage_method or "按商品资料组织步骤", "步骤化排版，文字简短，动作明确", "template", True),
        ("brand", "品牌收尾", "统一品牌信任感并完成视觉收束", f"{product.brand_name}品牌定位与服务信息", "延续整套视觉语言，避免突然换风格", "template", False),
        ("specification", "产品信息", "准确展示规格和必要说明", product.specifications or "规格、套装组成与以实物为准提示", "标准信息排版，优先保证准确与可读", "template", True),
    ]
    if has_color:
        specs.insert(7, ("shade", "色号/妆效", "帮助消费者理解色号与实际妆效", "色号、肤色适配与妆效差异", "真实肤色与统一光线，禁止误导性色差", "template", True))
    return [dict(module_type=item[0], title=item[1], objective=item[2], content_guidance=item[3], visual_direction=item[4], production_method=item[5], required=item[6]) for item in specs]


def _plan_out(plan: CreativePlan, modules: list[StoryboardModule]) -> dict:
    return {
        "id": plan.id,
        "project_id": plan.project_id,
        "product_understanding": plan.product_understanding,
        "strategy": plan.strategy,
        "status": plan.status,
        "modules": modules,
    }


@router.get("", response_model=list[CreativeProjectOut])
def list_projects(db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    return db.query(CreativeProject).filter(CreativeProject.tenant_id == auth.tenant_id).order_by(CreativeProject.updated_at.desc()).all()


@router.get("/metrics/summary")
def creative_metrics(project_id: Optional[int] = None, provider: str = "", status: str = "", date_from: str = "", date_to: str = "", db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    query = db.query(CreativeGeneration).filter(CreativeGeneration.tenant_id == auth.tenant_id)
    if project_id is not None: query = query.filter(CreativeGeneration.project_id == project_id)
    if provider: query = query.filter(CreativeGeneration.provider == provider)
    if status: query = query.filter(CreativeGeneration.status == status)
    if date_from: query = query.filter(CreativeGeneration.created_at >= date_from)
    if date_to: query = query.filter(CreativeGeneration.created_at <= f"{date_to} 23:59:59")
    jobs = query.order_by(CreativeGeneration.created_at.desc()).all()
    completed = [job for job in jobs if job.status == "completed"]
    failed = [job for job in jobs if job.status == "failed"]
    image_count = sum(len(job.result_node_ids or []) for job in completed)
    settings = get_settings()
    estimated_cost = round(sum((len(job.result_node_ids or []) if job.provider != "template_renderer" else 0) * settings.image_generation_unit_cost_cny for job in completed), 2)
    diagnostics: dict[str, int] = {}
    for job in failed:
        code = (job.context_snapshot or {}).get("diagnostic", {}).get("code", "unknown")
        diagnostics[code] = diagnostics.get(code, 0) + 1
    return {"total_tasks": len(jobs), "completed": len(completed), "failed": len(failed), "success_rate": round(len(completed) / len(jobs) * 100, 1) if jobs else 0, "image_count": image_count, "estimated_cost_cny": estimated_cost, "cost_source": "estimated", "cost_note": "按成功生成图片数和配置单价估算，尚未接入火山方舟账单 API。", "monthly_budget_cny": settings.tenant_monthly_budget_cny, "budget_usage_percent": round(estimated_cost / settings.tenant_monthly_budget_cny * 100, 1) if settings.tenant_monthly_budget_cny else 0, "max_concurrency": settings.tenant_max_concurrent_generations, "running": sum(job.status == "running" for job in jobs), "error_breakdown": diagnostics, "providers": sorted({job.provider for job in db.query(CreativeGeneration).filter(CreativeGeneration.tenant_id == auth.tenant_id).all()}), "recent_tasks": [{"id": job.id, "project_id": job.project_id, "action": job.action, "provider": job.provider, "status": job.status, "result_count": len(job.result_node_ids or []), "diagnostic": (job.context_snapshot or {}).get("diagnostic"), "created_at": job.created_at} for job in jobs[:100]]}


@router.post("/{project_id}/generations/{generation_id}/retry")
def retry_creative_generation(project_id: int, generation_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    job = db.query(CreativeGeneration).filter(CreativeGeneration.id == generation_id, CreativeGeneration.project_id == project_id, CreativeGeneration.tenant_id == auth.tenant_id).first()
    if not job: raise HTTPException(404, "生成任务不存在")
    if job.status != "failed": raise HTTPException(400, "仅失败任务可以重试")
    module_id = (job.context_snapshot or {}).get("module_id")
    payload = CreativeGenerateRequest(prompt=job.prompt, action=job.action, selected_node_ids=job.selected_node_ids or [], parent_node_id=job.parent_node_id, auto_select_materials=not bool(job.selected_node_ids), module_id=module_id, count=max(1, min(6, (job.context_snapshot or {}).get("requested_count", 1))))
    return generate_variants(project_id, payload, db, auth)


@router.post("", response_model=CreativeProjectOut)
def create_project(payload: CreativeProjectCreate, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    product = db.query(Product).filter(Product.id == payload.product_id, Product.tenant_id == auth.tenant_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="商品不存在")
    project = CreativeProject(tenant_id=auth.tenant_id, **payload.model_dump())
    db.add(project); db.commit(); db.refresh(project)
    urls = list(product.image_urls or []) + list(product.detail_image_urls or [])
    for index, url in enumerate(urls):
        db.add(CanvasNode(
            id=uuid.uuid4().hex, tenant_id=auth.tenant_id, project_id=project.id,
            node_type="product" if index < len(product.image_urls or []) else "reference",
            position_x=(index % 3) * 300, position_y=(index // 3) * 360,
            data={"label": "商品图片" if index < len(product.image_urls or []) else "详情参考", "image_url": url, "source": "product"},
        ))
    image_assets = db.query(ProductAsset).filter(ProductAsset.tenant_id == auth.tenant_id, ProductAsset.product_id == product.id, ProductAsset.mime_type.like("image/%")).all()
    for index, asset in enumerate(image_assets):
        db.add(CanvasNode(
            id=uuid.uuid4().hex, tenant_id=auth.tenant_id, project_id=project.id,
            node_type="brand_asset" if asset.asset_type == "brand_asset" else "reference",
            position_x=((len(urls) + index) % 3) * 300, position_y=((len(urls) + index) // 3) * 360,
            data={"label": asset.name, "image_url": asset.file_url, "source": "asset_library", "asset_id": asset.id, "asset_type": asset.asset_type, "description": asset.description, "material_role": asset.material_role, "priority": asset.priority, "locked": asset.locked, "excluded": asset.excluded},
        ))
    db.commit()
    return project


@router.get("/{project_id}", response_model=CreativeProjectOut)
def get_project(project_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    return _project(db, project_id, auth.tenant_id)


@router.get("/{project_id}/plan", response_model=CreativePlanOut)
def get_plan(project_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    _project(db, project_id, auth.tenant_id)
    plan = db.query(CreativePlan).filter(CreativePlan.project_id == project_id, CreativePlan.tenant_id == auth.tenant_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="详情页策划尚未生成")
    modules = db.query(StoryboardModule).filter(StoryboardModule.project_id == project_id, StoryboardModule.tenant_id == auth.tenant_id).order_by(StoryboardModule.sort_order).all()
    return _plan_out(plan, modules)


@router.post("/{project_id}/plan", response_model=CreativePlanOut)
def generate_plan(project_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    project = _project(db, project_id, auth.tenant_id)
    product = db.query(Product).filter(Product.id == project.product_id, Product.tenant_id == auth.tenant_id).first()
    documents = db.query(KnowledgeDocument).filter(KnowledgeDocument.tenant_id == auth.tenant_id, KnowledgeDocument.brand_name == product.brand_name).all()
    skills = db.query(DesignSkill).filter(DesignSkill.tenant_id == auth.tenant_id, DesignSkill.enabled.is_(True)).all()
    matched_skills = [skill for skill in skills if skill.scope == "general" or (skill.scope == "category" and skill.category == product.category) or (skill.scope == "brand" and skill.brand_name == product.brand_name) or (skill.scope == "product" and skill.product_id == product.id)]
    plan = db.query(CreativePlan).filter(CreativePlan.project_id == project_id).first()
    if not plan:
        plan = CreativePlan(tenant_id=auth.tenant_id, project_id=project_id)
        db.add(plan)
    specs = _module_specs(product)
    plan.product_understanding = {
        "name": product.name,
        "brand": product.brand_name,
        "category": product.category,
        "target_users": product.target_users,
        "core_value": product.description,
        "ingredients": product.ingredients,
        "usage_method": product.usage_method,
        "specifications": product.specifications,
        "image_count": len(product.image_urls or []),
        "knowledge_count": len(documents),
    }
    plan.strategy = {
        "platform": project.platform,
        "recommended_module_count": len(specs),
        "narrative": "先建立商品认知，再解释需求与卖点，随后用成分、质地、场景和使用方式完成信任闭环。",
        "visual_tone": matched_skills[0].visual_rules if matched_skills else "保持商品准确、品牌一致、信息清楚，每屏只表达一个核心结论。",
        "matched_skills": [skill.name for skill in matched_skills],
        "knowledge_titles": [document.title for document in documents],
    }
    plan.status = "draft"
    db.query(StoryboardModule).filter(StoryboardModule.project_id == project_id).delete()
    db.flush()
    modules = []
    for index, spec in enumerate(specs):
        module = StoryboardModule(tenant_id=auth.tenant_id, project_id=project_id, sort_order=index + 1, **spec)
        db.add(module)
        modules.append(module)
    project.status = "planning"
    db.commit()
    db.refresh(plan)
    for module in modules:
        db.refresh(module)
    return _plan_out(plan, modules)


@router.put("/{project_id}/plan/modules", response_model=CreativePlanOut)
def update_plan_modules(project_id: int, payload: StoryboardUpdateRequest, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    project = _project(db, project_id, auth.tenant_id)
    if project.review_status == "finalized": raise HTTPException(409, "项目已定稿，请复制为新项目后再修改")
    plan = db.query(CreativePlan).filter(CreativePlan.project_id == project_id, CreativePlan.tenant_id == auth.tenant_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="详情页策划尚未生成")
    existing = db.query(StoryboardModule).filter(StoryboardModule.project_id == project_id).all()
    if any(module.preview_node_id or module.final_node_id for module in existing):
        raise HTTPException(status_code=409, detail="已有生成结果，请在 Storyboard 中逐项调整")
    db.query(StoryboardModule).filter(StoryboardModule.project_id == project_id).delete()
    modules = []
    for index, item in enumerate(payload.modules):
        values = item.model_dump()
        values["sort_order"] = index + 1
        module = StoryboardModule(tenant_id=auth.tenant_id, project_id=project_id, **values)
        db.add(module)
        modules.append(module)
    plan.status = "confirmed"
    project.status = "storyboard"
    db.commit()
    for module in modules:
        db.refresh(module)
    return _plan_out(plan, modules)


@router.get("/{project_id}/plan/modules/{module_id}/versions", response_model=list[CanvasNodeOut])
def list_module_versions(project_id: int, module_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    _project(db, project_id, auth.tenant_id)
    module = db.query(StoryboardModule).filter(StoryboardModule.id == module_id, StoryboardModule.project_id == project_id, StoryboardModule.tenant_id == auth.tenant_id).first()
    if not module:
        raise HTTPException(status_code=404, detail="Storyboard 模块不存在")
    nodes = db.query(CanvasNode).filter(CanvasNode.project_id == project_id, CanvasNode.tenant_id == auth.tenant_id).order_by(CanvasNode.created_at.desc()).all()
    return [node for node in nodes if node.data.get("storyboard_module_id") == module_id]


@router.put("/{project_id}/plan/modules/{module_id}/selection", response_model=StoryboardModuleOut)
def select_module_version(project_id: int, module_id: int, payload: StoryboardModuleSelectionRequest, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    project = _project(db, project_id, auth.tenant_id)
    _editable(project)
    module = db.query(StoryboardModule).filter(StoryboardModule.id == module_id, StoryboardModule.project_id == project_id, StoryboardModule.tenant_id == auth.tenant_id).first()
    if not module:
        raise HTTPException(status_code=404, detail="Storyboard 模块不存在")
    node = db.query(CanvasNode).filter(CanvasNode.id == payload.node_id, CanvasNode.project_id == project_id, CanvasNode.tenant_id == auth.tenant_id).first()
    if not node or node.data.get("storyboard_module_id") != module_id:
        raise HTTPException(status_code=404, detail="该版本不属于当前模块")
    module.preview_node_id = node.id
    module.final_node_id = node.id if payload.approve else None
    module.status = "approved" if payload.approve else "preview_ready"
    project.status = "designing"
    db.commit(); db.refresh(module)
    return module


@router.post("/{project_id}/plan/modules/{module_id}/quick-edit", response_model=CanvasNodeOut)
def quick_edit_module(project_id: int, module_id: int, payload: StoryboardQuickEditRequest, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    _editable(_project(db, project_id, auth.tenant_id))
    module = db.query(StoryboardModule).filter(StoryboardModule.id == module_id, StoryboardModule.project_id == project_id, StoryboardModule.tenant_id == auth.tenant_id).first()
    source = db.query(CanvasNode).filter(CanvasNode.id == payload.node_id, CanvasNode.project_id == project_id, CanvasNode.tenant_id == auth.tenant_id).first()
    if not module or not source or source.data.get("storyboard_module_id") != module_id:
        raise HTTPException(status_code=404, detail="模块图片版本不存在")
    replacement = db.query(CanvasNode).filter(CanvasNode.id == payload.replacement_node_id, CanvasNode.project_id == project_id, CanvasNode.tenant_id == auth.tenant_id).first() if payload.replacement_node_id else None
    if replacement and replacement.node_type not in {"product", "product_image", "reference", "brand_asset", "detail_image"}:
        raise HTTPException(status_code=400, detail="只能使用商品或素材库图片进行替换")
    edit_source = replacement or source
    try:
        image_url = render_quick_edit(str(edit_source.data.get("image_url") or ""), project_id, payload.headline, payload.subtitle, payload.zoom, payload.offset_x, payload.offset_y, payload.text_x, payload.text_y, payload.font_size, payload.text_color, payload.text_align, payload.text_background)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    node = CanvasNode(id=uuid.uuid4().hex, tenant_id=auth.tenant_id, project_id=project_id, node_type="generated", parent_node_id=source.id, position_x=source.position_x + 40, position_y=source.position_y + 40, data={**source.data, "label": f"{module.title} · 快速编辑", "image_url": image_url, "source": "quick_edit", "replacement_source_node_id": replacement.id if replacement else None, "quick_edit": payload.model_dump()})
    db.add(node); db.flush()
    module.preview_node_id = node.id; module.final_node_id = None; module.status = "preview_ready"
    db.commit(); db.refresh(node)
    return node


@router.post("/{project_id}/style-versions", response_model=CreativePlanOut)
def apply_storyboard_style(project_id: int, payload: StoryboardStyleRequest, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    project = _project(db, project_id, auth.tenant_id)
    _editable(project)
    plan = db.query(CreativePlan).filter(CreativePlan.project_id == project_id, CreativePlan.tenant_id == auth.tenant_id).first()
    modules = db.query(StoryboardModule).filter(StoryboardModule.project_id == project_id, StoryboardModule.tenant_id == auth.tenant_id).order_by(StoryboardModule.sort_order).all()
    snapshot = {str(module.id): {"preview_node_id": module.preview_node_id, "final_node_id": module.final_node_id, "status": module.status} for module in modules}
    changed = 0
    for module in modules:
        source = db.query(CanvasNode).filter(CanvasNode.id == (module.final_node_id or module.preview_node_id), CanvasNode.project_id == project_id).first() if (module.final_node_id or module.preview_node_id) else None
        if not source:
            continue
        try:
            image_url = render_style_adjustment(str(source.data.get("image_url") or ""), project_id, payload.primary_color, payload.accent_color, payload.whitespace, payload.copy_density)
        except ValueError:
            continue
        node = CanvasNode(id=uuid.uuid4().hex, tenant_id=auth.tenant_id, project_id=project_id, node_type="generated", parent_node_id=source.id, position_x=source.position_x + 60, position_y=source.position_y + 60, data={**source.data, "label": f"{module.title} · {payload.name}", "image_url": image_url, "source": "batch_style", "style_settings": payload.model_dump()})
        db.add(node); db.flush(); module.preview_node_id = node.id; module.final_node_id = None; module.status = "preview_ready"; changed += 1
    strategy = dict(plan.strategy or {})
    versions = list(strategy.get("style_versions") or [])
    versions.append({"id": uuid.uuid4().hex, "name": payload.name, "settings": payload.model_dump(), "snapshot": snapshot, "changed": changed})
    strategy["style_versions"] = versions[-10:]
    plan.strategy = strategy; project.status = "designing"
    db.commit()
    return _plan_out(plan, modules)


@router.post("/{project_id}/style-versions/{version_id}/rollback", response_model=CreativePlanOut)
def rollback_storyboard_style(project_id: int, version_id: str, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    _project(db, project_id, auth.tenant_id)
    plan = db.query(CreativePlan).filter(CreativePlan.project_id == project_id, CreativePlan.tenant_id == auth.tenant_id).first()
    modules = db.query(StoryboardModule).filter(StoryboardModule.project_id == project_id, StoryboardModule.tenant_id == auth.tenant_id).order_by(StoryboardModule.sort_order).all()
    version = next((item for item in (plan.strategy or {}).get("style_versions", []) if item.get("id") == version_id), None)
    if not version:
        raise HTTPException(status_code=404, detail="整套风格版本不存在")
    for module in modules:
        saved = version["snapshot"].get(str(module.id))
        if saved:
            module.preview_node_id = saved.get("preview_node_id"); module.final_node_id = saved.get("final_node_id"); module.status = saved.get("status", "preview_ready")
    db.commit()
    return _plan_out(plan, modules)


@router.post("/{project_id}/batch-generate")
def create_batch_generation(project_id: int, payload: StoryboardBatchCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    _project(db, project_id, auth.tenant_id)
    running = db.query(CreativeBatchJob).filter(CreativeBatchJob.project_id == project_id, CreativeBatchJob.tenant_id == auth.tenant_id, CreativeBatchJob.status.in_(["pending", "running"])).first()
    if running:
        return _batch_out(running)
    modules = db.query(StoryboardModule).filter(StoryboardModule.project_id == project_id, StoryboardModule.tenant_id == auth.tenant_id).order_by(StoryboardModule.sort_order).all()
    requested = set(payload.module_ids)
    targets = [module for module in modules if (module.id in requested if requested else not module.preview_node_id)]
    if not targets:
        raise HTTPException(status_code=409, detail="没有需要生成的模块")
    job = CreativeBatchJob(id=uuid.uuid4().hex, tenant_id=auth.tenant_id, project_id=project_id, status="pending", module_ids=[module.id for module in targets], total=len(targets))
    db.add(job); db.commit(); db.refresh(job)
    generation_started = time.perf_counter()
    background_tasks.add_task(_run_storyboard_batch, job.id, auth.tenant_id, auth.user_id, auth.role, auth.email, auth.tenant_name)
    return _batch_out(job)


@router.get("/{project_id}/batch-generate/latest")
def latest_batch_generation(project_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    _project(db, project_id, auth.tenant_id)
    job = db.query(CreativeBatchJob).filter(CreativeBatchJob.project_id == project_id, CreativeBatchJob.tenant_id == auth.tenant_id).order_by(CreativeBatchJob.created_at.desc()).first()
    return _batch_out(job) if job else None


@router.put("/{project_id}/batch-generate/{job_id}/stop")
def stop_batch_generation(project_id: int, job_id: str, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    _project(db, project_id, auth.tenant_id)
    job = db.query(CreativeBatchJob).filter(CreativeBatchJob.id == job_id, CreativeBatchJob.project_id == project_id, CreativeBatchJob.tenant_id == auth.tenant_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="批量任务不存在")
    job.stop_requested = True; db.commit(); db.refresh(job)
    return _batch_out(job)


@router.get("/{project_id}/nodes", response_model=list[CanvasNodeOut])
def list_nodes(project_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    _project(db, project_id, auth.tenant_id)
    return db.query(CanvasNode).filter(CanvasNode.project_id == project_id, CanvasNode.tenant_id == auth.tenant_id).all()


@router.put("/{project_id}/canvas", response_model=list[CanvasNodeOut])
def save_canvas(project_id: int, payload: CanvasSaveRequest, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    project = _project(db, project_id, auth.tenant_id)
    _editable(project)
    incoming_ids = []
    for item in payload.nodes:
        node_id = item.id or uuid.uuid4().hex
        incoming_ids.append(node_id)
        node = db.query(CanvasNode).filter(CanvasNode.id == node_id, CanvasNode.project_id == project_id).first()
        values = item.model_dump(exclude={"id"})
        if not node:
            node = CanvasNode(id=node_id, tenant_id=auth.tenant_id, project_id=project_id, **values)
            db.add(node)
        else:
            for key, value in values.items(): setattr(node, key, value)
    project.viewport = payload.viewport
    db.commit()
    return db.query(CanvasNode).filter(CanvasNode.project_id == project_id).all()


@router.post("/{project_id}/generate")
def generate_variants(project_id: int, payload: CreativeGenerateRequest, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    project = _project(db, project_id, auth.tenant_id)
    if project.review_status == "finalized": raise HTTPException(409, "项目已定稿，请复制为新项目后再生成")
    settings = get_settings()
    running_count = db.query(CreativeGeneration).filter(CreativeGeneration.tenant_id == auth.tenant_id, CreativeGeneration.status == "running").count()
    if running_count >= settings.tenant_max_concurrent_generations:
        raise HTTPException(status_code=429, detail="当前并发生成任务已达上限，请等待已有任务完成")
    product = db.query(Product).filter(Product.id == project.product_id).first()
    storyboard_module = None
    if payload.module_id:
        storyboard_module = db.query(StoryboardModule).filter(StoryboardModule.id == payload.module_id, StoryboardModule.project_id == project_id, StoryboardModule.tenant_id == auth.tenant_id).first()
        if not storyboard_module:
            raise HTTPException(status_code=404, detail="Storyboard 模块不存在")
    project_nodes = db.query(CanvasNode).filter(CanvasNode.project_id == project_id, CanvasNode.tenant_id == auth.tenant_id).all()
    explicit_selected = [node for node in project_nodes if node.id in payload.selected_node_ids]
    parent = db.query(CanvasNode).filter(CanvasNode.id == payload.parent_node_id, CanvasNode.project_id == project_id).first() if payload.parent_node_id else None
    selected = explicit_selected
    selection_strategy = "manual"
    material_reasons: dict[str, str] = {node.id: "设计师手动选择" for node in explicit_selected}
    if payload.auto_select_materials:
        approved_nodes = [node for node in project_nodes if node.node_type in {"generated", "refined", "deliverable"} and (node.data.get("is_final") or node.data.get("review_status") in {"usable", "final"}) and node.data.get("image_url")]
        selected, selection_strategy, material_reasons = _smart_materials(storyboard_module, project_nodes, explicit_selected)
        if storyboard_module and storyboard_module.module_type not in {"hero", "product_showcase"} and approved_nodes:
            selected.append(approved_nodes[-1]); material_reasons[approved_nodes[-1].id] = "沿用已定稿视觉，保持整套详情页一致"
        selected = list({node.id: node for node in selected}.values())
    source_node = parent or next((node for node in reversed(selected) if node.node_type in {"deliverable", "refined", "generated"} and node.data.get("image_url")), None) or next((node for node in selected if node.data.get("image_url")), None)
    source_url = source_node.data.get("image_url", "") if source_node else ((product.image_urls or [""])[0])
    brand_docs = db.query(KnowledgeDocument).filter(KnowledgeDocument.tenant_id == auth.tenant_id, KnowledgeDocument.brand_name == product.brand_name).all()
    all_skills = db.query(DesignSkill).filter(DesignSkill.tenant_id == auth.tenant_id, DesignSkill.enabled.is_(True)).all()
    matched_skills = [skill for skill in all_skills if skill.scope == "general" or (skill.scope == "category" and skill.category == product.category) or (skill.scope == "brand" and skill.brand_name == product.brand_name) or (skill.scope == "product" and skill.product_id == product.id)]
    learned = db.query(LearnedDesignProfile).filter(LearnedDesignProfile.tenant_id == auth.tenant_id, LearnedDesignProfile.brand_name == product.brand_name, LearnedDesignProfile.category == product.category).first() if product.learned_profile_enabled else None
    brand_profile = db.query(BrandVisualProfile).filter(BrandVisualProfile.tenant_id == auth.tenant_id, BrandVisualProfile.brand_name == product.brand_name).first()
    confirmed_facts = db.query(ProductFact).filter(ProductFact.tenant_id == auth.tenant_id, ProductFact.product_id == product.id, ProductFact.status == "confirmed").all()
    context_snapshot = {
        "product": {"id": product.id, "name": product.name, "brand": product.brand_name, "category": product.category, "ingredients": product.ingredients, "specifications": product.specifications},
        "confirmed_facts": [{"key": fact.fact_key, "label": fact.label, "value": fact.value, "source": fact.source_ref} for fact in confirmed_facts],
        "material_selection": {"mode": "auto" if payload.auto_select_materials else "manual", "strategy": selection_strategy, "count": len(selected)},
        "selected_nodes": [{"id": node.id, "type": node.node_type, "role": _material_role(node), "label": node.data.get("label"), "image_url": node.data.get("image_url"), "reason": material_reasons.get(node.id, "自动匹配")} for node in selected],
        "brand_documents": [{"id": doc.id, "title": doc.title} for doc in brand_docs],
        "design_skills": [{"id": skill.id, "name": skill.name, "scope": skill.scope, "visual_rules": skill.visual_rules} for skill in matched_skills],
        "learned_profile": {"status": learned.status, "confidence": learned.confidence, "rules": learned.learned_rules} if learned else None,
        "project_brief": project.brief,
        "module_id": payload.module_id,
        "requested_count": payload.count,
        "brand_visual": {"primary_color": brand_profile.primary_color, "accent_color": brand_profile.accent_color, "typography": brand_profile.typography, "visual_keywords": brand_profile.visual_keywords, "forbidden_elements": brand_profile.forbidden_elements} if brand_profile else None,
        "parameter_version": get_settings().generation_parameter_version,
        "seed": None,
        "seed_supported": False,
    }
    module_prompt = ""
    if storyboard_module:
        module_prompt = f"\n详情页模块：{storyboard_module.title}\n模块目标：{storyboard_module.objective}\n内容要求：{storyboard_module.content_guidance}\n视觉方向：{storyboard_module.visual_direction}"
    brand_prompt = f"\n品牌视觉规范：主色 {brand_profile.primary_color}，辅助色 {brand_profile.accent_color}，字体气质 {brand_profile.typography}，视觉关键词 {'、'.join(brand_profile.visual_keywords)}，禁止出现 {'、'.join(brand_profile.forbidden_elements)}。Logo 必须作为原始素材直接使用，禁止重绘、变形或修改文字。{brand_profile.tone_notes}" if brand_profile else ""
    fact_prompt = "\n已确认商品事实（只能使用这些事实，不得采用冲突或待确认信息）：\n" + "\n".join(f"- {fact.label}：{fact.value}" for fact in confirmed_facts) if confirmed_facts else ""
    raw_prompt = f"{project.brief}\n{payload.prompt}{module_prompt}{brand_prompt}{fact_prompt}\n品牌：{product.brand_name}；商品：{product.name}；已匹配 Skill：{'、'.join(skill.name for skill in matched_skills) or '无'}"
    prompt_check=validate_and_rewrite_prompt(raw_prompt,storyboard_module.title if storyboard_module else payload.action,[{"id":f.id} for f in confirmed_facts])
    effective_prompt = apply_generation_controls(prompt_check["corrected"], payload.product_lock, payload.variation_axis, payload.generation_stage)
    context_snapshot["prompt_check"]=prompt_check
    context_snapshot["generation_controls"]={"product_lock":payload.product_lock,"variation_axis":payload.variation_axis,"stage":payload.generation_stage}
    context_snapshot["source_admission"]=[{"url":url,"result":inspect_source(url)} for url in ([source_url] if source_url else [])]
    main_image_roles = ["主封面", "核心卖点", "套装内容", "成分质地", "使用场景"] if payload.action == "生成主图套系" else []
    output_count = len(main_image_roles) or (max(4,payload.count) if storyboard_module and storyboard_module.production_method!="template" else payload.count)
    is_template = bool(storyboard_module and storyboard_module.production_method == "template")
    route_key=(storyboard_module.module_type if storyboard_module else payload.action)+("_edit" if payload.parent_node_id else "");context_snapshot["model_route"]=route_key
    provider = None if is_template else get_image_provider(route_key)
    job = CreativeGeneration(
        tenant_id=auth.tenant_id, project_id=project_id, parent_node_id=payload.parent_node_id,
        prompt=payload.prompt, action=payload.action, selected_node_ids=[node.id for node in selected],
        provider="template_renderer" if is_template else provider.name, status="running", context_snapshot=context_snapshot,
    )
    db.add(job); db.commit(); db.refresh(job)
    try:
        source_urls = [node.data.get("image_url") for node in selected if node.data.get("image_url")]
        if brand_profile and brand_profile.logo_url and storyboard_module and storyboard_module.module_type in {"hero", "brand"}:
            source_urls.append(brand_profile.logo_url)
        urls = [render_storyboard_template(product, storyboard_module, project.id, brand_profile)] if is_template else provider.generate(source_url=source_url, source_urls=source_urls, variant_labels=main_image_roles or None, prompt=effective_prompt, action=payload.action, count=output_count, width=project.output_width, height=project.output_height, project_id=project.id)
        lock_results=[]
        source_asset=db.query(ProductAsset).filter_by(product_id=product.id,tenant_id=auth.tenant_id,file_url=source_url).first() if source_url else None;protection=(source_asset.protection or {}) if source_asset else {}
        if payload.product_lock in {"strict","balanced"} and source_url and not is_template:
            locked=[]
            for url in urls:
                try:
                    locked_url=hard_lock_product(source_url,url,project.id,protection) if payload.product_lock=="strict" else restore_protected_regions(source_url,url,list(protection.get("protected_regions") or []),project.id)
                    locked.append(locked_url);lock_results.append({"source":url,"status":"applied","mask_source":protection.get("mask_source"),"protected_region_count":len(protection.get("protected_regions") or [])})
                except ValueError as exc:locked.append(url);lock_results.append({"source":url,"status":"unavailable","message":str(exc)})
            urls=locked
        candidate_similarity=duplicate_report(urls)
        context_snapshot["hard_lock_results"]=lock_results;context_snapshot["candidate_similarity"]=candidate_similarity
        db.refresh(job)
        if job.status == "cancelled":
            job.duration_ms = int((time.perf_counter() - generation_started) * 1000); db.commit()
            return {"generation": CreativeGenerationOut.model_validate(job), "nodes": []}
        max_x = max([node.position_x for node in db.query(CanvasNode).filter(CanvasNode.project_id == project_id).all()] or [0])
        base_y = parent.position_y if parent else 0
        result_ids = []
        scored=[(url,score_output(url,storyboard_module.module_type if storyboard_module else "general",context_snapshot.get("brand_visual"))) for url in urls]
        duplicate_indices={pair["right"] for pair in candidate_similarity.get("duplicates",[])}
        ranked=sorted(range(len(scored)),key=lambda i:((i not in duplicate_indices),scored[i][1]["total"]),reverse=True);shortlist=set([i for i in ranked if i not in duplicate_indices][:2])
        for index, (url,quality) in enumerate(scored):
            node_id = uuid.uuid4().hex
            result_ids.append(node_id)
            db.add(CanvasNode(
                id=node_id, tenant_id=auth.tenant_id, project_id=project_id, node_type="generated",
                parent_node_id=payload.parent_node_id, position_x=max_x + 340, position_y=base_y + index * 360,
                data={"label": storyboard_module.title if storyboard_module else (f"主图套系 · {main_image_roles[index]}" if main_image_roles else f"AI 方案 {chr(65 + index)}"), "image_url": url, "prompt": payload.prompt, "effective_prompt":effective_prompt,"action": payload.action, "storyboard_module_id": storyboard_module.id if storyboard_module else None, "module_role": storyboard_module.module_type if storyboard_module else (main_image_roles[index] if main_image_roles else None), "suite_type": "detail_page" if storyboard_module else ("main_image" if main_image_roles else None), "generation_id": job.id, "provider": "template_renderer" if is_template else provider.name,"quality_scores":quality,"auto_shortlisted":index in shortlist,"repair_instruction":repair_instruction(quality),"generation_stage":payload.generation_stage,"product_lock":payload.product_lock,"variation_axis":payload.variation_axis,"candidate_similarity":candidate_similarity, "context_summary": {"material_strategy": selection_strategy, "materials": [{"id": item.id, "type": item.node_type, "role": _material_role(item), "label": item.data.get("label"), "reason": material_reasons.get(item.id, "自动匹配")} for item in selected], "brand_documents": [{"id": doc.id, "title": doc.title} for doc in brand_docs], "skills": [{"id": skill.id, "name": skill.name, "scope": skill.scope} for skill in matched_skills], "learned_profile": bool(learned)}},
            ))
        if storyboard_module and result_ids:
            storyboard_module.preview_node_id = result_ids[ranked[0] if ranked else 0]
            storyboard_module.status = "preview_ready"
        job.result_node_ids = result_ids; job.status = "completed"; job.duration_ms = int((time.perf_counter() - generation_started) * 1000); db.commit(); db.refresh(job)
    except Exception as exc:
        diagnostic = diagnose_generation_error(exc)
        job.status = "failed"; job.error_message = diagnostic["title"]; job.duration_ms = int((time.perf_counter() - generation_started) * 1000)
        job.context_snapshot = {**(job.context_snapshot or {}), "diagnostic": diagnostic}
        db.commit()
        raise HTTPException(status_code=500, detail=diagnostic)
    nodes = db.query(CanvasNode).filter(CanvasNode.id.in_(job.result_node_ids)).all()
    return {"generation": CreativeGenerationOut.model_validate(job), "nodes": [CanvasNodeOut.model_validate(node) for node in nodes]}


@router.get("/{project_id}/compliance")
def storyboard_compliance(project_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    project = _project(db, project_id, auth.tenant_id)
    product = db.query(Product).filter(Product.id == project.product_id, Product.tenant_id == auth.tenant_id).first()
    modules = db.query(StoryboardModule).filter(StoryboardModule.project_id == project_id, StoryboardModule.tenant_id == auth.tenant_id).order_by(StoryboardModule.sort_order).all()
    documents = db.query(KnowledgeDocument).filter(KnowledgeDocument.tenant_id == auth.tenant_id, ((KnowledgeDocument.product_id == product.id) | (KnowledgeDocument.brand_name == product.brand_name))).all()
    report = check_storyboard_compliance(product, modules, documents)
    nodes = {node.id: node for node in db.query(CanvasNode).filter(CanvasNode.project_id == project_id, CanvasNode.tenant_id == auth.tenant_id).all()}
    visual_quality = check_visual_quality(modules, nodes, project.output_width)
    report["visual_quality"] = visual_quality
    report["score"] = min(report["score"], visual_quality["score"])
    if visual_quality["status"] == "blocked":
        report["status"] = "blocked"
    elif visual_quality["status"] == "review" and report["status"] == "passed":
        report["status"] = "review"
    return report


@router.post("/{project_id}/product-consistency")
async def product_consistency(project_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    project = _project(db, project_id, auth.tenant_id)
    product = db.query(Product).filter(Product.id == project.product_id, Product.tenant_id == auth.tenant_id).first()
    modules = db.query(StoryboardModule).filter(StoryboardModule.project_id == project_id, StoryboardModule.tenant_id == auth.tenant_id).order_by(StoryboardModule.sort_order).all()
    node_ids = [module.final_node_id or module.preview_node_id for module in modules if module.final_node_id or module.preview_node_id]
    nodes = db.query(CanvasNode).filter(CanvasNode.project_id == project_id, CanvasNode.id.in_(node_ids)).all() if node_ids else []
    node_map = {node.id: node for node in nodes}
    outputs = [{"module_id": module.id, "title": module.title, "image_url": str(node_map[module.final_node_id or module.preview_node_id].data.get("image_url") or "")} for module in modules if (module.final_node_id or module.preview_node_id) in node_map]
    benchmarks = db.query(ProductAsset).filter(ProductAsset.product_id == product.id, ProductAsset.tenant_id == auth.tenant_id, ProductAsset.benchmark_role != "none", ProductAsset.excluded.is_(False)).order_by(ProductAsset.priority.desc()).all()
    references = [asset.file_url for asset in benchmarks] or list(product.image_urls or [])
    report = await compare_product_images(product.name, references, outputs)
    facts = db.query(ProductFact).filter(ProductFact.product_id == product.id, ProductFact.tenant_id == auth.tenant_id, ProductFact.status == "confirmed").all()
    report["evidence"] = {"benchmark_images": [{"asset_id": asset.id, "role": asset.benchmark_role, "name": asset.name, "file_url": asset.file_url} for asset in benchmarks], "confirmed_facts": [{"id": fact.id, "label": fact.label, "value": fact.value, "source_type": fact.source_type, "source_ref": fact.source_ref} for fact in facts]}
    return report

@router.get("/{project_id}/quality-summary")
def quality_summary(project_id:int,db:Session=Depends(get_db),auth:AuthContext=Depends(current_auth)):
    project=_project(db,project_id,auth.tenant_id);modules=db.query(StoryboardModule).filter_by(project_id=project_id,tenant_id=auth.tenant_id).order_by(StoryboardModule.sort_order).all();rows=[]
    for module in modules:
        node=db.query(CanvasNode).filter_by(id=module.final_node_id or module.preview_node_id,tenant_id=auth.tenant_id).first() if (module.final_node_id or module.preview_node_id) else None
        scores=(node.data or {}).get("quality_scores") if node else None
        rows.append({"module_id":module.id,"title":module.title,"status":module.status,"node_id":node.id if node else None,"image_url":node.data.get("image_url") if node else "","scores":scores,"repair_instruction":node.data.get("repair_instruction") if node else ""})
    valid=[r["scores"] for r in rows if r["scores"]];totals=[s["total"] for s in valid]
    duplicate_types={};issues=[]
    for r in rows:
        if r["scores"] and r["scores"]["total"]<65:issues.append({"module_id":r["module_id"],"severity":"high","message":"候选质量低于提交阈值","suggestion":r["repair_instruction"]})
        key=next((x for x in ["hero","product_showcase","scenario","texture"] if x in r["title"].lower()),r["title"])
        duplicate_types[key]=duplicate_types.get(key,0)+1
    return {"status":"blocked" if any(i["severity"]=="high" for i in issues) else "passed","score":round(sum(totals)/len(totals)) if totals else 0,"module_count":len(rows),"scored_count":len(valid),"modules":rows,"issues":issues,"consistency":{"score":round(sum(totals)/len(totals)) if totals else 0,"message":"基于各屏商品一致性、品牌匹配和商业审美综合分检查整套稳定性"}}


@router.post("/{project_id}/quality-summary/vision")
async def vision_quality_summary(project_id:int,db:Session=Depends(get_db),auth:AuthContext=Depends(current_auth)):
    project=_project(db,project_id,auth.tenant_id);product=db.query(Product).filter_by(id=project.product_id,tenant_id=auth.tenant_id).first()
    modules=db.query(StoryboardModule).filter_by(project_id=project_id,tenant_id=auth.tenant_id).order_by(StoryboardModule.sort_order).all();outputs=[];nodes=[]
    for module in modules:
        node=db.query(CanvasNode).filter_by(id=module.final_node_id or module.preview_node_id,tenant_id=auth.tenant_id).first() if (module.final_node_id or module.preview_node_id) else None
        if node and node.data.get("image_url"):nodes.append(node);outputs.append({"module_id":module.id,"title":module.title,"image_url":node.data["image_url"]})
    assets=db.query(ProductAsset).filter(ProductAsset.product_id==product.id,ProductAsset.tenant_id==auth.tenant_id,ProductAsset.benchmark_role!="none",ProductAsset.excluded.is_(False)).order_by(ProductAsset.priority.desc()).all()
    references=[asset.file_url for asset in assets] or list(product.image_urls or [])
    quality_rule_set=db.query(QualityRuleSet).filter_by(tenant_id=auth.tenant_id,category=product.category).first();quality_rules=list(quality_rule_set.rules or []) if quality_rule_set else []
    reports=[];all_items=[];all_issues=[]
    for start in range(0,len(outputs),4):
        report=await review_commercial_suite(product.name,product.brand_name,references,outputs[start:start+4],quality_rules)
        if report.get("status")=="unavailable":raise HTTPException(503,report)
        reports.append(report);items=report.get("items") or [];all_items.extend(items);all_issues.extend(report.get("issues") or [])
        for offset,item in enumerate(items):
            if start+offset>=len(nodes):break
            node=nodes[start+offset];node.data={**node.data,"vision_quality":item,"vision_quality_suite":{"status":report.get("status"),"score":report.get("score"),"suite_consistency":report.get("suite_consistency"),"model":report.get("model"),"is_real_model":True}}
    suite_report=None
    try:
        sheet=contact_sheet([row["image_url"] for row in outputs],project_id);suite_report=await review_commercial_suite(product.name,product.brand_name,[],[{"image_url":sheet}],quality_rules)
    except ValueError:pass
    statuses=[report.get("status") for report in reports]+([suite_report.get("status")] if suite_report else []);status="blocked" if "blocked" in statuses else "review" if "review" in statuses else "passed";score=round(sum(float(report.get("score",0)) for report in reports)/len(reports)) if reports else 0
    combined={"status":status,"score":score,"checked_count":len(all_items),"items":all_items,"issues":all_issues,"batches":len(reports),"suite_consistency":suite_report.get("suite_consistency") if suite_report else None,"model":reports[0].get("model") if reports else "","is_real_model":True}
    for node in nodes:
        saved=dict(node.data.get("vision_quality_suite") or {});node.data={**node.data,"vision_quality_suite":{**saved,"status":status,"score":score,"suite_consistency":combined["suite_consistency"],"is_real_model":True}}
    protection_asset=next((asset for asset in assets if (asset.protection or {}).get("protected_regions")),None)
    if protection_asset:
        for node in nodes:
            ocr=await compare_protected_text(protection_asset.file_url,str(node.data.get("image_url") or ""),list(protection_asset.protection.get("protected_regions") or []));node.data={**node.data,"protected_text_check":ocr}
    db.commit();return combined

@router.post("/{project_id}/nodes/{node_id}/retry-by-quality")
def retry_by_quality(project_id:int,node_id:str,db:Session=Depends(get_db),auth:AuthContext=Depends(current_auth)):
    node=db.query(CanvasNode).filter_by(id=node_id,project_id=project_id,tenant_id=auth.tenant_id).first()
    if not node:raise HTTPException(404,"图片版本不存在")
    module_id=node.data.get("storyboard_module_id");instruction=node.data.get("repair_instruction") or "保持商品准确，优化构图和品牌一致性"
    return generate_variants(project_id,CreativeGenerateRequest(prompt=instruction,action="按质检建议重试",selected_node_ids=[node.id],parent_node_id=node.id,auto_select_materials=True,module_id=module_id,count=4),db,auth)

@router.get("/{project_id}/approval-issues")
def approval_issues(project_id:int,db:Session=Depends(get_db),auth:AuthContext=Depends(current_auth)):
    _project(db,project_id,auth.tenant_id);return db.query(ApprovalIssue).filter_by(project_id=project_id,tenant_id=auth.tenant_id).order_by(ApprovalIssue.created_at.desc()).all()

@router.post("/{project_id}/plan/modules/{module_id}/reject")
def reject_module(project_id:int,module_id:int,payload:dict,db:Session=Depends(get_db),auth:AuthContext=Depends(current_auth)):
    project=_project(db,project_id,auth.tenant_id);_editable(project);module=db.query(StoryboardModule).filter_by(id=module_id,project_id=project_id,tenant_id=auth.tenant_id).first()
    if not module:raise HTTPException(404,"模块不存在")
    region=dict(payload.get("region") or {});regions=list(payload.get("regions") or [])
    if regions:region={"regions":regions}
    issue=ApprovalIssue(tenant_id=auth.tenant_id,project_id=project_id,module_id=module_id,source_node_id=module.final_node_id or module.preview_node_id,issue_type=str(payload.get("issue_type") or "其他问题"),severity=str(payload.get("severity") or "medium"),action=str(payload.get("action") or "regenerate"),note=str(payload.get("note") or ""),region=region,created_by=auth.user_id);db.add(issue);module.status="needs_revision";db.commit();db.refresh(issue);return issue

@router.post("/{project_id}/approval-issues/{issue_id}/resolve")
def resolve_issue(project_id:int,issue_id:int,payload:dict,db:Session=Depends(get_db),auth:AuthContext=Depends(current_auth)):
    issue=db.query(ApprovalIssue).filter_by(id=issue_id,project_id=project_id,tenant_id=auth.tenant_id).first()
    if not issue:raise HTTPException(404,"修改任务不存在")
    node_id=str(payload.get("node_id") or "");node=db.query(CanvasNode).filter_by(id=node_id,project_id=project_id).first()
    if not node:raise HTTPException(404,"解决版本不存在")
    issue.resolved_node_id=node.id;issue.status="resolved";issue.resolved_by=auth.user_id;issue.resolved_at=datetime.utcnow();module=db.query(StoryboardModule).filter_by(id=issue.module_id).first();module.preview_node_id=node.id;module.status="preview_ready";db.commit();return issue


@router.post("/{project_id}/approval-issues/{issue_id}/regional-regenerate")
def regional_regenerate(project_id:int,issue_id:int,db:Session=Depends(get_db),auth:AuthContext=Depends(current_auth)):
    project=_project(db,project_id,auth.tenant_id);_editable(project)
    issue=db.query(ApprovalIssue).filter_by(id=issue_id,project_id=project_id,tenant_id=auth.tenant_id,status="open").first()
    if not issue:raise HTTPException(404,"待处理的框选修改任务不存在")
    regions=list((issue.region or {}).get("regions") or [issue.region or {}])
    if not any(float(item.get("width",0))>0 and float(item.get("height",0))>0 for item in regions):raise HTTPException(409,"该任务没有有效框选区域")
    source=db.query(CanvasNode).filter_by(id=issue.source_node_id,project_id=project_id,tenant_id=auth.tenant_id).first()
    if not source:raise HTTPException(404,"驳回原图不存在")
    provider=get_image_provider("regional_edit")
    if provider.name!="ark_seedream":raise HTTPException(503,"未配置真实 Seedream 模型，已保留框选任务但不会伪造局部修改结果")
    original_url=str(source.data.get("image_url") or "")
    region=issue.region;prompt=f"只修正红框所指区域的问题：{issue.issue_type}。{issue.note}。框外画面必须保持不变，不得改变商品瓶型、包装、Logo、文字和数量。"
    edited=provider.generate(source_url=original_url,source_urls=[original_url],prompt=prompt,action="框选局部修改",count=1,width=project.output_width,height=project.output_height,project_id=project_id)[0]
    final_url=regional_composite(original_url,edited,region,project_id)
    product=db.query(Product).filter_by(id=project.product_id,tenant_id=auth.tenant_id).first();assets=db.query(ProductAsset).filter(ProductAsset.product_id==product.id,ProductAsset.tenant_id==auth.tenant_id,ProductAsset.benchmark_role!="none",ProductAsset.excluded.is_(False)).all();references=[a.file_url for a in assets] or list(product.image_urls or []);recheck=asyncio.run(review_commercial_suite(product.name,product.brand_name,references,[{"image_url":final_url}]))
    passed=recheck.get("status")=="passed" and bool(recheck.get("items"));item=(recheck.get("items") or [{}])[0]
    node=CanvasNode(id=uuid.uuid4().hex,tenant_id=auth.tenant_id,project_id=project_id,node_type="generated",parent_node_id=source.id,position_x=source.position_x+40,position_y=source.position_y+40,data={**source.data,"image_url":final_url,"label":f"{source.data.get('label','图片')} · 局部修改","source":"regional_seedream_composite","regional_edit":{"issue_id":issue.id,"region":region,"model_output":edited,"automatic_recheck":recheck},"vision_quality":item,"vision_quality_suite":{"status":recheck.get("status"),"score":recheck.get("score"),"model":recheck.get("model"),"is_real_model":True}})
    db.add(node);db.flush()
    if passed:issue.resolved_node_id=node.id;issue.status="resolved";issue.resolved_by=auth.user_id;issue.resolved_at=datetime.utcnow()
    else:issue.note=f"{issue.note}\n自动复检未通过：{recheck.get('summary') or recheck.get('message') or '需继续修改'}"
    module=db.query(StoryboardModule).filter_by(id=issue.module_id,project_id=project_id).first();module.preview_node_id=node.id;module.final_node_id=None;module.status="preview_ready" if passed else "needs_revision"
    db.commit();db.refresh(node);return {"issue":issue,"node":node}


@router.post("/{project_id}/nodes/{node_id}/finalize-hd")
def finalize_hd(project_id:int,node_id:str,db:Session=Depends(get_db),auth:AuthContext=Depends(current_auth)):
    project=_project(db,project_id,auth.tenant_id);_editable(project)
    source=db.query(CanvasNode).filter_by(id=node_id,project_id=project_id,tenant_id=auth.tenant_id).first()
    if not source:raise HTTPException(404,"图片版本不存在")
    url=str(source.data.get("image_url") or "");provider=get_image_provider("4k_final_upscale")
    if provider.name!="ark_seedream":raise HTTPException(503,"未配置真实 Seedream，禁止用普通插值冒充高清修复")
    ratio=project.output_width/max(1,project.output_height);width=4096 if ratio>=1 else round(4096*ratio);height=round(4096/ratio) if ratio>=1 else 4096
    final_prompt=f"将输入图修复为4K商业交付稿。严格保持构图和商品，修复商品边缘、包装文字、Logo、材质、手指、倒影和光影融合。不得新增文字或改变商品数量。"
    final_url=provider.generate(source_url=url,source_urls=[url],prompt=final_prompt,action="4K高清修复",count=1,width=width,height=height,project_id=project_id)[0]
    product=db.query(Product).filter_by(id=project.product_id,tenant_id=auth.tenant_id).first();assets=db.query(ProductAsset).filter(ProductAsset.product_id==product.id,ProductAsset.tenant_id==auth.tenant_id,ProductAsset.benchmark_role!="none",ProductAsset.excluded.is_(False)).order_by(ProductAsset.priority.desc()).all();references=[asset.file_url for asset in assets] or list(product.image_urls or [])
    report=asyncio.run(review_commercial_suite(product.name,product.brand_name,references,[{"image_url":final_url}]))
    if report.get("status") in {"unavailable","blocked"} or not report.get("items") or min(report["items"][0].get("product_consistency",0),report["items"][0].get("brand_match",0),report["items"][0].get("commercial_aesthetic",0))<65:raise HTTPException(409,{"message":"4K修复结果未通过真实视觉模型终检","final_checks":report})
    quality=score_output(final_url,str(source.data.get("module_role") or "general"),None);terminal_checks={"vision":report,"quality_scores":quality,"is_real_model":True}
    node=CanvasNode(id=uuid.uuid4().hex,tenant_id=auth.tenant_id,project_id=project_id,node_type="deliverable",parent_node_id=source.id,position_x=source.position_x+40,position_y=source.position_y+40,data={**source.data,"image_url":final_url,"label":f"{source.data.get('label','图片')} · 4K高清终稿","generation_stage":"final","final_quality_checks":terminal_checks,"vision_quality":report["items"][0],"vision_quality_suite":{"status":report.get("status"),"score":report.get("score"),"suite_consistency":report.get("suite_consistency"),"model":report.get("model"),"is_real_model":True},"is_final":True})
    db.add(node);module_id=source.data.get("storyboard_module_id");module=db.query(StoryboardModule).filter_by(id=module_id,project_id=project_id).first() if module_id else None
    if module:module.preview_node_id=node.id;module.final_node_id=node.id;module.status="approved"
    db.commit();db.refresh(node);return node


@router.get("/{project_id}/quality-regression")
async def quality_regression(project_id:int,db:Session=Depends(get_db),auth:AuthContext=Depends(current_auth)):
    project=_project(db,project_id,auth.tenant_id);product=db.query(Product).filter_by(id=project.product_id,tenant_id=auth.tenant_id).first();settings=get_settings()
    expected=[("hero","首屏商品准确"),("product_showcase","商品展示"),("texture","材质细节"),("ingredient","成分表达"),("scenario","使用场景"),("information","产品信息")]
    saved_samples=db.query(RegressionSample).filter(RegressionSample.tenant_id==auth.tenant_id,RegressionSample.enabled.is_(True),RegressionSample.category.in_(["general",product.category])).all()
    for sample in saved_samples:
        if not any(case_type==sample.case_type for case_type,_ in expected):expected.append((sample.case_type,sample.name))
    modules=db.query(StoryboardModule).filter_by(project_id=project_id,tenant_id=auth.tenant_id).all();assets=db.query(ProductAsset).filter(ProductAsset.product_id==product.id,ProductAsset.tenant_id==auth.tenant_id,ProductAsset.benchmark_role!="none",ProductAsset.excluded.is_(False)).all();references=[a.file_url for a in assets] or list(product.image_urls or [])
    cases=[]
    for module_type,label in expected:
        module=next((m for m in modules if m.module_type==module_type),None);node=db.query(CanvasNode).filter_by(id=module.final_node_id or module.preview_node_id,tenant_id=auth.tenant_id).first() if module and (module.final_node_id or module.preview_node_id) else None
        if not node:cases.append({"case_id":module_type,"label":label,"passed":False,"reason":"缺少固定基准用例输出"});continue
        report=await review_commercial_suite(product.name,product.brand_name,references,[{"image_url":node.data.get("image_url")}])
        if report.get("status")=="unavailable":raise HTTPException(503,report)
        item=(report.get("items") or [{}])[0];score=round((item.get("product_consistency",0)*.5+item.get("brand_match",0)*.25+item.get("commercial_aesthetic",0)*.25));cases.append({"case_id":module_type,"label":label,"module_id":module.id,"score":score,"scores":item,"passed":report.get("status")!="blocked" and score>=75})
    failed=[case for case in cases if not case["passed"]];score=round(sum(case.get("score",0) for case in cases)/len(cases));previous=db.query(QualityRegressionRun).filter_by(project_id=project_id,tenant_id=auth.tenant_id,suite_version="commerce-v1").order_by(QualityRegressionRun.created_at.desc()).first();delta=round(score-previous.score,1) if previous else None
    result={"suite":f"{product.category or '通用'}电商固定回归集","suite_version":"commerce-v1","model":settings.llm_vision_model,"baseline":{"total":75},"case_count":len(cases),"passed":len(cases)-len(failed),"failed":len(failed),"score":score,"previous_score":previous.score if previous else None,"delta":delta,"status":"passed" if not failed else "failed","cases":cases}
    db.add(QualityRegressionRun(tenant_id=auth.tenant_id,project_id=project_id,suite_version="commerce-v1",model=settings.llm_vision_model,provider=get_image_provider().name,score=score,status=result["status"],results=result));db.commit();return result


@router.post("/{project_id}/export")
def export_storyboard(project_id: int, confirm_risks: bool = False, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    project = _project(db, project_id, auth.tenant_id)
    modules = db.query(StoryboardModule).filter(StoryboardModule.project_id == project_id, StoryboardModule.tenant_id == auth.tenant_id).order_by(StoryboardModule.sort_order).all()
    product = db.query(Product).filter(Product.id == project.product_id, Product.tenant_id == auth.tenant_id).first()
    documents = db.query(KnowledgeDocument).filter(KnowledgeDocument.tenant_id == auth.tenant_id, ((KnowledgeDocument.product_id == product.id) | (KnowledgeDocument.brand_name == product.brand_name))).all()
    compliance = check_storyboard_compliance(product, modules, documents)
    nodes_by_id = {node.id: node for node in db.query(CanvasNode).filter(CanvasNode.project_id == project_id, CanvasNode.tenant_id == auth.tenant_id).all()}
    missing_real_vision=[module.title for module in modules if (module.final_node_id or module.preview_node_id) and not ((nodes_by_id.get(module.final_node_id or module.preview_node_id).data.get("vision_quality_suite") or {}).get("is_real_model") if nodes_by_id.get(module.final_node_id or module.preview_node_id) else False)]
    if missing_real_vision:raise HTTPException(409,{"message":"导出前必须完成真实视觉模型质检","missing_modules":missing_real_vision})
    visual_quality = check_visual_quality(modules, nodes_by_id, project.output_width)
    compliance["visual_quality"] = visual_quality
    compliance["score"] = min(compliance["score"], visual_quality["score"])
    if visual_quality["status"] == "blocked":
        compliance["status"] = "blocked"
    elif visual_quality["status"] == "review" and compliance["status"] == "passed":
        compliance["status"] = "review"
    if compliance["status"] == "blocked" and not confirm_risks:
        raise HTTPException(status_code=409, detail={"message": "存在高风险宣称，请人工确认后再导出", "compliance": compliance})
    images: list[Image.Image] = []
    missing: list[str] = []
    for module in modules:
        node_id = module.final_node_id or module.preview_node_id
        node = db.query(CanvasNode).filter(CanvasNode.id == node_id, CanvasNode.project_id == project_id).first() if node_id else None
        image_url = node.data.get("image_url") if node else None
        if not image_url or image_url.startswith(("http://", "https://", "data:")):
            missing.append(module.title)
            continue
        path = get_storage().local_path(image_url)
        if not path:
            missing.append(module.title)
            continue
        source = Image.open(path).convert("RGB")
        target_height = max(1, round(source.height * project.output_width / source.width))
        images.append(ImageOps.fit(source, (project.output_width, target_height), method=Image.Resampling.LANCZOS))
    if not images:
        raise HTTPException(status_code=409, detail="请至少生成一个模块后再预览整套详情页")
    long_image = Image.new("RGB", (project.output_width, sum(image.height for image in images)), "white")
    offset = 0
    for image in images:
        long_image.paste(image, (0, offset))
        offset += image.height
    filename = f"detail-page-{project_id}-{uuid.uuid4().hex[:8]}.jpg"
    output=BytesIO();long_image.save(output,"JPEG",quality=92,optimize=True)
    url=get_storage().save_bytes(output.getvalue(),filename,"exports")
    return {"long_image_url": url, "module_count": len(images), "missing_modules": missing, "compliance": compliance}


@router.post("/{project_id}/refined-output", response_model=CanvasNodeOut)
async def upload_refined_output(project_id: int, file: UploadFile = File(...), parent_node_id: str = Form(""), db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    _project(db, project_id, auth.tenant_id)
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(status_code=415, detail="精修成品必须是图片")
    url = await get_storage().upload(await file.read(), file.filename or "refined.png", "creative")
    parent = db.query(CanvasNode).filter(CanvasNode.id == parent_node_id, CanvasNode.project_id == project_id).first() if parent_node_id else None
    node = CanvasNode(
        id=uuid.uuid4().hex, tenant_id=auth.tenant_id, project_id=project_id, node_type="refined",
        parent_node_id=parent_node_id or None, position_x=(parent.position_x + 340 if parent else 600), position_y=(parent.position_y if parent else 0),
        data={"label": "设计师精修成品", "image_url": url, "source": "designer_refined", "filename": file.filename},
    )
    db.add(node); db.commit(); db.refresh(node); return node


@router.post("/{project_id}/deliverable", response_model=CanvasNodeOut)
async def submit_final_design(
    project_id: int,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    parent_node_id: str = Form(""),
    note: str = Form(""),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(current_auth),
):
    project = _project(db, project_id, auth.tenant_id)
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(status_code=415, detail="最终设计必须是图片")
    parent = db.query(CanvasNode).filter(CanvasNode.id == parent_node_id, CanvasNode.project_id == project_id).first() if parent_node_id else None
    version = db.query(CanvasNode).filter(CanvasNode.project_id == project_id, CanvasNode.node_type == "deliverable").count() + 1
    url = await get_storage().upload(await file.read(), file.filename or "final-design.png", "creative")
    node = CanvasNode(
        id=uuid.uuid4().hex,
        tenant_id=auth.tenant_id,
        project_id=project_id,
        node_type="deliverable",
        parent_node_id=parent_node_id or None,
        position_x=(parent.position_x + 340 if parent else 600),
        position_y=(parent.position_y if parent else 0),
        data={
            "label": f"最终设计 V{version}",
            "image_url": url,
            "source": "designer_deliverable",
            "filename": file.filename,
            "delivery_version": version,
            "delivery_note": note.strip(),
            "is_final": True,
            "review_status": "pending_review",
        },
    )
    feedback = CreativeFeedback(
        tenant_id=auth.tenant_id,
        project_id=project_id,
        product_id=project.product_id,
        node_id=node.id,
        image_url=url,
        status="final",
        weight=REVIEW_WEIGHTS["final"],
        learning_status="pending",
    )
    project.status = "pending_review"
    db.add(node)
    db.add(feedback)
    db.commit()
    db.refresh(node)
    db.refresh(feedback)
    background_tasks.add_task(analyze_creative_feedback, feedback.id)
    return node


@router.get("/{project_id}/feedback", response_model=list[CreativeFeedbackOut])
def list_feedback(project_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    _project(db, project_id, auth.tenant_id)
    return db.query(CreativeFeedback).filter(CreativeFeedback.project_id == project_id, CreativeFeedback.tenant_id == auth.tenant_id).all()


@router.put("/{project_id}/nodes/{node_id}/feedback", response_model=CreativeFeedbackOut)
def save_feedback(project_id: int, node_id: str, payload: CreativeFeedbackCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    project = _project(db, project_id, auth.tenant_id)
    if payload.status not in REVIEW_WEIGHTS: raise HTTPException(status_code=400, detail="评价状态无效")
    node = db.query(CanvasNode).filter(CanvasNode.id == node_id, CanvasNode.project_id == project_id).first()
    if not node or not node.data.get("image_url"): raise HTTPException(status_code=404, detail="图片节点不存在")
    feedback = db.query(CreativeFeedback).filter(CreativeFeedback.project_id == project_id, CreativeFeedback.node_id == node_id).first()
    if not feedback:
        feedback = CreativeFeedback(tenant_id=auth.tenant_id, project_id=project_id, product_id=project.product_id, node_id=node_id, image_url=node.data["image_url"], status=payload.status)
        db.add(feedback)
    feedback.status = payload.status; feedback.reasons = payload.reasons; feedback.weight = REVIEW_WEIGHTS[payload.status]
    feedback.learning_status = "pending"; feedback.visual_analysis = None
    db.commit(); db.refresh(feedback); background_tasks.add_task(analyze_creative_feedback, feedback.id); return feedback


@router.put("/{project_id}/nodes/{node_id}/final", response_model=CanvasNodeOut)
def mark_final(project_id: int, node_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    project = _project(db, project_id, auth.tenant_id)
    node = db.query(CanvasNode).filter(CanvasNode.id == node_id, CanvasNode.project_id == project_id).first()
    if not node: raise HTTPException(status_code=404, detail="节点不存在")
    data = dict(node.data); data["is_final"] = True; node.data = data
    feedback = db.query(CreativeFeedback).filter(CreativeFeedback.project_id == project_id, CreativeFeedback.node_id == node_id).first()
    if not feedback:
        feedback = CreativeFeedback(tenant_id=auth.tenant_id, project_id=project_id, product_id=project.product_id, node_id=node_id, image_url=data.get("image_url", ""), status="final")
        db.add(feedback)
    feedback.status = "final"; feedback.weight = REVIEW_WEIGHTS["final"]; feedback.learning_status = "pending"; feedback.visual_analysis = None
    db.commit(); db.refresh(node); db.refresh(feedback); background_tasks.add_task(analyze_creative_feedback, feedback.id); return node
