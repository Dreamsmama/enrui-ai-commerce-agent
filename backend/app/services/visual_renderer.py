"""Render image-led ecommerce detail modules from verified product assets."""

from __future__ import annotations

import textwrap
import uuid
from pathlib import Path
from typing import Any, Optional

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from app.config import get_settings
from app.models import Product

WIDTH = 750
HEIGHT = 1000
FONT_PATH = "/System/Library/Fonts/STHeiti Medium.ttc"


def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_PATH, size)


def _local_image(url: str) -> Path | None:
    if not url or url.startswith(("http://", "https://", "data:")):
        return None
    path = get_settings().upload_path / url.removeprefix("/uploads/")
    return path if path.exists() else None


def _gradient(top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(image)
    for y in range(HEIGHT):
        ratio = y / (HEIGHT - 1)
        color = tuple(int(top[i] * (1 - ratio) + bottom[i] * ratio) for i in range(3))
        draw.line((0, y, WIDTH, y), fill=color)
    return image


def _color(value: str, fallback: tuple[int, int, int]) -> tuple[int, int, int]:
    try:
        cleaned = value.strip().lstrip("#")
        if len(cleaned) != 6:
            return fallback
        return tuple(int(cleaned[index:index + 2], 16) for index in (0, 2, 4))
    except (TypeError, ValueError):
        return fallback


def _mix(color: tuple[int, int, int], white_ratio: float) -> tuple[int, int, int]:
    return tuple(int(channel * (1 - white_ratio) + 255 * white_ratio) for channel in color)


def _paste_packshot(canvas: Image.Image, path: Path, box: tuple[int, int, int, int]) -> None:
    source = Image.open(path).convert("RGB")
    source = ImageEnhance.Contrast(source).enhance(1.03)
    fitted = ImageOps.contain(source, (box[2] - box[0], box[3] - box[1]))
    x = box[0] + (box[2] - box[0] - fitted.width) // 2
    y = box[1] + (box[3] - box[1] - fitted.height) // 2
    canvas.paste(fitted, (x, y))


def _text(draw: ImageDraw.ImageDraw, value: str, xy: tuple[int, int], size: int, fill=(24, 48, 40), width=18) -> None:
    lines = textwrap.wrap(value.replace("\n", " "), width=width) or [value]
    draw.multiline_text(xy, "\n".join(lines), font=_font(size), fill=fill, spacing=12)


def render_visual_modules(
    product: Product,
    sections: dict[str, Any],
    generation_id: int,
    design_theme: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    output_dir = get_settings().upload_path / "generated" / str(generation_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = [_local_image(url) for url in (product.image_urls or []) + (product.detail_image_urls or [])]
    packshots = [path for path in paths if path]
    if not packshots:
        return {"visual_modules": [], "long_image_url": None, "warning": "请先上传产品图片"}

    modules: list[dict[str, Any]] = []
    design_theme = design_theme or {}
    primary = _color(design_theme.get("primary_color", ""), (31, 114, 88))
    accent = _color(design_theme.get("accent_color", ""), (220, 238, 229))

    def save(key: str, title: str, canvas: Image.Image, sources: list[Path]) -> None:
        filename = f"{len(modules) + 1:02d}-{key}-{uuid.uuid4().hex[:8]}.png"
        canvas.save(output_dir / filename, quality=95)
        modules.append({
            "key": key,
            "title": title,
            "image_url": f"/uploads/generated/{generation_id}/{filename}",
            "source_images": [path.name for path in sources],
            "status": "completed",
        })

    hero = Image.open(packshots[-1]).convert("RGB")
    hero = ImageOps.fit(hero, (WIDTH, HEIGHT), method=Image.Resampling.LANCZOS)
    overlay = Image.new("RGBA", hero.size, (0, 0, 0, 0))
    ImageDraw.Draw(overlay).rectangle((0, 0, WIDTH, 260), fill=(245, 246, 238, 220))
    hero = Image.alpha_composite(hero.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(hero)
    _text(draw, product.brand_name or "品牌臻选", (54, 44), 28, width=24)
    _text(draw, str(sections.get("title") or product.name), (54, 92), 46, width=13)
    save("hero", "首屏主视觉", hero, [packshots[-1]])

    duo = _gradient(_mix(accent, 0.78), _mix(accent, 0.12))
    draw = ImageDraw.Draw(duo)
    _text(draw, "水乳协同  日常焕活", (70, 58), 46, width=16)
    _text(draw, "先水后乳 · 补水柔润 · 细腻弹润", (72, 130), 25, fill=(72, 96, 82), width=28)
    _paste_packshot(duo, packshots[0], (40, 210, 375, 900))
    _paste_packshot(duo, packshots[min(1, len(packshots) - 1)], (375, 210, 710, 900))
    save("duo", "水乳组合", duo, packshots[:2])

    ingredient = _gradient(_mix(accent, 0.62), _mix(primary, 0.3))
    ingredient = ingredient.filter(ImageFilter.GaussianBlur(0.3))
    draw = ImageDraw.Draw(ingredient)
    _text(draw, "核心成分护理", (58, 56), 48, width=16)
    _text(draw, "烟酰胺 · 透明质酸 · 多肽复配", (60, 130), 27, fill=(48, 91, 68), width=25)
    _paste_packshot(ingredient, packshots[0], (330, 210, 710, 930))
    for index, label in enumerate(["补水保湿", "紧致弹润", "细腻柔滑"]):
        y = 300 + index * 150
        draw.ellipse((55, y, 145, y + 90), fill=(247, 250, 242), outline=primary, width=3)
        _text(draw, label, (165, y + 18), 29, width=8)
    save("ingredients", "成分功效视觉", ingredient, [packshots[0]])

    steps = _gradient((250, 247, 238), (232, 239, 226))
    draw = ImageDraw.Draw(steps)
    _text(draw, "每日水乳护理三步曲", (62, 55), 44, width=18)
    step_labels = [("01", "洁面后\n轻拍精华水"), ("02", "均匀涂抹\n紧肤焕颜乳"), ("03", "轻柔按摩\n帮助吸收")]
    for index, (number, label) in enumerate(step_labels):
        x = 55 + index * 230
        draw.rounded_rectangle((x, 220, x + 190, 690), radius=28, fill=(255, 255, 252), outline=(204, 216, 199), width=2)
        _text(draw, number, (x + 55, 255), 52, fill=(30, 126, 82), width=3)
        _text(draw, label, (x + 30, 360), 28, width=7)
    _text(draw, "建议早晚使用 · 实际使用方法以产品包装为准", (75, 820), 24, fill=(80, 92, 82), width=30)
    save("usage", "使用步骤", steps, [])

    long_image = Image.new("RGB", (WIDTH, HEIGHT * len(modules)), "white")
    for index, module in enumerate(modules):
        module_path = get_settings().upload_path / module["image_url"].removeprefix("/uploads/")
        long_image.paste(Image.open(module_path).convert("RGB"), (0, index * HEIGHT))
    long_filename = "detail-page-long.png"
    long_image.save(output_dir / long_filename, quality=95)
    return {"visual_modules": modules, "long_image_url": f"/uploads/generated/{generation_id}/{long_filename}"}
