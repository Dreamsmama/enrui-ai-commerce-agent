"""Reusable detail-page storyboard templates."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import AuthContext, current_auth
from app.database import get_db
from app.models import CreativePlan, CreativeProject, DetailPageTemplate, Product, StoryboardModule
from app.schemas import DetailPageTemplateApply, DetailPageTemplateCreate, DetailPageTemplateOut, CreativeProjectOut

router = APIRouter(prefix="/detail-page-templates", tags=["detail-page-templates"])

VARIABLES = [("product_name","商品名称","name"),("brand_name","品牌","brand_name"),("category","品类","category"),("selling_points","核心卖点","description"),("target_users","目标用户","target_users"),("ingredients","成分","ingredients"),("usage_method","使用方法","usage_method"),("specifications","规格/套装组成","specifications")]

def _parameterize(text: str, product: Product) -> str:
    result=text or ""
    for key,_,field in VARIABLES:
        value=str(getattr(product,field) or "").strip()
        if value and value in result: result=result.replace(value,f"{{{{{key}}}}}")
    return result

def _resolve(text: str, product: Product) -> str:
    result=text or ""
    for key,_,field in VARIABLES: result=result.replace(f"{{{{{key}}}}}",str(getattr(product,field) or ""))
    return result


@router.get("", response_model=list[DetailPageTemplateOut])
def list_templates(db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    return db.query(DetailPageTemplate).filter(DetailPageTemplate.tenant_id == auth.tenant_id, DetailPageTemplate.enabled.is_(True)).order_by(DetailPageTemplate.updated_at.desc()).all()


@router.post("", response_model=DetailPageTemplateOut)
def save_template(payload: DetailPageTemplateCreate, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    project = db.query(CreativeProject).filter(CreativeProject.id == payload.project_id, CreativeProject.tenant_id == auth.tenant_id).first()
    if not project:
        raise HTTPException(404, "创作项目不存在")
    product = db.query(Product).filter(Product.id == project.product_id, Product.tenant_id == auth.tenant_id).first()
    modules = db.query(StoryboardModule).filter(StoryboardModule.project_id == project.id, StoryboardModule.tenant_id == auth.tenant_id).order_by(StoryboardModule.sort_order).all()
    if not modules:
        raise HTTPException(400, "当前项目还没有详情页策划模块")
    snapshot=[]
    for module in modules:
        item={key:getattr(module,key) for key in ("sort_order","module_type","title","objective","content_guidance","visual_direction","production_method","required")}
        for field in ("title","objective","content_guidance","visual_direction"): item[field]=_parameterize(item[field],product)
        if module.module_type=="shade": item["condition"]="has_color_variants"
        if module.module_type=="product_showcase": item["condition"]="has_set_composition"
        snapshot.append(item)
    variables=[{"key":key,"label":label,"required":key in {"product_name","brand_name","selling_points","specifications"}} for key,label,_ in VARIABLES]
    row = DetailPageTemplate(tenant_id=auth.tenant_id, name=payload.name, description=payload.description, category=product.category if product else "", brand_name=product.brand_name if product else "", platform=project.platform, output_width=project.output_width, output_height=project.output_height, source_project_id=project.id, modules=snapshot,variables=variables,conditions={"has_color_variants":"品类或商品包含色号/彩妆","has_set_composition":"商品名称或规格包含套装/组合/礼盒"})
    db.add(row); db.commit(); db.refresh(row)
    return row


@router.post("/{template_id}/apply", response_model=CreativeProjectOut)
def apply_template(template_id: int, payload: DetailPageTemplateApply, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    template = db.query(DetailPageTemplate).filter(DetailPageTemplate.id == template_id, DetailPageTemplate.tenant_id == auth.tenant_id, DetailPageTemplate.enabled.is_(True)).first()
    product = db.query(Product).filter(Product.id == payload.product_id, Product.tenant_id == auth.tenant_id).first()
    if not template or not product:
        raise HTTPException(404, "模板或商品不存在")
    project = CreativeProject(tenant_id=auth.tenant_id, product_id=product.id, name=payload.project_name.strip() or f"{product.name} · {template.name}", brief=f"基于模板“{template.name}”创建，替换商品事实、卖点与素材。", platform=template.platform, output_width=template.output_width, output_height=template.output_height)
    db.add(project); db.flush()
    plan = CreativePlan(tenant_id=auth.tenant_id, project_id=project.id, product_understanding={}, strategy={"source_template_id": template.id, "source_template_name": template.name}, status="draft")
    db.add(plan)
    has_color=any(k in f"{product.category}{product.name}" for k in ["气垫","粉底","口红","唇","眼影","彩妆","色号"])
    has_set=any(k in f"{product.name}{product.specifications}" for k in ["套装","组合","礼盒"])
    for spec in template.modules:
        if spec.get("condition")=="has_color_variants" and not has_color: continue
        if spec.get("condition")=="has_set_composition" and not has_set: continue
        values={key:spec.get(key) for key in ("sort_order","module_type","title","objective","content_guidance","visual_direction","production_method","required")}
        for field in ("title","objective","content_guidance","visual_direction"): values[field]=_resolve(values[field],product)
        db.add(StoryboardModule(tenant_id=auth.tenant_id, project_id=project.id, status="planned", **values))
    template.usage_count += 1
    db.commit(); db.refresh(project)
    return project


@router.delete("/{template_id}")
def delete_template(template_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    row = db.query(DetailPageTemplate).filter(DetailPageTemplate.id == template_id, DetailPageTemplate.tenant_id == auth.tenant_id).first()
    if not row:
        raise HTTPException(404, "模板不存在")
    row.enabled = False; db.commit()
    return {"ok": True}
