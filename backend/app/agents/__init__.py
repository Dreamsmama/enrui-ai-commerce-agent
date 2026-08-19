"""Multi-agent commerce workflow: understanding → consumer → strategy → detail page."""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models import DesignSkill, KnowledgeDocument, LearnedDesignProfile, Product
from app.rag import retrieve_context_with_hits
from app.services.llm import get_llm

logger = logging.getLogger(__name__)

RISKY_CLAIMS = ("根治", "药到病除", "100%有效", "绝对安全", "全网第一", "永久", "零风险")


def _extract_ingredient_names(value: str) -> list[str]:
    names: list[str] = []
    for match in re.findall(r"(?:^|\n)\s*\d+[\.、]\s*([^：:\n]{1,30})", value):
        cleaned = re.sub(r"[（(].*?[）)]", "", match).strip(" ，,；;。")
        if cleaned:
            names.append(cleaned)
    if not names and len(value) <= 180:
        names = [item.strip() for item in re.split(r"[，,、；;\n]", value) if 1 < len(item.strip()) <= 30]
    return list(dict.fromkeys(names))


def validate_detail_sections(product: Product, sections: dict[str, Any]) -> dict[str, Any]:
    text = "\n".join(str(value) for key, value in sections.items() if not key.startswith("_"))
    warnings: list[dict[str, str]] = []
    missing = [key for key in DetailPageAgent.SECTION_KEYS if not str(sections.get(key, "")).strip()]
    for key in missing:
        warnings.append({"type": "missing_module", "section": key, "message": "模块内容为空"})
    for claim in RISKY_CLAIMS:
        if claim in text:
            warnings.append({"type": "risky_claim", "section": "", "message": f"发现高风险表述：{claim}"})
    facts = {
        "brand": product.brand_name,
        "ingredients": product.ingredients,
        "specifications": product.specifications,
        "usage_method": product.usage_method,
    }
    covered = [name for name, value in facts.items() if value and value in text]
    provided = [name for name, value in facts.items() if value]
    ingredient_names = _extract_ingredient_names(product.ingredients)
    matched_ingredients = [name for name in ingredient_names if name in text]
    missing_ingredients = [name for name in ingredient_names if name not in text]
    if product.ingredients and ingredient_names and not matched_ingredients:
        warnings.append({"type": "fact_coverage", "section": "advantages", "message": "未覆盖已录入的核心成分"})
    score = max(0, 100 - len(missing) * 10 - sum(15 for item in warnings if item["type"] == "risky_claim") - sum(8 for item in warnings if item["type"] == "fact_coverage"))
    return {
        "score": score,
        "passed": score >= 80 and not any(item["type"] == "risky_claim" for item in warnings),
        "warnings": warnings,
        "fact_coverage": {
            "covered": covered,
            "provided": provided,
            "ingredients": {
                "provided": ingredient_names,
                "matched": matched_ingredients,
                "not_mentioned": missing_ingredients,
                "status": "none" if ingredient_names and not matched_ingredients else ("partial" if missing_ingredients else "covered"),
            },
        },
        "disclaimer": "自动检查仅用于内容初筛，发布前仍需品牌法务或合规人员审核。",
    }


def _product_text(product: Product) -> str:
    return f"""商品名称：{product.name}
品牌名称：{product.brand_name}
商品类别：{product.category}
价格：{product.price}
商品描述：{product.description}
目标用户：{product.target_users}
核心成分：{product.ingredients}
使用方法：{product.usage_method}
规格信息：{product.specifications}"""


def _rag_block(rag_context: str, prefix: str = "知识库参考：") -> str:
    if not rag_context:
        return ""
    return f"{prefix}\n{rag_context}"


PLATFORM_DESIGN_RULES = """平台通用详情页规则：
- 商品图片是视觉主体，文字只承担信息层级与购买解释。
- 首屏先传达品牌、商品和核心利益点，再展开卖点、成分、场景与使用方法。
- 所有功效与成分表达必须来自商品资料或知识库，不得虚构。
- 模块必须可独立替换、重排，并保持整页视觉一致。"""


def _matched_design_skills(db: Session, product: Product) -> list[DesignSkill]:
    skills = db.query(DesignSkill).filter(
        DesignSkill.tenant_id == product.tenant_id, DesignSkill.enabled.is_(True)
    ).all()
    rank = {"general": 0, "category": 1, "brand": 2, "product": 3}
    matched = []
    for skill in skills:
        applies = (
            skill.scope == "general"
            or (skill.scope == "category" and skill.category.strip() == product.category.strip())
            or (skill.scope == "brand" and skill.brand_name.strip() == product.brand_name.strip())
            or (skill.scope == "product" and skill.product_id == product.id)
        )
        if applies:
            matched.append(skill)
    return sorted(matched, key=lambda item: (rank.get(item.scope, 0), item.id))


