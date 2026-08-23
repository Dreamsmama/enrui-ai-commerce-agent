from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import AuthContext, create_token, current_auth, hash_password, verify_password
from app.database import get_db
from app.models import KnowledgeDocument, Product, ProductAsset, Tenant, TenantMember, User
from app.schemas import AuthOut, LoginRequest, RegisterRequest

router = APIRouter(prefix="/auth", tags=["auth"])


def _response(user: User, tenant: Tenant, role: str) -> AuthOut:
    return AuthOut(access_token=create_token(user.id, tenant.id), user={"id": user.id, "name": user.name, "email": user.email, "role": role}, tenant={"id": tenant.id, "name": tenant.name, "code": tenant.code})


@router.post("/register", response_model=AuthOut)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> AuthOut:
    email = payload.email.strip().lower()
    if db.query(User).filter(User.email == email).first(): raise HTTPException(status_code=409, detail="邮箱已注册")
    if db.query(Tenant).filter(Tenant.code == payload.tenant_code).first(): raise HTTPException(status_code=409, detail="企业代码已存在")
    tenant = Tenant(id=uuid.uuid4().hex, name=payload.tenant_name.strip(), code=payload.tenant_code)
    user = User(id=uuid.uuid4().hex, email=email, name=payload.name.strip(), password_hash=hash_password(payload.password))
    db.add_all([tenant, user]); db.flush()
    db.add(TenantMember(tenant_id=tenant.id, user_id=user.id, role="owner"))
    if db.query(TenantMember).count() == 1:
        for model in (Product, KnowledgeDocument, ProductAsset):
            db.query(model).filter(model.tenant_id == "default").update({"tenant_id": tenant.id})
    db.commit()
    return _response(user, tenant, "owner")


@router.post("/login", response_model=AuthOut)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> AuthOut:
    user = db.query(User).filter(User.email == payload.email.strip().lower(), User.status == "active").first()
    if not user or not verify_password(payload.password, user.password_hash): raise HTTPException(status_code=401, detail="邮箱或密码错误")
    member = db.query(TenantMember).filter_by(user_id=user.id, status="active").first()
    tenant = db.query(Tenant).filter_by(id=member.tenant_id, status="active").first() if member else None
    if not member or not tenant: raise HTTPException(status_code=403, detail="未加入可用企业")
    return _response(user, tenant, member.role)


@router.get("/me")
def me(auth: AuthContext = Depends(current_auth)) -> dict:
    return {"user_id": auth.user_id, "email": auth.email, "role": auth.role, "tenant_id": auth.tenant_id, "tenant_name": auth.tenant_name}
