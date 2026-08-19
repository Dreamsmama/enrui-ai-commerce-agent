from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, default="default", index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    category: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    target_users: Mapped[str] = mapped_column(Text, nullable=False, default="")
    brand_name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    ingredients: Mapped[str] = mapped_column(Text, nullable=False, default="")
    usage_method: Mapped[str] = mapped_column(Text, nullable=False, default="")
    specifications: Mapped[str] = mapped_column(Text, nullable=False, default="")
    learned_profile_enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    image_urls: Mapped[Optional[list]] = mapped_column(JSON, nullable=True, default=list)
    detail_image_urls: Mapped[Optional[list]] = mapped_column(JSON, nullable=True, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    generations: Mapped[list["Generation"]] = relationship(
        "Generation", back_populates="product", cascade="all, delete-orphan"
    )
    knowledge_docs: Mapped[list["KnowledgeDocument"]] = relationship(
        "KnowledgeDocument", back_populates="product", cascade="all, delete-orphan"
    )
    assets: Mapped[list["ProductAsset"]] = relationship(
        "ProductAsset", back_populates="product", cascade="all, delete-orphan"
    )


class Generation(Base):
    __tablename__ = "generations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, default="default", index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending/running/completed/failed
    agent_results: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    detail_page_markdown: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    detail_page_sections: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    marketing_copy: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    main_image_copy: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    product: Mapped["Product"] = relationship("Product", back_populates="generations")
    edits: Mapped[list["EditHistory"]] = relationship(
        "EditHistory", back_populates="generation", cascade="all, delete-orphan"
    )


class EditHistory(Base):
    __tablename__ = "edit_histories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    generation_id: Mapped[int] = mapped_column(
        ForeignKey("generations.id"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    section: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    instruction: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    before_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    after_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    generation: Mapped["Generation"] = relationship("Generation", back_populates="edits")


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, default="default", index=True)
    product_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("products.id"), nullable=True, index=True
    )
    brand_name: Mapped[str] = mapped_column(String(256), nullable=False, default="", index=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(64), default="general")
    # product_manual / brand_material / historical_detail / general
    filename: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    product: Mapped[Optional["Product"]] = relationship(
        "Product", back_populates="knowledge_docs"
    )
    chunks: Mapped[list["KnowledgeChunk"]] = relationship(
        "KnowledgeChunk", back_populates="document", cascade="all, delete-orphan"
    )


class DesignSkill(Base):
    __tablename__ = "design_skills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, default="default", index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    scope: Mapped[str] = mapped_column(String(32), nullable=False, default="general")
    category: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    brand_name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    product_id: Mapped[Optional[int]] = mapped_column(ForeignKey("products.id"), nullable=True, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    design_principles: Mapped[str] = mapped_column(Text, nullable=False, default="")
    module_guidance: Mapped[str] = mapped_column(Text, nullable=False, default="")
    visual_rules: Mapped[str] = mapped_column(Text, nullable=False, default="")
    copy_rules: Mapped[str] = mapped_column(Text, nullable=False, default="")
    negative_rules: Mapped[str] = mapped_column(Text, nullable=False, default="")
    primary_color: Mapped[str] = mapped_column(String(16), nullable=False, default="#1f7258")
    accent_color: Mapped[str] = mapped_column(String(16), nullable=False, default="#dceee5")
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ImageReview(Base):
    __tablename__ = "image_reviews"
    __table_args__ = (UniqueConstraint("generation_id", "module_key", name="uq_generation_module_review"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    generation_id: Mapped[int] = mapped_column(ForeignKey("generations.id"), nullable=False, index=True)
    module_key: Mapped[str] = mapped_column(String(64), nullable=False)
    module_title: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    image_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    reasons: Mapped[Optional[list]] = mapped_column(JSON, nullable=True, default=list)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    visual_analysis: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    learning_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class LearnedDesignProfile(Base):
    __tablename__ = "learned_design_profiles"
    __table_args__ = (UniqueConstraint("tenant_id", "brand_name", "category", name="uq_learned_brand_category"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    brand_name: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    positive_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    negative_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    learned_rules: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="observing")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CreativeProject(Base):
    __tablename__ = "creative_projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    brief: Mapped[str] = mapped_column(Text, nullable=False, default="")
    platform: Mapped[str] = mapped_column(String(64), nullable=False, default="天猫")
    output_width: Mapped[int] = mapped_column(Integer, nullable=False, default=750)
    output_height: Mapped[int] = mapped_column(Integer, nullable=False, default=1000)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    viewport: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CanvasNode(Base):
    __tablename__ = "canvas_nodes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("creative_projects.id"), nullable=False, index=True)
    node_type: Mapped[str] = mapped_column(String(32), nullable=False)
    parent_node_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    position_x: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    position_y: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    width: Mapped[float] = mapped_column(Float, nullable=False, default=260)
    height: Mapped[float] = mapped_column(Float, nullable=False, default=320)
    data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CreativeGeneration(Base):
    __tablename__ = "creative_generations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("creative_projects.id"), nullable=False, index=True)
    parent_node_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    action: Mapped[str] = mapped_column(String(64), nullable=False, default="generate")
    selected_node_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="local_demo")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    result_node_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    context_snapshot: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, default=dict)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CreativeFeedback(Base):
    __tablename__ = "creative_feedback"
    __table_args__ = (UniqueConstraint("project_id", "node_id", name="uq_project_node_feedback"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("creative_projects.id"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    node_id: Mapped[str] = mapped_column(ForeignKey("canvas_nodes.id"), nullable=False, index=True)
    image_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    reasons: Mapped[Optional[list]] = mapped_column(JSON, nullable=True, default=list)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    visual_analysis: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    learning_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_documents.id"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    document: Mapped["KnowledgeDocument"] = relationship(
        "KnowledgeDocument", back_populates="chunks"
    )


class ProductAsset(Base):
    __tablename__ = "product_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, default="default", index=True)
    product_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("products.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(64), nullable=False, default="product_image")
    file_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tags: Mapped[Optional[list]] = mapped_column(JSON, nullable=True, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    product: Mapped[Optional["Product"]] = relationship("Product", back_populates="assets")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TenantMember(Base):
    __tablename__ = "tenant_members"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", name="uq_tenant_user"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="member")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
