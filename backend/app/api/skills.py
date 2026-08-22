"""Layered designer Skill management."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import AuthContext, current_auth
from app.database import get_db
from app.models import DesignSkill, Product, SkillCandidate, DesignSkillVersion
from app.schemas import DesignSkillCreate, DesignSkillOut, SkillCandidateOut

router = APIRouter(prefix="/design-skills", tags=["design-skills"])
VALID_SCOPES = {"general", "category", "brand", "product"}

def _snapshot(skill: DesignSkill) -> dict:
    keys = ("name", "scope", "category", "brand_name", "product_id", "description", "design_principles", "module_guidance", "visual_rules", "copy_rules", "negative_rules", "primary_color", "accent_color", "enabled")
    return {key: getattr(skill, key) for key in keys}

def _performance(skill: DesignSkill) -> dict:
    return {"note": "从该版本生效后的项目采用与审核记录持续累计", "captured_at": str(skill.updated_at)}


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


@router.get("/candidates", response_model=list[SkillCandidateOut])
def list_candidates(db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    return db.query(SkillCandidate).filter(SkillCandidate.tenant_id == auth.tenant_id).order_by(SkillCandidate.updated_at.desc()).all()


@router.post("/candidates/{candidate_id}/publish", response_model=DesignSkillOut)
def publish_candidate(candidate_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    candidate = db.query(SkillCandidate).filter(SkillCandidate.id == candidate_id, SkillCandidate.tenant_id == auth.tenant_id).first()
    if not candidate:
        raise HTTPException(404, "候选 Skill 不存在")
    if candidate.published_skill_id:
        existing = db.query(DesignSkill).filter(DesignSkill.id == candidate.published_skill_id).first()
        if existing: return existing
    payload = DesignSkillCreate(**candidate.payload)
    _validate(payload, db, auth)
    skill = DesignSkill(tenant_id=auth.tenant_id, **payload.model_dump())
    db.add(skill); db.flush(); db.add(DesignSkillVersion(tenant_id=auth.tenant_id, skill_id=skill.id, version=1, snapshot=payload.model_dump(), change_note=f"由候选 Skill #{candidate.id} 发布"))
    candidate.status = "published"; candidate.published_skill_id = skill.id
    db.commit(); db.refresh(skill)
    return skill


@router.post("/candidates/{candidate_id}/reject", response_model=SkillCandidateOut)
def reject_candidate(candidate_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    candidate = db.query(SkillCandidate).filter(SkillCandidate.id == candidate_id, SkillCandidate.tenant_id == auth.tenant_id).first()
    if not candidate: raise HTTPException(404, "候选 Skill 不存在")
    candidate.status = "rejected"; db.commit(); db.refresh(candidate)
    return candidate


@router.put("/candidates/{candidate_id}", response_model=SkillCandidateOut)
def edit_candidate(candidate_id: int, payload: DesignSkillCreate, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    _validate(payload, db, auth)
    candidate = db.query(SkillCandidate).filter(SkillCandidate.id == candidate_id, SkillCandidate.tenant_id == auth.tenant_id).first()
    if not candidate or candidate.status != "pending": raise HTTPException(400, "仅待审核候选 Skill 可以编辑")
    candidate.name = payload.name; candidate.payload = payload.model_dump(); db.commit(); db.refresh(candidate)
    return candidate


@router.post("", response_model=DesignSkillOut)
def create_skill(payload: DesignSkillCreate, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    _validate(payload, db, auth)
    skill = DesignSkill(tenant_id=auth.tenant_id, **payload.model_dump())
    db.add(skill); db.flush(); db.add(DesignSkillVersion(tenant_id=auth.tenant_id, skill_id=skill.id, version=1, snapshot=payload.model_dump(), change_note="创建 Skill"))
    db.commit()
    db.refresh(skill)
    return skill


@router.put("/{skill_id}", response_model=DesignSkillOut)
def update_skill(skill_id: int, payload: DesignSkillCreate, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    _validate(payload, db, auth)
    skill = db.query(DesignSkill).filter(DesignSkill.id == skill_id, DesignSkill.tenant_id == auth.tenant_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="设计 Skill 不存在")
    skill.version += 1
    for key, value in payload.model_dump().items():
        setattr(skill, key, value)
    db.add(DesignSkillVersion(tenant_id=auth.tenant_id, skill_id=skill.id, version=skill.version, snapshot=payload.model_dump(), change_note="人工编辑", performance_snapshot=_performance(skill)))
    db.commit()
    db.refresh(skill)
    return skill


@router.get("/{skill_id}/versions")
def skill_versions(skill_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    skill = db.query(DesignSkill).filter(DesignSkill.id == skill_id, DesignSkill.tenant_id == auth.tenant_id).first()
    if not skill: raise HTTPException(404, "设计 Skill 不存在")
    rows = db.query(DesignSkillVersion).filter(DesignSkillVersion.skill_id == skill_id, DesignSkillVersion.tenant_id == auth.tenant_id).order_by(DesignSkillVersion.version.desc()).all()
    if not rows:
        baseline = DesignSkillVersion(tenant_id=auth.tenant_id, skill_id=skill.id, version=skill.version, snapshot=_snapshot(skill), change_note="现有 Skill 基线版本", performance_snapshot=_performance(skill))
        db.add(baseline); db.commit(); db.refresh(baseline); rows = [baseline]
    return [{"id": row.id, "version": row.version, "snapshot": row.snapshot, "change_note": row.change_note, "performance_snapshot": row.performance_snapshot, "created_at": row.created_at, "is_current": row.version == skill.version} for row in rows]


@router.post("/{skill_id}/versions/{version}/rollback", response_model=DesignSkillOut)
def rollback_skill(skill_id: int, version: int, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    skill = db.query(DesignSkill).filter(DesignSkill.id == skill_id, DesignSkill.tenant_id == auth.tenant_id).first()
    source = db.query(DesignSkillVersion).filter(DesignSkillVersion.skill_id == skill_id, DesignSkillVersion.version == version, DesignSkillVersion.tenant_id == auth.tenant_id).first()
    if not skill or not source: raise HTTPException(404, "Skill 版本不存在")
    skill.version += 1
    for key, value in source.snapshot.items(): setattr(skill, key, value)
    db.add(DesignSkillVersion(tenant_id=auth.tenant_id, skill_id=skill.id, version=skill.version, snapshot=source.snapshot, change_note=f"回滚自 v{version}", performance_snapshot=_performance(skill)))
    db.commit(); db.refresh(skill); return skill


@router.delete("/{skill_id}")
def delete_skill(skill_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    skill = db.query(DesignSkill).filter(DesignSkill.id == skill_id, DesignSkill.tenant_id == auth.tenant_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="设计 Skill 不存在")
    db.delete(skill)
    db.commit()
    return {"ok": True, "id": skill_id}
