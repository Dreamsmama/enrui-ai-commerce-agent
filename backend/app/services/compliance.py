"""Deterministic pre-export checks for cosmetic ecommerce claims."""

from __future__ import annotations

import re

from app.models import KnowledgeDocument, Product, StoryboardModule

ABSOLUTE_TERMS = ["最好", "最佳", "第一", "顶级", "永久", "100%", "完全消除", "彻底解决", "零风险"]
MEDICAL_TERMS = ["治疗", "治愈", "消炎", "抗菌", "杀菌", "修复细胞", "根治", "药效"]
DATA_PATTERN = re.compile(r"\d+(?:\.\d+)?%|\d+(?:\.\d+)?倍|临床|检测证明|专利")


def check_storyboard_compliance(product: Product, modules: list[StoryboardModule], documents: list[KnowledgeDocument]) -> dict:
    issues: list[dict] = []
    sources = [{"id": doc.id, "title": doc.title, "doc_type": doc.doc_type} for doc in documents]
    evidence_text = "\n".join(f"{doc.title}\n{doc.content}" for doc in documents)
    for module in modules:
        content = "。".join([module.title, module.objective, module.content_guidance])
        for term in ABSOLUTE_TERMS:
            if term.lower() in content.lower():
                issues.append({"module_id": module.id, "module_title": module.title, "severity": "high", "type": "absolute_claim", "claim": term, "message": f"包含绝对化用语“{term}”，建议删除或改为有边界的表达", "sources": []})
        for term in MEDICAL_TERMS:
            if term in content:
                issues.append({"module_id": module.id, "module_title": module.title, "severity": "high", "type": "medical_claim", "claim": term, "message": f"化妆品内容不应直接使用医疗化宣称“{term}”", "sources": []})
        data_claims = DATA_PATTERN.findall(content)
        for claim in data_claims:
            matched = [source for source in sources if claim in evidence_text or source["doc_type"] in {"certificate", "test_report"}]
            issues.append({"module_id": module.id, "module_title": module.title, "severity": "medium" if matched else "high", "type": "data_claim", "claim": claim, "message": "数据型宣称已找到证据材料" if matched else f"数据型宣称“{claim}”未找到检测报告或证书依据", "sources": matched})
        if module.module_type == "ingredients" and not product.ingredients.strip():
            issues.append({"module_id": module.id, "module_title": module.title, "severity": "high", "type": "missing_evidence", "claim": "成分功效", "message": "尚未录入核心成分，不应生成具体成分功效", "sources": []})
    high_count = sum(issue["severity"] == "high" for issue in issues)
    medium_count = sum(issue["severity"] == "medium" for issue in issues)
    return {"status": "blocked" if high_count else "review" if medium_count else "passed", "score": max(0, 100 - high_count * 18 - medium_count * 6), "high_count": high_count, "medium_count": medium_count, "issues": issues, "knowledge_sources": sources}
