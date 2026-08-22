"""Render image-led ecommerce detail modules from verified product assets."""

from __future__ import annotations

import textwrap
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any, Optional

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from app.config import get_settings
from app.models import BrandVisualProfile, Product, StoryboardModule
from app.services.storage import get_storage

WIDTH = 750
HEIGHT = 1000
FONT_PATH = next((path for path in ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/System/Library/Fonts/STHeiti Medium.ttc") if Path(path).exists()), "/System/Library/Fonts/STHeiti Medium.ttc")


def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_PATH, size)


def _local_image(url: str) -> Path | None:
    return get_storage().local_path(url)


def _store_image(image: Image.Image, filename: str, subdir: str, image_format: str = "PNG") -> str:
    output = BytesIO()
    image.save(output, format=image_format, quality=95)
    return get_storage().save_bytes(output.getvalue(), filename, subdir)


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
        image_url = _store_image(canvas, filename, f"generated/{generation_id}")
        modules.append({
            "key": key,
            "title": title,
            "image_url": image_url,
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
        module_path = _local_image(module["image_url"])
        long_image.paste(Image.open(module_path).convert("RGB"), (0, index * HEIGHT))
    long_filename = "detail-page-long.png"
    long_url = _store_image(long_image, long_filename, f"generated/{generation_id}")
    return {"visual_modules": modules, "long_image_url": long_url}


def render_storyboard_template(product: Product, module: StoryboardModule, project_id: int, brand_profile: BrandVisualProfile | None = None) -> str:
    primary = _color(brand_profile.primary_color, (28, 111, 86)) if brand_profile else (28, 111, 86)
    accent = _color(brand_profile.accent_color, (226, 239, 231)) if brand_profile else (226, 239, 231)
    canvas = _gradient(_mix(accent, 0.86), _mix(accent, 0.18))
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((42, 42, WIDTH - 42, HEIGHT - 42), radius=28, fill=(255, 255, 252), outline=(216, 222, 213), width=2)
    draw.text((72, 76), product.brand_name or "品牌资料", font=_font(24), fill=primary)
    logo_path = _local_image(brand_profile.logo_url) if brand_profile and brand_profile.logo_url else None
    if logo_path:
        _paste_packshot(canvas, logo_path, (560, 62, 680, 125))
    _text(draw, module.title, (72, 125), 48, fill=(24, 39, 34), width=13)
    draw.line((72, 210, WIDTH - 72, 210), fill=(213, 224, 217), width=2)

    content = module.content_guidance or module.objective
    if module.module_type in {"pain_point", "selling_points", "ingredients", "technology", "usage"}:
        parts = [part.strip() for part in content.replace("；", "\n").replace("。", "\n").replace("、", "\n").splitlines() if part.strip()][:4]
        if not parts:
            parts = [module.objective]
        for index, part in enumerate(parts):
            y = 270 + index * 135
            draw.ellipse((78, y, 126, y + 48), fill=primary)
            draw.text((93, y + 7), str(index + 1), font=_font(24), fill="white")
            _text(draw, part, (150, y - 2), 29, width=20)
    else:
        _text(draw, content, (76, 285), 34, width=18)

    image_paths = [_local_image(url) for url in (product.image_urls or [])]
    image_paths = [path for path in image_paths if path]
    if image_paths:
        _paste_packshot(canvas, image_paths[0], (410, 575, 690, 900))
    _text(draw, module.objective, (74, 790 if not image_paths else 705), 24, fill=(78, 91, 84), width=22)
    footer = f"{brand_profile.typography} · 模板预览" if brand_profile else "AI 详情页 · 模板预览"
    draw.text((72, 925), footer[:28], font=_font(18), fill=(128, 137, 131))
    filename = f"template-{module.id}-{uuid.uuid4().hex[:8]}.png"
    return _store_image(canvas, filename, f"creative/{project_id}")


def render_quick_edit(image_url: str, project_id: int, headline: str, subtitle: str, zoom: float, offset_x: float, offset_y: float, text_x: float = 0.08, text_y: float = 0.78, font_size: int = 42, text_color: str = "#183028", text_align: str = "left", text_background: bool = True) -> str:
    source_path = _local_image(image_url)
    if not source_path:
        raise ValueError("当前图片不是本地文件，暂不支持快速编辑")
    source = Image.open(source_path).convert("RGB")
    target_width, target_height = source.size
    scale = max(target_width / source.width, target_height / source.height) * zoom
    resized = source.resize((round(source.width * scale), round(source.height * scale)), Image.Resampling.LANCZOS)
    overflow_x = max(0, resized.width - target_width)
    overflow_y = max(0, resized.height - target_height)
    left = round(overflow_x * (offset_x + 1) / 2)
    top = round(overflow_y * (offset_y + 1) / 2)
    canvas = resized.crop((left, top, left + target_width, top + target_height))
    if headline or subtitle:
        overlay_height = 210 if subtitle else 150
        text_left = round(target_width * text_x); text_top = round(target_height * text_y)
        if text_background:
            overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0)); overlay_draw = ImageDraw.Draw(overlay)
            overlay_draw.rounded_rectangle((max(0, text_left - 24), max(0, text_top - 20), target_width - 28, min(target_height, text_top + overlay_height)), radius=20, fill=(248, 247, 242, 220))
            canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(canvas)
        color = _color(text_color, (24, 48, 40))
        if headline:
            anchor = "ma" if text_align == "center" else "la"
            x = target_width // 2 if text_align == "center" else text_left
            draw.text((x, text_top), headline, font=_font(font_size), fill=color, anchor=anchor)
        if subtitle:
            _text(draw, subtitle, (text_left, text_top + font_size + 18), max(18, round(font_size * 0.55)), fill=color, width=25)
    filename = f"quick-edit-{uuid.uuid4().hex[:10]}.png"
    return _store_image(canvas, filename, f"creative/{project_id}")


def render_style_adjustment(image_url: str, project_id: int, primary_color: str, accent_color: str, whitespace: int, copy_density: int) -> str:
    source_path = _local_image(image_url)
    if not source_path:
        raise ValueError("当前图片无法进行本地风格调整")
    canvas = Image.open(source_path).convert("RGB")
    primary = _color(primary_color, (28, 111, 86))
    accent = _color(accent_color, (226, 239, 231))
    tint = Image.new("RGBA", canvas.size, (*accent, max(8, min(55, round((100 - whitespace) * 0.45)))))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), tint).convert("RGB")
    draw = ImageDraw.Draw(canvas)
    border = max(4, round(canvas.width * (whitespace / 100) * 0.055))
    draw.rounded_rectangle((border, border, canvas.width - border, canvas.height - border), radius=max(12, border), outline=primary, width=max(2, border // 5))
    if copy_density < 35:
        overlay_height = round(canvas.height * 0.08)
        draw.rectangle((0, canvas.height - overlay_height, canvas.width, canvas.height), fill=_mix(accent, 0.72))
    filename = f"style-{uuid.uuid4().hex[:10]}.png"
    return _store_image(canvas, filename, f"creative/{project_id}")
