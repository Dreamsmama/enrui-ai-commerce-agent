"""Knowledge base / RAG document management."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.config import get_settings
from app.auth import AuthContext, current_auth
from app.database import get_db
from app.models import KnowledgeDocument, Product
from app.rag import index_document
from app.schemas import KnowledgeDocCreate, KnowledgeDocOut
from app.services.document_parser import parse_document
from app.services.storage import get_storage

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def _to_out(doc: KnowledgeDocument) -> KnowledgeDocOut:
    return KnowledgeDocOut.model_validate(doc)


@router.get("", response_model=list[KnowledgeDocOut])
def list_docs(
    product_id: Optional[int] = None,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(current_auth),
) -> list[KnowledgeDocOut]:
    q = db.query(KnowledgeDocument).filter(KnowledgeDocument.tenant_id == auth.tenant_id).order_by(KnowledgeDocument.created_at.desc())
    if product_id is not None:
        q = q.filter(KnowledgeDocument.product_id == product_id)
    return [_to_out(d) for d in q.all()]


@router.get("/{doc_id}", response_model=KnowledgeDocOut)
def get_doc(doc_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)) -> KnowledgeDocOut:
    doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == doc_id, KnowledgeDocument.tenant_id == auth.tenant_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    return _to_out(doc)


@router.post("", response_model=KnowledgeDocOut)
async def create_doc(
    payload: KnowledgeDocCreate, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)
) -> KnowledgeDocOut:
    if payload.product_id is not None:
        product = db.query(Product).filter(Product.id == payload.product_id, Product.tenant_id == auth.tenant_id).first()
        if not product:
            raise HTTPException(status_code=404, detail="商品不存在")

    doc = KnowledgeDocument(
        tenant_id=auth.tenant_id, product_id=payload.product_id,
        brand_name=payload.brand_name.strip(),
        title=payload.title,
        doc_type=payload.doc_type,
        content=payload.content,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    await index_document(db, doc)
    db.refresh(doc)
    return _to_out(doc)


@router.post("/upload", response_model=KnowledgeDocOut)
async def upload_doc(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    doc_type: str = Form("general"),
    product_id: Optional[int] = Form(None),
    brand_name: str = Form(""),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(current_auth),
) -> KnowledgeDocOut:
    if product_id is not None:
        product = db.query(Product).filter(Product.id == product_id, Product.tenant_id == auth.tenant_id).first()
        if not product:
            raise HTTPException(status_code=404, detail="商品不存在")

    raw = await file.read()
    settings = get_settings()
    if len(raw) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"文件不能超过 {settings.max_upload_mb}MB")
    content = parse_document(raw, file.filename or "doc.txt")

    stored_url = await get_storage().upload(raw, file.filename or "doc.txt", "documents")
    stored_name = Path(stored_url).name

    doc = KnowledgeDocument(
        tenant_id=auth.tenant_id, product_id=product_id,
        brand_name=brand_name.strip(),
        title=title or (file.filename or "未命名文档"),
        doc_type=doc_type,
        filename=stored_name,
        content=content,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    await index_document(db, doc)
    db.refresh(doc)
    return _to_out(doc)


@router.delete("/{doc_id}")
def delete_doc(doc_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)) -> dict:
    doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == doc_id, KnowledgeDocument.tenant_id == auth.tenant_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    db.delete(doc)
    db.commit()
    return {"ok": True, "id": doc_id}