def _design_skill_context(skills: list[DesignSkill]) -> str:
    blocks = [PLATFORM_DESIGN_RULES]
    for skill in skills:
        blocks.append(f"""[{skill.scope} Skill｜{skill.name}]
说明：{skill.description}
设计原则：{skill.design_principles}
模块指导：{skill.module_guidance}
视觉规则：{skill.visual_rules}
文案规则：{skill.copy_rules}
禁止事项：{skill.negative_rules}
主色：{skill.primary_color}；辅助色：{skill.accent_color}""")
    return "\n\n".join(blocks)


def _learned_profile_context(profile: Optional[LearnedDesignProfile]) -> str:
    if not profile or not profile.sample_count:
        return ""
    rules = profile.learned_rules or {}
    return f"""[系统从设计师图片选择中学习的偏好｜{profile.status}]
样本：{profile.sample_count}；正样本：{profile.positive_count}；负样本：{profile.negative_count}；置信度：{profile.confidence:.0%}
偏好风格：{rules.get('preferred_styles', [])}
偏好色彩：{rules.get('preferred_palettes', [])}
偏好构图：{rules.get('preferred_compositions', [])}
偏好光影：{rules.get('preferred_lighting', [])}
商品呈现：{rules.get('preferred_product_presentation', [])}
避免：{rules.get('avoid', [])}
使用原则：该画像只作为弱偏好，不得覆盖商品事实、品牌正式规范和合规规则。"""


class ProductUnderstandingAgent:
    """Agent1: Multimodal product understanding."""

    name = "product_understanding"

    async def run(self, product: Product, rag_context: str = "") -> dict[str, Any]:
        llm = get_llm()
        asset_images = [
            asset.file_url for asset in product.assets if asset.mime_type.startswith("image/")
        ]
        images = (product.image_urls or []) + (product.detail_image_urls or []) + asset_images
        prompt = f"""请作为资深电商商品分析师，基于以下商品信息与图片进行深度理解分析。

{_product_text(product)}

{_rag_block(rag_context)}

请输出 JSON，字段如下：
{{
  "product_type": "商品类型细分",
  "features": ["产品特点1", "产品特点2", "..."],
  "core_advantages": ["核心优势1", "核心优势2", "..."],
  "purchase_reasons": ["用户购买理由1", "用户购买理由2", "..."],
  "visual_insights": "基于图片的视觉卖点与呈现建议（若无图片则根据描述推断）"
}}"""
        system = "你是电商多模态商品理解专家。结合文字与图片信息输出结构化 JSON。"
        if images:
            return await llm.chat_vision(
                prompt, images, system_prompt=system, as_json=True, temperature=0.4
            )
        return await llm.chat_json(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            temperature=0.4,
        )


