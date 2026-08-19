"""Creative projects and lightweight infinite-canvas APIs."""

from __future__ import annotations

import mimetypes
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.auth import AuthContext, current_auth
from app.database import get_db
from app.models import CanvasNode, CreativeFeedback, CreativeGeneration, CreativeProject, DesignSkill, KnowledgeDocument, LearnedDesignProfile, Product, ProductAsset
from app.schemas import (
    CanvasNodeCreate,
    CanvasNodeOut,
    CanvasSaveRequest,
    CreativeGenerateRequest,
    CreativeFeedbackCreate,
    CreativeFeedbackOut,
    CreativeGenerationOut,
    CreativeProjectCreate,
    CreativeProjectOut,
)
from app.services.design_learning import REVIEW_WEIGHTS, analyze_creative_feedback
from app.services.image_generation import get_image_provider
from app.services.storage import get_storage

router = APIRouter(prefix="/creative-projects", tags=["creative-projects"])


def _project(db: Session, project_id: int, tenant_id: str) -> CreativeProject:
    row = db.query(CreativeProject).filter(CreativeProject.id == project_id, CreativeProject.tenant_id == tenant_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="创作项目不存在")
    return row


@router.get("", response_model=list[CreativeProjectOut])
def list_projects(db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    return db.query(CreativeProject).filter(CreativeProject.tenant_id == auth.tenant_id).order_by(CreativeProject.updated_at.desc()).all()


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
            data={"label": asset.name, "image_url": asset.file_url, "source": "asset_library", "asset_type": asset.asset_type, "description": asset.description},
        ))
    db.commit()
    return project


