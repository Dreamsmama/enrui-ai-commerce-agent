from __future__ import annotations

import time
import uuid

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import auth, creative, dashboard, generations, knowledge, products, skills
from app.config import get_settings
from app.database import SessionLocal, init_db
from app.models import AuditLog, Generation

settings = get_settings()

app = FastAPI(
    title="Enrui AI Commerce Agent",
    description="企业级 AI 商品详情页生成助手 — 多模态 Agent Workflow + RAG",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def audit_requests(request, call_next):
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    started = time.perf_counter()
    response = await call_next(request)
    duration_ms = int((time.perf_counter() - started) * 1000)
    response.headers["x-request-id"] = request_id
    if request.url.path.startswith("/api"):
        db = SessionLocal()
        try:
            db.add(AuditLog(request_id=request_id, method=request.method, path=request.url.path, status_code=response.status_code, duration_ms=duration_ms))
            db.commit()
        finally:
            db.close()
    return response

app.include_router(products.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(generations.router, prefix="/api")
app.include_router(knowledge.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(skills.router, prefix="/api")
app.include_router(creative.router, prefix="/api")

upload_path = settings.upload_path
app.mount("/uploads", StaticFiles(directory=str(upload_path)), name="uploads")


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    settings.upload_path  # ensure dirs
    db = SessionLocal()
    try:
        interrupted = db.query(Generation).filter(Generation.status == "running").all()
        for generation in interrupted:
            generation.status = "failed"
            generation.error_message = "服务重启导致任务中断，可点击重试"
        db.commit()
    finally:
        db.close()


@app.get("/api/health")
def health() -> dict:
    key = settings.llm_api_key or ""
    configured = bool(key) and not key.startswith("sk-your-")
    return {
        "status": "ok",
        "llm_model": settings.llm_model,
        "llm_configured": configured,
        "llm_mock_mode": settings.llm_mock_mode,
        "embedding_model": settings.embedding_model,
        "embedding_mode": settings.embedding_mode,
    }
