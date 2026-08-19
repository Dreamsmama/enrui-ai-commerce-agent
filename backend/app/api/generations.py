"""Generation workflow + section editing APIs."""

from __future__ import annotations

import logging
import json
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.agents import (
    CommerceAgentWorkflow,
    DetailEditorService,
    DetailPageAgent,
    validate_detail_sections,
)
from app.config import get_settings
from app.auth import AuthContext, current_auth
from app.database import SessionLocal, get_db
from app.models import EditHistory, Generation, ImageReview, LearnedDesignProfile, Product
from app.rag import retrieve_context
from app.schemas import (
    EditHistoryOut,
    EditRequest,
    GenerationListItem,
    GenerationModulesUpdate,
    GenerationOut,
    ImageReviewCreate,
    ImageReviewOut,
    LearnedDesignProfileOut,
)
from app.services.design_learning import REVIEW_WEIGHTS, analyze_review
from app.services.visual_renderer import render_visual_modules

router = APIRouter(tags=["generations"])
logger = logging.getLogger(__name__)


def _text_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _gen_out(g: Generation) -> GenerationOut:
    return GenerationOut.model_validate(g)


async def _run_workflow(generation_id: int) -> None:
    db = SessionLocal()
    try:
        generation = db.query(Generation).filter(Generation.id == generation_id).first()
        if not generation:
            return
        product = db.query(Product).filter(Product.id == generation.product_id).first()
        if not product:
            generation.status = "failed"
            generation.error_message = "商品不存在"
            db.commit()
            return

        generation.status = "running"
        generation.attempt_count += 1
        db.commit()

        workflow = CommerceAgentWorkflow()
        live_results: dict = {
            "execution_trace": {"status": "running", "current_stage": None, "steps": []}
        }

        async def on_progress(stage: str, data: object = None) -> None:
            is_done = stage.endswith("_done")
            key = stage.removesuffix("_done")
            trace = live_results["execution_trace"]
            if is_done:
                payload = data if isinstance(data, dict) else {}
                result_data = payload.get("result")
                if result_data is not None:
                    live_results[key] = result_data
                trace["steps"].append({
                    "key": key,
                    "status": "completed",
                    "duration_ms": payload.get("duration_ms", 0),
                })
                trace["current_stage"] = None
            else:
                trace["current_stage"] = key
            generation.agent_results = dict(live_results)
            db.commit()

        result = await workflow.run(db, product, on_progress=on_progress)
        visual_result = render_visual_modules(
            product,
            result["detail_page_sections"],
            generation.id,
            result["agent_results"].get("design_theme"),
        )
        result["agent_results"].update(visual_result)

        generation.agent_results = result["agent_results"]
        generation.detail_page_sections = result["detail_page_sections"]
        generation.detail_page_markdown = _text_value(result["detail_page_markdown"])
        generation.marketing_copy = _text_value(result["marketing_copy"])
        generation.main_image_copy = _text_value(result["main_image_copy"])
        generation.status = "completed"
        generation.error_message = None
        db.commit()
    except Exception as exc:
        logger.exception("Generation %s failed", generation_id)
        db.rollback()
        generation = db.query(Generation).filter(Generation.id == generation_id).first()
        if generation:
            generation.status = "failed"
            generation.error_message = str(exc)
            db.commit()
    finally:
        db.close()


@router.post("/products/{product_id}/generate", response_model=GenerationOut)
async def start_generation(
    product_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> GenerationOut:
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="商品不存在")

    generation = Generation(
        product_id=product_id,
        status="pending",
        max_attempts=get_settings().generation_max_attempts,
    )
    db.add(generation)
    db.commit()
    db.refresh(generation)

    background_tasks.add_task(_run_workflow, generation.id)
    return _gen_out(generation)


@router.get("/generations", response_model=list[GenerationListItem])
def list_generations(
    product_id: Optional[int] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
) -> list[GenerationListItem]:
    q = db.query(Generation).order_by(Generation.created_at.desc())
    if product_id is not None:
        q = q.filter(Generation.product_id == product_id)
    rows = q.limit(limit).all()
    result = []
    for g in rows:
        name = g.product.name if g.product else ""
        result.append(
            GenerationListItem(
                id=g.id,
                product_id=g.product_id,
                product_name=name,
                status=g.status,
                created_at=g.created_at,
                updated_at=g.updated_at,
            )
        )
    return result


