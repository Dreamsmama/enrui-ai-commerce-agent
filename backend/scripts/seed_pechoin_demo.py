"""Seed idempotent Pechoin brand knowledge and a brand design Skill."""

import asyncio

from app.database import SessionLocal, init_db
from app.models import DesignSkill, KnowledgeDocument, Product
from app.rag import index_document

PRODUCT_NAME = "百雀羚肌初赋活水乳护肤套装"
DOC_TITLE = "百雀羚品牌与详情页表达规范（Demo）"
SKILL_NAME = "百雀羚东方草本护肤详情页 Skill"

BRAND_KNOWLEDGE = """# 百雀羚品牌知识与内容规范

## 品牌定位
百雀羚是中国本土护肤品牌。本 Demo 的详情页表达以“东方护肤、草本灵感、温润可靠、长期日常护理”为核心印象。品牌内容应体现成熟、可信、克制的专业感，不采用夸张叫卖或过度年轻化的网络语言。

## 目标消费者
核心关注人群为重视日常补水保湿、肌肤细腻度、弹润感和初老护理的女性消费者。她们关注产品是否适合长期使用、成分信息是否可信、护理步骤是否简单，以及礼盒是否具有品质感。

## 品牌语气
1. 温润而专业：使用清晰、平实、有依据的护肤语言。
2. 东方而现代：可以表达东方审美和草本灵感，但避免堆砌古风辞藻。
3. 克制而可信：先讲商品事实，再讲消费者利益，不承诺确定性效果。
4. 有陪伴感：强调早晚护理、循序使用和日常肌肤管理。

## 视觉识别建议
主视觉以草木绿、松石绿、米白、暖金为主要色系，保持大面积留白和稳定的信息秩序。商品包装和产品实拍必须是视觉主体，植物、水润纹理、柔光可作为辅助元素。避免高饱和促销红、霓虹科技蓝、复杂赛博光效和廉价爆炸贴。

## 图片使用规则
首屏优先使用套装合影或完整水乳组合图；单品模块分别展示精华水和乳液；成分、功效和使用方法模块可结合产品局部图、质地联想和简洁图标。不得通过修图改变包装文字、瓶型、容量或商品实际组成。

## 内容结构建议
推荐顺序为：品牌与套装首屏、核心利益点、水乳协同逻辑、代表性成分、质地与肤感、适用人群和场景、两步使用方法、规格与温馨提示。每屏只突出一个核心信息，标题简短，正文承担证据和解释。

## 合规边界
不得使用“根治、永久、100%有效、绝对安全、立即消除皱纹”等绝对化或医疗化表述。紧致、抗皱、补水等功效表达必须以产品备案、包装或品牌正式资料为依据。成分信息不得代替完整成分表；效果因肤质和使用习惯存在差异；规格、赠品和套装组成以实际销售页面及包装为准。

## 当前商品关联提示
肌初赋活水乳护肤套装的详情页应重点解释水乳搭配的日常护理价值，围绕补水、柔润、弹润和初老护理组织内容。所有具体成分、容量和使用方法优先引用商品资料，不从品牌调性推导商品事实。
"""


async def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        product = db.query(Product).filter(Product.name == PRODUCT_NAME).first()
        if not product:
            raise RuntimeError(f"未找到商品：{PRODUCT_NAME}")

        document = db.query(KnowledgeDocument).filter(
            KnowledgeDocument.tenant_id == product.tenant_id,
            KnowledgeDocument.title == DOC_TITLE,
        ).first()
        if not document:
            document = KnowledgeDocument(tenant_id=product.tenant_id, title=DOC_TITLE)
            db.add(document)
        document.product_id = None
        document.brand_name = product.brand_name
        document.doc_type = "brand_material"
        document.content = BRAND_KNOWLEDGE
        db.commit()
        db.refresh(document)
        await index_document(db, document)

        skill = db.query(DesignSkill).filter(
            DesignSkill.tenant_id == product.tenant_id,
            DesignSkill.name == SKILL_NAME,
        ).first()
        if not skill:
            skill = DesignSkill(tenant_id=product.tenant_id, name=SKILL_NAME)
            db.add(skill)
        skill.scope = "brand"
        skill.brand_name = product.brand_name
        skill.category = ""
        skill.product_id = None
        skill.description = "适用于百雀羚护肤商品，以东方草本、温润可信和现代留白为核心。"
        skill.design_principles = "商品实拍为主体；每屏一个核心结论；先事实后利益；整体温润、克制、可靠；兼顾礼盒品质感与日常护理感。"
        skill.module_guidance = "首屏套装合影与核心定位；水乳协同；补水柔润与弹润卖点；代表性成分；质地肤感；适用场景；两步使用；规格与提示。"
        skill.visual_rules = "草木绿与松石绿为主，米白大面积留白，暖金仅作细节；产品占主要视觉面积；使用柔光、水润纹理和轻植物元素；信息层级简洁。"
        skill.copy_rules = "标题控制在4至12字；语气温润专业；避免堆砌形容词；功效、成分、容量必须来自商品或品牌知识；必要处增加以包装为准提示。"
        skill.negative_rules = "禁止高饱和促销红、霓虹科技蓝、爆炸贴、包装变形；禁止医疗化、绝对化功效；禁止虚构专利、检测、奖项、成分和消费者数据。"
        skill.primary_color = "#176b55"
        skill.accent_color = "#e4efe8"
        skill.enabled = True
        db.commit()
        db.refresh(skill)
        print(f"brand_document_id={document.id} chunks={document.chunk_count}")
        print(f"design_skill_id={skill.id} scope={skill.scope} brand={skill.brand_name}")
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
