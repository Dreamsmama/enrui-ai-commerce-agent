"""Fast local image checks before ecommerce detail-page export."""

from __future__ import annotations

from PIL import Image, ImageStat

from app.config import get_settings
from app.models import CanvasNode, StoryboardModule
from app.services.storage import get_storage


def _hash(image: Image.Image) -> str:
    small = image.convert("L").resize((8, 8), Image.Resampling.LANCZOS)
    values = list(small.getdata())
    average = sum(values) / len(values)
    return "".join("1" if value >= average else "0" for value in values)


def _distance(left: str, right: str) -> int:
    return sum(a != b for a, b in zip(left, right))


def check_visual_quality(modules: list[StoryboardModule], nodes: dict[str, CanvasNode], expected_width: int) -> dict:
    issues: list[dict] = []
    hashes: list[tuple[StoryboardModule, str]] = []
    checked = 0
    for module in modules:
        node = nodes.get(module.final_node_id or module.preview_node_id or "")
        image_url = str(node.data.get("image_url") or "") if node else ""
        if not image_url:
            issues.append({"module_id": module.id, "module_title": module.title, "severity": "high", "type": "missing_image", "message": "模块尚未生成图片"})
            continue
        if image_url.startswith(("http://", "https://", "data:")):
            issues.append({"module_id": module.id, "module_title": module.title, "severity": "medium", "type": "external_image", "message": "外部图片无法完成本地清晰度检测，请人工复核"})
            continue
        path = get_storage().local_path(image_url)
        if not path:
            issues.append({"module_id": module.id, "module_title": module.title, "severity": "high", "type": "missing_file", "message": "图片文件不存在，需要重新生成"})
            continue
        image = Image.open(path).convert("RGB")
        checked += 1
        if image.width < expected_width or image.height < 600:
            issues.append({"module_id": module.id, "module_title": module.title, "severity": "high", "type": "low_resolution", "message": f"图片仅 {image.width}×{image.height}，低于建议交付尺寸"})
        ratio = image.width / max(1, image.height)
        if ratio < 0.55 or ratio > 1.05:
            issues.append({"module_id": module.id, "module_title": module.title, "severity": "medium", "type": "aspect_ratio", "message": f"当前宽高比 {ratio:.2f} 与详情页模块差异较大，拼接时可能裁切"})
        contrast = ImageStat.Stat(image.convert("L").resize((128, 128))).stddev[0]
        if contrast < 7:
            issues.append({"module_id": module.id, "module_title": module.title, "severity": "high", "type": "blank_image", "message": "图片对比度过低，可能为空白图或主体不可见"})
        hashes.append((module, _hash(image)))
    for index, (module, fingerprint) in enumerate(hashes):
        for other_module, other_fingerprint in hashes[:index]:
            if _distance(fingerprint, other_fingerprint) <= 3:
                issues.append({"module_id": module.id, "module_title": module.title, "severity": "medium", "type": "duplicate_image", "message": f"与“{other_module.title}”画面高度相似，建议确认是否重复"})
                break
    high_count = sum(issue["severity"] == "high" for issue in issues)
    medium_count = sum(issue["severity"] == "medium" for issue in issues)
    return {"status": "blocked" if high_count else "review" if medium_count else "passed", "score": max(0, 100 - high_count * 15 - medium_count * 5), "checked_count": checked, "high_count": high_count, "medium_count": medium_count, "issues": issues}
