from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ── Product ──────────────────────────────────────────────

class ProductCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    category: str = ""
    price: float = 0.0
    description: str = ""
    target_users: str = ""
    brand_name: str = ""
    ingredients: str = ""
    usage_method: str = ""
    specifications: str = ""
    image_urls: list[str] = Field(default_factory=list)
    detail_image_urls: list[str] = Field(default_factory=list)
    learned_profile_enabled: bool = True


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    price: Optional[float] = None
    description: Optional[str] = None
    target_users: Optional[str] = None
    brand_name: Optional[str] = None
    ingredients: Optional[str] = None
    usage_method: Optional[str] = None
    specifications: Optional[str] = None
    image_urls: Optional[list[str]] = None
    detail_image_urls: Optional[list[str]] = None
    learned_profile_enabled: Optional[bool] = None


class ProductOut(BaseModel):
    id: int
    name: str
    category: str
    price: float
    description: str
    target_users: str
    brand_name: str = ""
    ingredients: str = ""
    usage_method: str = ""
    specifications: str = ""
    image_urls: list[str] = []
    detail_image_urls: list[str] = []
    created_at: datetime
    updated_at: datetime
    generation_count: int = 0
    learned_profile_enabled: bool = True

    model_config = {"from_attributes": True}


# ── Generation ───────────────────────────────────────────

class GenerationOut(BaseModel):
    id: int
    product_id: int
    status: str
    agent_results: Optional[dict[str, Any]] = None
    detail_page_markdown: Optional[str] = None
    detail_page_sections: Optional[dict[str, Any]] = None
    marketing_copy: Optional[str] = None
    main_image_copy: Optional[str] = None
    error_message: Optional[str] = None
    attempt_count: int = 0
    max_attempts: int = 3
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class GenerationListItem(BaseModel):
    id: int
    product_id: int
    product_name: str = ""
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Edit ─────────────────────────────────────────────────

class EditRequest(BaseModel):
    action: str  # regenerate_section | optimize_tone | change_audience
    section: Optional[str] = None
    instruction: Optional[str] = None
    target_audience: Optional[str] = None


class GenerationModulesUpdate(BaseModel):
    sections: dict[str, str]
    module_order: list[str]


class EditHistoryOut(BaseModel):
    id: int
    generation_id: int
    action: str
    section: Optional[str] = None
    instruction: Optional[str] = None
    before_content: Optional[str] = None
    after_content: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Knowledge ────────────────────────────────────────────

class KnowledgeDocCreate(BaseModel):
    title: str
    doc_type: str = "general"
    content: str
    product_id: Optional[int] = None
    brand_name: str = ""


class KnowledgeDocOut(BaseModel):
    id: int
    product_id: Optional[int] = None
    brand_name: str = ""
    title: str
    doc_type: str
    filename: Optional[str] = None
    content: str
    chunk_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class DesignSkillCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    scope: str = "general"
    category: str = ""
    brand_name: str = ""
    product_id: Optional[int] = None
    description: str = ""
    design_principles: str = ""
    module_guidance: str = ""
    visual_rules: str = ""
    copy_rules: str = ""
    negative_rules: str = ""
    primary_color: str = "#1f7258"
    accent_color: str = "#dceee5"
    enabled: bool = True


class DesignSkillOut(DesignSkillCreate):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ImageReviewCreate(BaseModel):
    status: str
    reasons: list[str] = Field(default_factory=list)
    note: str = ""


class ImageReviewOut(BaseModel):
    id: int
    generation_id: int
    product_id: int
    module_key: str
    module_title: str
    image_url: str
    status: str
    reasons: list[str] = Field(default_factory=list)
    note: str
    weight: float
    visual_analysis: Optional[dict[str, Any]] = None
    learning_status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LearnedDesignProfileOut(BaseModel):
    id: int
    brand_name: str
    category: str
    sample_count: int
    positive_count: int
    negative_count: int
    confidence: float
    learned_rules: dict[str, Any] = Field(default_factory=dict)
    status: str
    updated_at: datetime

    model_config = {"from_attributes": True}


class CreativeProjectCreate(BaseModel):
    product_id: int
    name: str = Field(..., min_length=1, max_length=256)
    brief: str = ""
    platform: str = "天猫"
    output_width: int = 750
    output_height: int = 1000


class CreativeProjectOut(CreativeProjectCreate):
    id: int
    status: str
    viewport: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CanvasNodeCreate(BaseModel):
    id: Optional[str] = None
    node_type: str
    parent_node_id: Optional[str] = None
    position_x: float = 0
    position_y: float = 0
    width: float = 260
    height: float = 320
    data: dict[str, Any] = Field(default_factory=dict)


class CanvasNodeOut(CanvasNodeCreate):
    id: str
    project_id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CanvasSaveRequest(BaseModel):
    nodes: list[CanvasNodeCreate]
    viewport: dict[str, Any] = Field(default_factory=dict)


class CreativeGenerateRequest(BaseModel):
    prompt: str = ""
    action: str = "generate"
    selected_node_ids: list[str] = Field(default_factory=list)
    parent_node_id: Optional[str] = None
    auto_select_materials: bool = True
    count: int = Field(default=3, ge=1, le=6)


class CreativeGenerationOut(BaseModel):
    id: int
    project_id: int
    parent_node_id: Optional[str] = None
    prompt: str
    action: str
    selected_node_ids: list[str]
    provider: str
    status: str
    result_node_ids: list[str]
    context_snapshot: dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CreativeFeedbackCreate(BaseModel):
    status: str
    reasons: list[str] = Field(default_factory=list)


class CreativeFeedbackOut(BaseModel):
    id: int
    project_id: int
    product_id: int
    node_id: str
    image_url: str
    status: str
    reasons: list[str] = Field(default_factory=list)
    weight: float
    visual_analysis: Optional[dict[str, Any]] = None
    learning_status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProductAssetOut(BaseModel):
    id: int
    product_id: Optional[int] = None
    name: str
    asset_type: str
    file_url: str
    mime_type: str
    description: str
    tags: list[str] = []
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Dashboard ────────────────────────────────────────────

class DashboardStats(BaseModel):
    product_count: int
    generation_count: int
    knowledge_doc_count: int
    recent_tasks: list[GenerationListItem]


class RegisterRequest(BaseModel):
    tenant_name: str = Field(..., min_length=2, max_length=200)
    tenant_code: str = Field(..., min_length=2, max_length=100, pattern=r"^[a-z0-9-]+$")
    name: str = Field(..., min_length=1, max_length=200)
    email: str = Field(..., min_length=5, max_length=320)
    password: str = Field(..., min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: str
    password: str


class AuthOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict[str, str]
    tenant: dict[str, str]