@router.get("/generations/{generation_id}", response_model=GenerationOut)
def get_generation(generation_id: int, db: Session = Depends(get_db)) -> GenerationOut:
    generation = db.query(Generation).filter(Generation.id == generation_id).first()
    if not generation:
        raise HTTPException(status_code=404, detail="生成记录不存在")
    return _gen_out(generation)


@router.get("/generations/{generation_id}/image-reviews", response_model=list[ImageReviewOut])
def list_image_reviews(
    generation_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(current_auth),
) -> list[ImageReviewOut]:
    generation = db.query(Generation).join(Product).filter(
        Generation.id == generation_id, Product.tenant_id == auth.tenant_id
    ).first()
    if not generation:
        raise HTTPException(status_code=404, detail="生成记录不存在")
    return db.query(ImageReview).filter(
        ImageReview.generation_id == generation_id,
        ImageReview.tenant_id == auth.tenant_id,
    ).all()


@router.put(
    "/generations/{generation_id}/visual-modules/{module_key}/review",
    response_model=ImageReviewOut,
)
def review_visual_module(
    generation_id: int,
    module_key: str,
    payload: ImageReviewCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(current_auth),
) -> ImageReviewOut:
    if payload.status not in REVIEW_WEIGHTS:
        raise HTTPException(status_code=400, detail="图片评价状态无效")
    generation = db.query(Generation).join(Product).filter(
        Generation.id == generation_id, Product.tenant_id == auth.tenant_id
    ).first()
    if not generation or generation.status != "completed":
        raise HTTPException(status_code=404, detail="已完成的生成记录不存在")
    modules = (generation.agent_results or {}).get("visual_modules") or []
    module = next((item for item in modules if item.get("key") == module_key), None)
    if not module:
        raise HTTPException(status_code=404, detail="视觉模块不存在")
    review = db.query(ImageReview).filter(
        ImageReview.generation_id == generation_id,
        ImageReview.module_key == module_key,
    ).first()
    if not review:
        review = ImageReview(
            tenant_id=auth.tenant_id,
            product_id=generation.product_id,
            generation_id=generation_id,
            module_key=module_key,
            module_title=module.get("title", module_key),
            image_url=module.get("image_url", ""),
            status=payload.status,
        )
        db.add(review)
    review.status = payload.status
    review.reasons = payload.reasons
    review.note = payload.note.strip()
    review.weight = REVIEW_WEIGHTS[payload.status]
    review.learning_status = "pending"
    review.visual_analysis = None
    db.commit()
    db.refresh(review)
    background_tasks.add_task(analyze_review, review.id)
    return review


@router.get("/products/{product_id}/learned-design-profile", response_model=Optional[LearnedDesignProfileOut])
def get_learned_design_profile(
    product_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(current_auth),
) -> Optional[LearnedDesignProfileOut]:
    product = db.query(Product).filter(
        Product.id == product_id, Product.tenant_id == auth.tenant_id
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="商品不存在")
    return db.query(LearnedDesignProfile).filter(
        LearnedDesignProfile.tenant_id == auth.tenant_id,
        LearnedDesignProfile.brand_name == product.brand_name,
        LearnedDesignProfile.category == product.category,
    ).first()


