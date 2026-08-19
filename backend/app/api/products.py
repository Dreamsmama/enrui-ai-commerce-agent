"""Product CRUD + image upload."""

from __future__ import annotations

import mimetypes
from pathlib import Path
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.config import get_settings
from app.auth import AuthContext, current_auth
from app.database import get_db
from app.models import Product, ProductAsset
from app.schemas import ProductAssetOut, ProductCreate, ProductOut, ProductUpdate
from app.services.storage import get_storage

router = APIRouter(prefix="/products", tags=["products"])


def _to_out(product: Product) -> ProductOut:
    return ProductOut(
        id=product.id,
        name=product.name,
        category=product.category,
        price=product.price,
        description=product.description,
        target_users=product.target_users,
        brand_name=product.brand_name,
        ingredients=product.ingredients,
        usage_method=product.usage_method,
        specifications=product.specifications,
        image_urls=product.image_urls or [],
        detail_image_urls=product.detail_image_urls or [],
        learned_profile_enabled=product.learned_profile_enabled,
        created_at=product.created_at,
        updated_at=product.updated_at,
        generation_count=len(product.generations) if product.generations else 0,
    )


@router.get("", response_model=list[ProductOut])
def list_products(db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)) -> list[ProductOut]:
    products = db.query(Product).filter(Product.tenant_id == auth.tenant_id).order_by(Product.created_at.desc()).all()
    return [_to_out(p) for p in products]


@router.get("/{product_id}", response_model=ProductOut)
def get_product(product_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)) -> ProductOut:
    product = db.query(Product).filter(Product.id == product_id, Product.tenant_id == auth.tenant_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="商品不存在")
    return _to_out(product)


@router.post("", response_model=ProductOut)
def create_product(payload: ProductCreate, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)) -> ProductOut:
    product = Product(
        tenant_id=auth.tenant_id, name=payload.name,
        category=payload.category,
        price=payload.price,
        description=payload.description,
        target_users=payload.target_users,
        brand_name=payload.brand_name,
        ingredients=payload.ingredients,
        usage_method=payload.usage_method,
        specifications=payload.specifications,
        image_urls=payload.image_urls,
        detail_image_urls=payload.detail_image_urls,
        learned_profile_enabled=payload.learned_profile_enabled,
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return _to_out(product)


@router.get("/{product_id}/assets", response_model=list[ProductAssetOut])
def list_product_assets(product_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)) -> list[ProductAssetOut]:
    if not db.query(Product).filter(Product.id == product_id, Product.tenant_id == auth.tenant_id).first():
        raise HTTPException(status_code=404, detail="商品不存在")
    assets = (
        db.query(ProductAsset)
        .filter(ProductAsset.tenant_id == auth.tenant_id, (ProductAsset.product_id == product_id) | (ProductAsset.product_id.is_(None)))
        .order_by(ProductAsset.created_at.desc())
        .all()
    )
    return [ProductAssetOut.model_validate(asset) for asset in assets]


@router.post("/{product_id}/assets", response_model=list[ProductAssetOut])
async def upload_product_assets(
    product_id: int,
    asset_type: str = Form("product_image"),
    description: str = Form(""),
    tags: str = Form(""),
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(current_auth),
) -> list[ProductAssetOut]:
    product = db.query(Product).filter(Product.id == product_id, Product.tenant_id == auth.tenant_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="商品不存在")

    settings = get_settings()
    created: list[ProductAsset] = []
    for upload in files:
        raw = await upload.read()
        if len(raw) > settings.max_upload_mb * 1024 * 1024:
            raise HTTPException(status_code=413, detail=f"文件不能超过 {settings.max_upload_mb}MB")
        subdir = "images" if (upload.content_type or "").startswith("image/") else "documents"
        file_url = await get_storage().upload(raw, upload.filename or "asset.bin", subdir)
        stored_name = Path(file_url).name
        asset = ProductAsset(
            tenant_id=auth.tenant_id, product_id=product_id,
            name=upload.filename or stored_name,
            asset_type=asset_type,
            file_url=file_url,
            mime_type=upload.content_type or mimetypes.guess_type(stored_name)[0] or "",
            description=description,
            tags=[item.strip() for item in tags.split(",") if item.strip()],
        )
        db.add(asset)
        created.append(asset)
    db.commit()
    for asset in created:
        db.refresh(asset)
    return [ProductAssetOut.model_validate(asset) for asset in created]


@router.delete("/{product_id}/assets/{asset_id}")
async def delete_product_asset(
    product_id: int, asset_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)
) -> dict:
    asset = db.query(ProductAsset).filter(
        ProductAsset.id == asset_id, ProductAsset.product_id == product_id, ProductAsset.tenant_id == auth.tenant_id
    ).first()
    if not asset:
        raise HTTPException(status_code=404, detail="素材不存在")
    file_url = asset.file_url
    db.delete(asset)
    db.commit()
    await get_storage().delete(file_url)
    return {"ok": True, "id": asset_id}


@router.put("/{product_id}", response_model=ProductOut)
def update_product(
    product_id: int, payload: ProductUpdate, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)
) -> ProductOut:
    product = db.query(Product).filter(Product.id == product_id, Product.tenant_id == auth.tenant_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="商品不存在")
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(product, key, value)
    db.commit()
    db.refresh(product)
    return _to_out(product)


@router.delete("/{product_id}")
def delete_product(product_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)) -> dict:
    product = db.query(Product).filter(Product.id == product_id, Product.tenant_id == auth.tenant_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="商品不存在")
    db.delete(product)
    db.commit()
    return {"ok": True, "id": product_id}


@router.post("/{product_id}/images")
async def upload_product_images(
    product_id: int,
    image_type: str = Form("product"),  # product | detail
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(current_auth),
) -> ProductOut:
    product = db.query(Product).filter(Product.id == product_id, Product.tenant_id == auth.tenant_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="商品不存在")

    settings = get_settings()
    saved_urls: list[str] = []
    for f in files:
        if not (f.content_type or "").startswith("image/"):
            raise HTTPException(status_code=415, detail="仅支持图片文件")
        content = await f.read()
        if len(content) > settings.max_upload_mb * 1024 * 1024:
            raise HTTPException(status_code=413, detail=f"图片不能超过 {settings.max_upload_mb}MB")
        saved_urls.append(await get_storage().upload(content, f.filename or "img.jpg", "images"))

    if image_type == "detail":
        product.detail_image_urls = (product.detail_image_urls or []) + saved_urls
    else:
        product.image_urls = (product.image_urls or []) + saved_urls

    db.commit()
    db.refresh(product)
    return _to_out(product)


@router.post("/upload-image")
async def upload_standalone_image(
    file: UploadFile = File(...),
    auth: AuthContext = Depends(current_auth),
) -> dict:
    """Upload an image before product creation; returns URL."""
    settings = get_settings()
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(status_code=415, detail="仅支持图片文件")
    content = await file.read()
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"图片不能超过 {settings.max_upload_mb}MB")
    return {"url": await get_storage().upload(content, file.filename or "img.jpg", "images")}