@router.get("/{project_id}", response_model=CreativeProjectOut)
def get_project(project_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    return _project(db, project_id, auth.tenant_id)


@router.get("/{project_id}/nodes", response_model=list[CanvasNodeOut])
def list_nodes(project_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    _project(db, project_id, auth.tenant_id)
    return db.query(CanvasNode).filter(CanvasNode.project_id == project_id, CanvasNode.tenant_id == auth.tenant_id).all()


@router.put("/{project_id}/canvas", response_model=list[CanvasNodeOut])
def save_canvas(project_id: int, payload: CanvasSaveRequest, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    project = _project(db, project_id, auth.tenant_id)
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
    product = db.query(Product).filter(Product.id == project.product_id).first()
    project_nodes = db.query(CanvasNode).filter(CanvasNode.project_id == project_id, CanvasNode.tenant_id == auth.tenant_id).all()
    explicit_selected = [node for node in project_nodes if node.id in payload.selected_node_ids]
    parent = db.query(CanvasNode).filter(CanvasNode.id == payload.parent_node_id, CanvasNode.project_id == project_id).first() if payload.parent_node_id else None
    selected = explicit_selected
    selection_strategy = "manual"
    if payload.auto_select_materials:
        product_nodes = [node for node in project_nodes if node.node_type in {"product", "product_image"} and node.data.get("image_url")]
        reference_nodes = [node for node in explicit_selected if node.node_type in {"reference", "brand_asset", "detail_image"} and node.data.get("image_url")]
        approved_nodes = [node for node in project_nodes if node.node_type in {"generated", "refined", "deliverable"} and (node.data.get("is_final") or node.data.get("review_status") in {"usable", "final"}) and node.data.get("image_url")]
        if "详情页" in payload.action:
            selected = product_nodes + approved_nodes[-1:] + reference_nodes
            selection_strategy = "全部商品原图 + 已定稿主图 + 手动参考图"
        else:
            selected = product_nodes + reference_nodes
            selection_strategy = "全部商品原图 + 手动参考图"
        selected = list({node.id: node for node in selected}.values())
    source_node = parent or next((node for node in reversed(selected) if node.node_type in {"deliverable", "refined", "generated"} and node.data.get("image_url")), None) or next((node for node in selected if node.data.get("image_url")), None)
    source_url = source_node.data.get("image_url", "") if source_node else ((product.image_urls or [""])[0])
    provider = get_image_provider()
    brand_docs = db.query(KnowledgeDocument).filter(KnowledgeDocument.tenant_id == auth.tenant_id, KnowledgeDocument.brand_name == product.brand_name).all()
    all_skills = db.query(DesignSkill).filter(DesignSkill.tenant_id == auth.tenant_id, DesignSkill.enabled.is_(True)).all()
    matched_skills = [skill for skill in all_skills if skill.scope == "general" or (skill.scope == "category" and skill.category == product.category) or (skill.scope == "brand" and skill.brand_name == product.brand_name) or (skill.scope == "product" and skill.product_id == product.id)]
    learned = db.query(LearnedDesignProfile).filter(LearnedDesignProfile.tenant_id == auth.tenant_id, LearnedDesignProfile.brand_name == product.brand_name, LearnedDesignProfile.category == product.category).first() if product.learned_profile_enabled else None
    context_snapshot = {
        "product": {"id": product.id, "name": product.name, "brand": product.brand_name, "category": product.category, "ingredients": product.ingredients, "specifications": product.specifications},
        "material_selection": {"mode": "auto" if payload.auto_select_materials else "manual", "strategy": selection_strategy, "count": len(selected)},
        "selected_nodes": [{"id": node.id, "type": node.node_type, "label": node.data.get("label"), "image_url": node.data.get("image_url")} for node in selected],
        "brand_documents": [{"id": doc.id, "title": doc.title} for doc in brand_docs],
        "design_skills": [{"id": skill.id, "name": skill.name, "scope": skill.scope, "visual_rules": skill.visual_rules} for skill in matched_skills],
        "learned_profile": {"status": learned.status, "confidence": learned.confidence, "rules": learned.learned_rules} if learned else None,
        "project_brief": project.brief,
    }
    effective_prompt = f"{project.brief}\n{payload.prompt}\n品牌：{product.brand_name}；商品：{product.name}；已匹配 Skill：{'、'.join(skill.name for skill in matched_skills) or '无'}"
    main_image_roles = ["主封面", "核心卖点", "套装内容", "成分质地", "使用场景"] if payload.action == "生成主图套系" else []
    output_count = len(main_image_roles) or payload.count
    job = CreativeGeneration(
        tenant_id=auth.tenant_id, project_id=project_id, parent_node_id=payload.parent_node_id,
        prompt=payload.prompt, action=payload.action, selected_node_ids=[node.id for node in selected],
        provider=provider.name, status="running", context_snapshot=context_snapshot,
    )
    db.add(job); db.commit(); db.refresh(job)
    try:
        urls = provider.generate(source_url=source_url, source_urls=[node.data.get("image_url") for node in selected if node.data.get("image_url")], variant_labels=main_image_roles or None, prompt=effective_prompt, action=payload.action, count=output_count, width=project.output_width, height=project.output_height, project_id=project.id)
        max_x = max([node.position_x for node in db.query(CanvasNode).filter(CanvasNode.project_id == project_id).all()] or [0])
        base_y = parent.position_y if parent else 0
        result_ids = []
        for index, url in enumerate(urls):
            node_id = uuid.uuid4().hex
            result_ids.append(node_id)
            db.add(CanvasNode(
                id=node_id, tenant_id=auth.tenant_id, project_id=project_id, node_type="generated",
                parent_node_id=payload.parent_node_id, position_x=max_x + 340, position_y=base_y + index * 360,
                data={"label": f"主图套系 · {main_image_roles[index]}" if main_image_roles else f"AI 方案 {chr(65 + index)}", "image_url": url, "prompt": payload.prompt, "action": payload.action, "module_role": main_image_roles[index] if main_image_roles else None, "suite_type": "main_image" if main_image_roles else None, "generation_id": job.id, "provider": provider.name, "context_summary": {"material_strategy": selection_strategy, "materials": [{"id": item.id, "type": item.node_type, "label": item.data.get("label")} for item in selected], "brand_documents": [{"id": doc.id, "title": doc.title} for doc in brand_docs], "skills": [{"id": skill.id, "name": skill.name, "scope": skill.scope} for skill in matched_skills], "learned_profile": bool(learned)}},
            ))
        job.result_node_ids = result_ids; job.status = "completed"; db.commit(); db.refresh(job)
    except Exception as exc:
        job.status = "failed"; job.error_message = str(exc); db.commit()
        raise HTTPException(status_code=500, detail=str(exc))
    nodes = db.query(CanvasNode).filter(CanvasNode.id.in_(job.result_node_ids)).all()
    return {"generation": CreativeGenerationOut.model_validate(job), "nodes": [CanvasNodeOut.model_validate(node) for node in nodes]}


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