@router.get("/generations/{generation_id}/export/markdown")
def export_generation_markdown(
    generation_id: int, db: Session = Depends(get_db)
) -> Response:
    generation = db.query(Generation).filter(Generation.id == generation_id).first()
    if not generation:
        raise HTTPException(status_code=404, detail="生成记录不存在")
    if generation.status != "completed":
        raise HTTPException(status_code=400, detail="仅已完成的详情页可以导出")
    filename = f"detail-page-{generation.id}.md"
    return Response(
        content=generation.detail_page_markdown or "",
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/generations/{generation_id}")
def delete_generation(generation_id: int, db: Session = Depends(get_db)) -> dict:
    generation = db.query(Generation).filter(Generation.id == generation_id).first()
    if not generation:
        raise HTTPException(status_code=404, detail="生成记录不存在")
    db.delete(generation)
    db.commit()
    return {"ok": True, "id": generation_id}


@router.post("/generations/{generation_id}/retry", response_model=GenerationOut)
async def retry_generation(
    generation_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> GenerationOut:
    generation = db.query(Generation).filter(Generation.id == generation_id).first()
    if not generation:
        raise HTTPException(status_code=404, detail="生成记录不存在")
    if generation.status != "failed":
        raise HTTPException(status_code=400, detail="仅失败任务可以重试")
    if generation.attempt_count >= generation.max_attempts:
        raise HTTPException(status_code=400, detail="已达到最大重试次数")
    generation.status = "pending"
    generation.error_message = None
    db.commit()
    db.refresh(generation)
    background_tasks.add_task(_run_workflow, generation.id)
    return _gen_out(generation)


@router.post("/generations/{generation_id}/edit", response_model=GenerationOut)
async def edit_generation(
    generation_id: int,
    payload: EditRequest,
    db: Session = Depends(get_db),
) -> GenerationOut:
    generation = db.query(Generation).filter(Generation.id == generation_id).first()
    if not generation:
        raise HTTPException(status_code=404, detail="生成记录不存在")
    if generation.status != "completed":
        raise HTTPException(status_code=400, detail="仅已完成的生成记录可编辑")

    product = generation.product
    sections = dict(generation.detail_page_sections or {})
    module_order = sections.pop("_module_order", list(DetailPageAgent.SECTION_KEYS))
    before_md = generation.detail_page_markdown or ""

    query = f"{product.name} {product.description}"
    rag_context = await retrieve_context(db, query, product_id=product.id, top_k=4)

    editor = DetailEditorService()
    try:
        new_sections = await editor.edit(
            product,
            sections,
            action=payload.action,
            section=payload.section,
            instruction=payload.instruction,
            target_audience=payload.target_audience,
            agent_results=generation.agent_results,
            rag_context=rag_context,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    merged = dict(sections)
    for key in DetailPageAgent.SECTION_KEYS:
        if key in new_sections:
            merged[key] = new_sections[key]

    after_md = DetailPageAgent.sections_to_markdown(merged, module_order)
    generation.detail_page_sections = {**merged, "_module_order": module_order}
    generation.detail_page_markdown = after_md
    agent_results = dict(generation.agent_results or {})
    agent_results["quality_check"] = validate_detail_sections(product, merged)
    generation.agent_results = agent_results

    if "marketing_copy" in new_sections:
        generation.marketing_copy = new_sections["marketing_copy"]
    if "main_image_copy" in new_sections:
        generation.main_image_copy = new_sections["main_image_copy"]

    edit = EditHistory(
        generation_id=generation.id,
        action=payload.action,
        section=payload.section,
        instruction=payload.instruction or payload.target_audience or None,
        before_content=before_md,
        after_content=after_md,
    )
    db.add(edit)
    db.commit()
    db.refresh(generation)
    return _gen_out(generation)


@router.put("/generations/{generation_id}/modules", response_model=GenerationOut)
def update_generation_modules(
    generation_id: int,
    payload: GenerationModulesUpdate,
    db: Session = Depends(get_db),
) -> GenerationOut:
    generation = db.query(Generation).filter(Generation.id == generation_id).first()
    if not generation:
        raise HTTPException(status_code=404, detail="生成记录不存在")
    if generation.status != "completed":
        raise HTTPException(status_code=400, detail="仅已完成的生成记录可编辑")

    allowed = set(DetailPageAgent.SECTION_KEYS)
    module_order = [key for key in payload.module_order if key in allowed]
    sections = {
        key: value for key, value in payload.sections.items() if key in allowed and value.strip()
    }
    for key in sections:
        if key not in module_order:
            module_order.append(key)

    before = generation.detail_page_markdown or ""
    after = DetailPageAgent.sections_to_markdown(sections, module_order)
    generation.detail_page_sections = {**sections, "_module_order": module_order}
    generation.detail_page_markdown = after
    agent_results = dict(generation.agent_results or {})
    agent_results["quality_check"] = validate_detail_sections(generation.product, sections)
    generation.agent_results = agent_results
    db.add(
        EditHistory(
            generation_id=generation.id,
            action="update_modules",
            instruction="调整详情页模块内容或顺序",
            before_content=before,
            after_content=after,
        )
    )
    db.commit()
    db.refresh(generation)
    return _gen_out(generation)


@router.get(
    "/generations/{generation_id}/edits",
    response_model=list[EditHistoryOut],
)
def list_edits(generation_id: int, db: Session = Depends(get_db)) -> list[EditHistoryOut]:
    generation = db.query(Generation).filter(Generation.id == generation_id).first()
    if not generation:
        raise HTTPException(status_code=404, detail="生成记录不存在")
    edits = (
        db.query(EditHistory)
        .filter(EditHistory.generation_id == generation_id)
        .order_by(EditHistory.created_at.desc())
        .all()
    )
    return [EditHistoryOut.model_validate(e) for e in edits]
