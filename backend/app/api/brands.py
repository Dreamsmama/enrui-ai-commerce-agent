"""Structured brand visual profiles used by templates and image generation."""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.auth import AuthContext, current_auth
from app.database import get_db
from app.models import BrandVisualProfile
from app.schemas import BrandVisualProfileCreate, BrandVisualProfileOut
from app.services.storage import get_storage

router = APIRouter(prefix="/brand-visuals", tags=["brand-visuals"])


@router.get("", response_model=list[BrandVisualProfileOut])
def list_brand_visuals(db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    return db.query(BrandVisualProfile).filter(BrandVisualProfile.tenant_id == auth.tenant_id).order_by(BrandVisualProfile.brand_name).all()


@router.put("/{brand_name}", response_model=BrandVisualProfileOut)
def save_brand_visual(brand_name: str, payload: BrandVisualProfileCreate, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    if payload.brand_name.strip() != brand_name.strip():
        raise HTTPException(status_code=400, detail="品牌名称不一致")
    profile = db.query(BrandVisualProfile).filter(BrandVisualProfile.tenant_id == auth.tenant_id, BrandVisualProfile.brand_name == brand_name).first()
    if not profile:
        profile = BrandVisualProfile(tenant_id=auth.tenant_id, brand_name=brand_name)
        db.add(profile)
    for key, value in payload.model_dump().items():
        setattr(profile, key, value)
    db.commit(); db.refresh(profile)
    return profile


@router.post("/{brand_name}/logo", response_model=BrandVisualProfileOut)
async def upload_brand_logo(brand_name: str, file: UploadFile = File(...), db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)):
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(status_code=415, detail="Logo 必须是图片文件")
    profile = db.query(BrandVisualProfile).filter(BrandVisualProfile.tenant_id == auth.tenant_id, BrandVisualProfile.brand_name == brand_name).first()
    if not profile:
        profile = BrandVisualProfile(tenant_id=auth.tenant_id, brand_name=brand_name)
        db.add(profile)
    profile.logo_url = await get_storage().upload(await file.read(), file.filename or "brand-logo.png", "brands")
    db.commit(); db.refresh(profile)
    return profile
