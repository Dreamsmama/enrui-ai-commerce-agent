from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth import AuthContext, current_auth
from app.models import Generation, KnowledgeDocument, Product
from app.schemas import DashboardStats, GenerationListItem

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/stats", response_model=DashboardStats)
def get_stats(db: Session = Depends(get_db), auth: AuthContext = Depends(current_auth)) -> DashboardStats:
    product_count = db.query(Product).filter(Product.tenant_id == auth.tenant_id).count()
    generation_count = db.query(Generation).filter(Generation.tenant_id == auth.tenant_id).count()
    knowledge_doc_count = db.query(KnowledgeDocument).filter(KnowledgeDocument.tenant_id == auth.tenant_id).count()

    recent = (
        db.query(Generation).filter(Generation.tenant_id == auth.tenant_id).order_by(Generation.created_at.desc()).limit(8).all()
    )
    recent_tasks = [
        GenerationListItem(
            id=g.id,
            product_id=g.product_id,
            product_name=g.product.name if g.product else "",
            status=g.status,
            created_at=g.created_at,
            updated_at=g.updated_at,
        )
        for g in recent
    ]
    return DashboardStats(
        product_count=product_count,
        generation_count=generation_count,
        knowledge_doc_count=knowledge_doc_count,
        recent_tasks=recent_tasks,
    )