class ConsumerAnalysisAgent:
    """Agent2: Target consumer & purchase psychology."""

    name = "consumer_analysis"

    async def run(
        self,
        product: Product,
        understanding: dict[str, Any],
        rag_context: str = "",
    ) -> dict[str, Any]:
        llm = get_llm()
        prompt = f"""请作为消费者洞察专家，基于商品信息与商品理解结果，输出目标消费者分析。

{_product_text(product)}

商品理解结果：
{understanding}

{_rag_block(rag_context)}

请输出 JSON：
{{
  "target_consumers": [
    {{"persona": "画像名称", "demographics": "人群特征", "needs": "核心需求"}}
  ],
  "usage_scenarios": ["消费场景1", "消费场景2"],
  "pain_points": ["购买痛点1", "购买痛点2"],
  "decision_factors": ["购买决策因素1", "购买决策因素2"]
}}"""
        return await llm.chat_json(
            [
                {
                    "role": "system",
                    "content": "你是电商消费者洞察专家，擅长用户画像与购买心理分析。输出 JSON。",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.5,
        )


class MarketingStrategyAgent:
    """Agent3: Positioning, selling points ranking, competitive edge."""

    name = "marketing_strategy"

    async def run(
        self,
        product: Product,
        understanding: dict[str, Any],
        consumer: dict[str, Any],
        rag_context: str = "",
    ) -> dict[str, Any]:
        llm = get_llm()
        prompt = f"""请作为电商营销策略专家，制定该商品的营销策略。

{_product_text(product)}

商品理解：
{understanding}

消费者分析：
{consumer}

{_rag_block(rag_context)}

请输出 JSON：
{{
  "positioning": "一句话营销定位",
  "selling_points_ranked": [
    {{"rank": 1, "point": "卖点", "reason": "为何排此位"}}
  ],
  "competitive_advantages": ["竞争优势1", "竞争优势2"],
  "tone_style": "建议的文案语气风格",
  "main_image_copy_suggestions": ["主图文案建议1", "主图文案建议2", "主图文案建议3"]
}}"""
        return await llm.chat_json(
            [
                {
                    "role": "system",
                    "content": "你是电商营销策略专家，擅长定位与卖点提炼。输出 JSON。",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.6,
        )


class DetailPageAgent:
    """Agent4: Full product detail page generation."""

    name = "detail_page"

    SECTION_KEYS = [
        "title",
        "selling_points",
        "advantages",
        "scenarios",
        "pain_solutions",
        "purchase_reasons",
        "faq",
        "after_sales",
    ]

    async def run(
        self,
        product: Product,
        understanding: dict[str, Any],
        consumer: dict[str, Any],
        strategy: dict[str, Any],
        rag_context: str = "",
        design_context: str = "",
    ) -> dict[str, Any]:
        llm = get_llm()
        prompt = f"""请作为资深电商详情页文案专家，生成完整商品详情页内容。

{_product_text(product)}

商品理解：{understanding}
消费者分析：{consumer}
营销策略：{strategy}

设计师 Skill（必须遵循，后出现的规则优先级更高）：
{design_context}

{_rag_block(rag_context, "知识库参考（请优先引用其中的规格/卖点/品牌信息）：")}

请输出 JSON，字段均为 Markdown 字符串：
{{
  "title": "商品标题（吸引点击、含核心关键词）",
  "selling_points": "核心卖点五点描述（Markdown 列表，共5条）",
  "advantages": "产品优势介绍（Markdown）",
  "scenarios": "使用场景（Markdown）",
  "pain_solutions": "用户痛点解决方案（Markdown）",
  "purchase_reasons": "购买理由（Markdown）",
  "faq": "FAQ（Markdown，至少5个问答）",
  "after_sales": "售后说明（Markdown）",
  "marketing_copy": "短营销文案（适合投放/朋友圈，200字内）",
  "main_image_copy": "主图文案建议（多条，Markdown 列表）"
}}"""
        result = await llm.chat_json(
            [
                {
                    "role": "system",
                    "content": (
                        "你是电商详情页文案专家。文案要具体、有说服力、符合中国电商平台风格。"
                        "输出 JSON，各字段为 Markdown。"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=6000,
        )
        return result

    @staticmethod
    def sections_to_markdown(
        sections: dict[str, Any], module_order: Optional[list[str]] = None
    ) -> str:
        labels = {
            "title": "商品标题",
            "selling_points": "核心卖点",
            "advantages": "产品优势",
            "scenarios": "使用场景",
            "pain_solutions": "痛点解决方案",
            "purchase_reasons": "购买理由",
            "faq": "FAQ",
            "after_sales": "售后说明",
        }
        order = module_order or list(labels)
        parts: list[str] = []
        for key in order:
            content = sections.get(key)
            if not content:
                continue
            if key == "title":
                parts.append(f"# {str(content).strip('#').strip()}\n")
                continue
            heading = labels.get(key, key)
            parts.append(f"## {heading}\n\n{content.strip()}\n")
        return "\n".join(parts).strip() + "\n"


class CommerceAgentWorkflow:
    """Orchestrates Agent1 → Agent2 → Agent3 → Agent4 with RAG context."""

    def __init__(self) -> None:
        self.understanding_agent = ProductUnderstandingAgent()
        self.consumer_agent = ConsumerAnalysisAgent()
        self.strategy_agent = MarketingStrategyAgent()
        self.detail_agent = DetailPageAgent()

    async def run(
        self,
        db: Session,
        product: Product,
        on_progress: Optional[Any] = None,
    ) -> dict[str, Any]:
        async def progress(stage: str, data: Any = None) -> None:
            if on_progress:
                await on_progress(stage, data)

        query = (
            f"{product.name} {product.brand_name} {product.category} {product.description} "
            f"{product.target_users} {product.ingredients} {product.specifications}"
        )
        retrieval = await retrieve_context_with_hits(
            db,
            query,
            product_id=product.id,
            brand_name=product.brand_name,
            tenant_id=product.tenant_id,
            top_k=6,
        )
        rag_context = retrieval["context"]
        brand_docs = db.query(KnowledgeDocument).filter(
            KnowledgeDocument.tenant_id == product.tenant_id,
            KnowledgeDocument.product_id.is_(None),
            KnowledgeDocument.brand_name == product.brand_name,
        ).all()
        if brand_docs:
            brand_context = "\n\n".join(
                f"[品牌必读｜{doc.title}]\n{doc.content[:4000]}" for doc in brand_docs
            )
            rag_context = f"{brand_context}\n\n{rag_context}".strip()
        design_skills = _matched_design_skills(db, product)
        design_context = _design_skill_context(design_skills)
        learned_profile = db.query(LearnedDesignProfile).filter(
            LearnedDesignProfile.tenant_id == product.tenant_id,
            LearnedDesignProfile.brand_name == product.brand_name,
            LearnedDesignProfile.category == product.category,
        ).first() if product.learned_profile_enabled else None
        learned_context = _learned_profile_context(learned_profile)
        if learned_context:
            design_context = f"{design_context}\n\n{learned_context}"
        if product.assets:
            asset_context = "\n".join(
                f"- {asset.asset_type}｜{asset.name}｜{asset.description or '无补充说明'}"
                for asset in product.assets
            )
            rag_context = f"{rag_context}\n\n[商品与品牌素材]\n{asset_context}".strip()

        execution_steps = []

        await progress("product_understanding", {"status": "running"})
        started = time.perf_counter()
        understanding = await self.understanding_agent.run(product, rag_context)
        duration = round((time.perf_counter() - started) * 1000)
        execution_steps.append({"key": "product_understanding", "label": "商品理解 Agent", "status": "completed", "duration_ms": duration})
        await progress("product_understanding_done", {"result": understanding, "duration_ms": duration})

        await progress("consumer_analysis", {"status": "running"})
        started = time.perf_counter()
        consumer = await self.consumer_agent.run(product, understanding, rag_context)
        duration = round((time.perf_counter() - started) * 1000)
        execution_steps.append({"key": "consumer_analysis", "label": "消费者分析 Agent", "status": "completed", "duration_ms": duration})
        await progress("consumer_analysis_done", {"result": consumer, "duration_ms": duration})

        await progress("marketing_strategy", {"status": "running"})
        started = time.perf_counter()
        strategy = await self.strategy_agent.run(
            product, understanding, consumer, rag_context
        )
        duration = round((time.perf_counter() - started) * 1000)
        execution_steps.append({"key": "marketing_strategy", "label": "营销策略 Agent", "status": "completed", "duration_ms": duration})
        await progress("marketing_strategy_done", {"result": strategy, "duration_ms": duration})

        await progress("detail_page", {"status": "running"})
        started = time.perf_counter()
        detail = await self.detail_agent.run(
            product, understanding, consumer, strategy, rag_context, design_context
        )
        duration = round((time.perf_counter() - started) * 1000)
        execution_steps.append({"key": "detail_page", "label": "详情页生成 Agent", "status": "completed", "duration_ms": duration})
        await progress("detail_page_done", {"result": detail, "duration_ms": duration})

        sections = {
            k: detail.get(k, "")
            for k in DetailPageAgent.SECTION_KEYS
        }
        module_order = list(DetailPageAgent.SECTION_KEYS)
        markdown = DetailPageAgent.sections_to_markdown(sections, module_order)
        quality_check = validate_detail_sections(product, sections)

        return {
            "agent_results": {
                "product_understanding": understanding,
                "consumer_analysis": consumer,
                "marketing_strategy": strategy,
                "detail_page": detail,
                "rag_used": bool(rag_context),
                "brand_knowledge_used": [doc.title for doc in brand_docs],
                "design_skills_used": [
                    {"id": skill.id, "name": skill.name, "scope": skill.scope}
                    for skill in design_skills
                ],
                "design_context": design_context,
                "design_theme": {
                    "primary_color": design_skills[-1].primary_color if design_skills else "#1f7258",
                    "accent_color": design_skills[-1].accent_color if design_skills else "#dceee5",
                },
                "generation_basis": {
                    "product": {
                        "id": product.id,
                        "name": product.name,
                        "brand_name": product.brand_name,
                        "category": product.category,
                        "fields_used": [
                            {"name": "商品描述", "value": product.description},
                            {"name": "目标用户", "value": product.target_users},
                            {"name": "核心成分", "value": product.ingredients},
                            {"name": "使用方法", "value": product.usage_method},
                            {"name": "规格信息", "value": product.specifications},
                        ],
                    },
                    "assets": {
                        "product_images": product.image_urls or [],
                        "detail_images": product.detail_image_urls or [],
                        "files": [
                            {"id": asset.id, "name": asset.name, "type": asset.asset_type, "url": asset.file_url}
                            for asset in product.assets
                        ],
                    },
                    "brand_documents": [
                        {"id": doc.id, "title": doc.title, "brand_name": doc.brand_name, "chunks": doc.chunk_count}
                        for doc in brand_docs
                    ],
                    "rag": {"method": retrieval["method"], "hits": retrieval["hits"]},
                    "skill_chain": [
                        {"level": "platform", "name": "平台通用详情页规则"},
                        *[
                            {
                                "level": skill.scope,
                                "id": skill.id,
                                "name": skill.name,
                                "primary_color": skill.primary_color,
                                "accent_color": skill.accent_color,
                                "design_principles": skill.design_principles,
                                "visual_rules": skill.visual_rules,
                                "copy_rules": skill.copy_rules,
                                "negative_rules": skill.negative_rules,
                            }
                            for skill in design_skills
                        ],
                        *([{
                            "level": "learned",
                            "name": "设计师图片选择学习画像",
                            "status": learned_profile.status,
                            "confidence": learned_profile.confidence,
                            "sample_count": learned_profile.sample_count,
                            "learned_rules": learned_profile.learned_rules,
                        }] if learned_profile and learned_profile.sample_count else []),
                    ],
                },
                "execution_trace": {
                    "status": "completed",
                    "current_stage": None,
                    "steps": execution_steps,
                    "total_duration_ms": sum(step["duration_ms"] for step in execution_steps),
                },
                "quality_check": quality_check,
            },
            "detail_page_sections": {**sections, "_module_order": module_order},
            "detail_page_markdown": markdown,
            "marketing_copy": detail.get("marketing_copy", ""),
            "main_image_copy": detail.get("main_image_copy", ""),
        }


class DetailEditorService:
    """Edit / regenerate individual sections of a generated detail page."""

    async def edit(
        self,
        product: Product,
        sections: dict[str, Any],
        *,
        action: str,
        section: Optional[str] = None,
        instruction: Optional[str] = None,
        target_audience: Optional[str] = None,
        agent_results: Optional[dict] = None,
        rag_context: str = "",
    ) -> dict[str, Any]:
        llm = get_llm()
        agent_results = agent_results or {}

        if action == "regenerate_section":
            if not section:
                raise ValueError("section is required for regenerate_section")
            prompt = f"""请重新生成商品详情页的「{section}」模块。

{_product_text(product)}

历史 Agent 分析结果：{agent_results}
当前完整详情页各模块：{sections}
额外指令：{instruction or "无"}

{_rag_block(rag_context)}

请只输出 JSON：{{ "{section}": "重新生成的 Markdown 内容" }}"""
            result = await llm.chat_json(
                [
                    {
                        "role": "system",
                        "content": "你是电商详情页文案专家。仅重新生成指定模块，输出 JSON。",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
            )
            new_sections = dict(sections)
            if section in result:
                new_sections[section] = result[section]
            elif "content" in result:
                new_sections[section] = result["content"]
            return new_sections

        if action == "optimize_tone":
            tone_hint = instruction or "更专业、更有说服力、更适合电商转化"
            prompt = f"""请优化以下商品详情页各模块的语气风格。

优化方向：{tone_hint}

{_product_text(product)}

当前内容：{sections}

请输出 JSON，字段与输入各模块 key 一致，值为优化后的 Markdown。"""
            return await llm.chat_json(
                [
                    {
                        "role": "system",
                        "content": "你是电商文案优化专家。保持信息完整，优化语气与节奏。输出 JSON。",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.6,
                max_tokens=6000,
            )

        if action == "change_audience":
            audience = target_audience or instruction or "年轻用户"
            prompt = f"""请将以下商品详情页改写为更适合「{audience}」的版本。

{_product_text(product)}

当前内容：{sections}

请输出 JSON，字段与输入各模块 key 一致，值为改写后的 Markdown。标题、卖点、场景、FAQ 等都要贴合新受众。"""
            return await llm.chat_json(
                [
                    {
                        "role": "system",
                        "content": "你是电商文案专家，擅长针对不同受众调整表达。输出 JSON。",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
                max_tokens=6000,
            )

        raise ValueError(f"Unknown action: {action}")
