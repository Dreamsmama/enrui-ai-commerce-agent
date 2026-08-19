"""Layered designer Skill management."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import AuthContext, current_auth
from app.database import get_db
from app.models import DesignSkill, Product
from app.schemas import DesignSkillCreate, DesignSkillOut

router = APIRouter(prefix="/design-skills", tags=["design-skills"])
VALID_SCOPES = {"general", "category", "brand", "product"}


def _validate(payload: DesignSkillCreate, db: Session, auth: AuthContext) -> None:
    if payload.scope not in VALID_SCOPES:
        raise HTTPException(status_code=400, detail="Skill 作用范围无效")
    if payload.scope == "category" and not payload.category.strip():
        raise HTTPException(status_code=400, detail="品类 Skill 必须填写品类")
    if payload.scope == "brand" and not payload.brand_name.strip():
        raise HTTPException(status_code=400, detail="品牌 Skill 必须填写品牌名称")
    if payload.scope == "product":
        product = db.query(Product).filter(
            Product.id == payload.product_id, Product.tenant_id == auth.tenant_id
        ).first()
        if not product:
            raise HTTPException(status_code=400, detail="商品 Skill 必须关联有效商品")


@router.get("", response_model=list[DesignSkillOut])
def list_skills(db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    return db.query(DesignSkill).filter(DesignSkill.tenant_id == auth.tenant_id).order_by(DesignSkill.created_at.desc()).all()


@router.post("", response_model=DesignSkillOut)
def create_skill(payload: DesignSkillCreate, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    _validate(payload, db, auth)
    skill = DesignSkill(tenant_id=auth.tenant_id, **payload.model_dump())
    db.add(skill)
    db.commit()
    db.refresh(skill)
    return skill


@router.put("/{skill_id}", response_model=DesignSkillOut)
def update_skill(skill_id: int, payload: DesignSkillCreate, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    _validate(payload, db, auth)
    skill = db.query(DesignSkill).filter(DesignSkill.id == skill_id, DesignSkill.tenant_id == auth.tenant_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="设计 Skill 不存在")
    for key, value in payload.model_dump().items():
        setattr(skill, key, value)
    db.commit()
    db.refresh(skill)
    return skill


@router.delete("/{skill_id}")
def delete_skill(skill_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    skill = db.query(DesignSkill).filter(DesignSkill.id == skill_id, DesignSkill.tenant_id == auth.tenant_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="设计 Skill 不存在")
    db.delete(skill)
    db.commit()
    return {"ok": True, "id": skill_id}
