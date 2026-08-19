"""Learn implicit design preferences from normal image review behavior."""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from app.database import SessionLocal
from app.models import CreativeFeedback, ImageReview, LearnedDesignProfile, Product
from app.services.llm import get_llm

logger = logging.getLogger(__name__)

REVIEW_WEIGHTS = {
    "usable": 1.0,
    "needs_edit": 0.35,
    "rejected": -1.0,
    "final": 2.0,
}


def _top(values: list[str], limit: int = 5) -> list[dict[str, Any]]:
    return [{"value": value, "count": count} for value, count in Counter(values).most_common(limit)]


def _rebuild_profile(db, product: Product) -> LearnedDesignProfile:
    reviews = db.query(ImageReview).join(Product, Product.id == ImageReview.product_id).filter(
        ImageReview.tenant_id == product.tenant_id,
        Product.brand_name == product.brand_name,
        Product.category == product.category,
        ImageReview.learning_status == "completed",
    ).all()
    creative_feedback = db.query(CreativeFeedback).join(Product, Product.id == CreativeFeedback.product_id).filter(
        CreativeFeedback.tenant_id == product.tenant_id,
        Product.brand_name == product.brand_name,
        Product.category == product.category,
        CreativeFeedback.learning_status == "completed",
    ).all()
    reviews = [*reviews, *creative_feedback]
    profile = db.query(LearnedDesignProfile).filter(
        LearnedDesignProfile.tenant_id == product.tenant_id,
        LearnedDesignProfile.brand_name == product.brand_name,
        LearnedDesignProfile.category == product.category,
    ).first()
    if not profile:
        profile = LearnedDesignProfile(
            tenant_id=product.tenant_id,
            brand_name=product.brand_name,
            category=product.category,
        )
        db.add(profile)

    positive = [review for review in reviews if review.weight > 0]
    negative = [review for review in reviews if review.weight < 0]
    styles: list[str] = []
    palettes: list[str] = []
    compositions: list[str] = []
    lighting: list[str] = []
    product_presentation: list[str] = []
    strengths: list[str] = []
    risks: list[str] = []
    for review in positive:
        analysis = review.visual_analysis or {}
        styles.extend(analysis.get("style_tags") or [])
        palettes.extend(analysis.get("palette_tags") or [])
        compositions.extend(analysis.get("composition_tags") or [])
        lighting.extend(analysis.get("lighting_tags") or [])
        product_presentation.extend(analysis.get("product_presentation_tags") or [])
        strengths.extend(analysis.get("strengths") or [])
    for review in negative:
        analysis = review.visual_analysis or {}
        risks.extend(review.reasons or [])
        risks.extend(analysis.get("risks") or [])

    profile.sample_count = len(reviews)
    profile.positive_count = len(positive)
    profile.negative_count = len(negative)
    profile.confidence = round(min(1.0, len(reviews) / 20) * (0.5 + min(0.5, len(positive) / 10)), 3)
    profile.status = "stable" if len(reviews) >= 10 and len(positive) >= 5 else "observing"
    profile.learned_rules = {
        "preferred_styles": _top(styles),
        "preferred_palettes": _top(palettes),
        "preferred_compositions": _top(compositions),
        "preferred_lighting": _top(lighting),
        "preferred_product_presentation": _top(product_presentation),
        "successful_characteristics": _top(strengths),
        "avoid": _top(risks),
        "usage_policy": "观察期画像仅作为弱偏好；稳定后提高生成权重，不覆盖商品事实、品牌规范和合规规则。",
    }
    db.commit()
    db.refresh(profile)
    return profile


async def analyze_review(review_id: int) -> None:
    db = SessionLocal()
    try:
        review = db.query(ImageReview).filter(ImageReview.id == review_id).first()
        if not review:
            return
        product = db.query(Product).filter(Product.id == review.product_id).first()
        if not product:
            return
        review.learning_status = "analyzing"
        db.commit()
        prompt = f"""你是美妆电商视觉分析师。分析这张已经被设计师评价的详情页模块图片，只描述可观察的视觉特征，不推测设计师身份。

商品：{product.name}
品牌：{product.brand_name}
品类：{product.category}
模块：{review.module_title}
设计师评价：{review.status}
快捷原因：{'、'.join(review.reasons or []) or '未填写'}
补充说明：{review.note or '无'}

输出 JSON：
{{
  "style_tags": ["2-5个短标签"],
  "palette_tags": ["2-5个色彩标签"],
  "composition_tags": ["2-5个构图标签"],
  "lighting_tags": ["1-3个光影标签"],
  "product_presentation_tags": ["2-5个商品呈现标签"],
  "text_density": "低/中/高",
  "strengths": ["被采用时可能值得复用的可观察特征"],
  "risks": ["被拒绝或需修改时可观察的问题"]
}}"""
        source = review.image_url.removeprefix("/uploads/")
        analysis = await get_llm().chat_vision(
            prompt,
            [source],
            system_prompt="你只做视觉特征标注，输出简洁 JSON。",
            temperature=0.2,
            max_tokens=1200,
            as_json=True,
        )
        review.visual_analysis = analysis
        review.learning_status = "completed"
        db.commit()
        _rebuild_profile(db, product)
    except Exception as exc:
        logger.exception("Design learning failed for review %s", review_id)
        db.rollback()
        review = db.query(ImageReview).filter(ImageReview.id == review_id).first()
        if review:
            review.learning_status = "failed"
            review.visual_analysis = {"error": str(exc)}
            db.commit()
    finally:
        db.close()


async def analyze_creative_feedback(feedback_id: int) -> None:
    db = SessionLocal()
    try:
        feedback = db.query(CreativeFeedback).filter(CreativeFeedback.id == feedback_id).first()
        if not feedback:
            return
        product = db.query(Product).filter(Product.id == feedback.product_id).first()
        if not product:
            return
        feedback.learning_status = "analyzing"; db.commit()
        prompt = f"""你是美妆电商视觉分析师。分析设计师在创作工作台中评价的图片。
商品：{product.name}
品牌：{product.brand_name}
评价：{feedback.status}
原因：{'、'.join(feedback.reasons or []) or '未填写'}
仅输出 JSON：{{"style_tags":[],"palette_tags":[],"composition_tags":[],"lighting_tags":[],"product_presentation_tags":[],"strengths":[],"risks":[]}}"""
        feedback.visual_analysis = await get_llm().chat_vision(
            prompt, [feedback.image_url.removeprefix("/uploads/")],
            system_prompt="只提取可观察的视觉特征，输出 JSON。", temperature=0.2, max_tokens=1000, as_json=True,
        )
        feedback.learning_status = "completed"; db.commit(); _rebuild_profile(db, product)
    except Exception as exc:
        logger.exception("Creative learning failed for feedback %s", feedback_id)
        db.rollback(); feedback = db.query(CreativeFeedback).filter(CreativeFeedback.id == feedback_id).first()
        if feedback:
            feedback.learning_status = "failed"; feedback.visual_analysis = {"error": str(exc)}; db.commit()
    finally:
        db.close()
