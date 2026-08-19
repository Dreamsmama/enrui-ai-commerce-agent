"""Replaceable image generation provider for the creative canvas."""

from __future__ import annotations

import base64
import mimetypes
import textwrap
import uuid
from pathlib import Path
from typing import Optional

import httpx
from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps

from app.config import get_settings

FONT_PATH = "/System/Library/Fonts/STHeiti Medium.ttc"


def _local_path(url: str) -> Optional[Path]:
    if not url or url.startswith(("http://", "https://", "data:")):
        return None
    path = get_settings().upload_path / url.removeprefix("/uploads/")
    return path if path.exists() else None


def _image_input(url: str) -> str:
    path = _local_path(url)
    if not path:
        return url
    mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{mime_type};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def _seedream_size(width: int, height: int) -> str:
    ratio = max(0.34, min(3.0, width / max(height, 1)))
    if ratio >= 1:
        output_width = 2048
        output_height = round(2048 / ratio / 64) * 64
    else:
        output_height = 2048
        output_width = round(2048 * ratio / 64) * 64
    return f"{max(1024, output_width)}x{max(1024, output_height)}"


class ArkSeedreamImageProvider:
    name = "ark_seedream"

    def __init__(self) -> None:
        settings = get_settings()
        self.base_url = (settings.image_generation_base_url or settings.llm_api_base).rstrip("/")
        self.api_key = settings.image_generation_api_key or settings.llm_api_key
        self.model = settings.image_generation_model
        self.timeout = settings.image_generation_timeout_seconds
        self.watermark = settings.image_generation_watermark

    def generate(
        self,
        *,
        source_url: str,
        source_urls: Optional[list[str]] = None,
        variant_labels: Optional[list[str]] = None,
        prompt: str,
        action: str,
        count: int,
        width: int,
        height: int,
        project_id: int,
    ) -> list[str]:
        image_inputs = [_image_input(url) for url in (source_urls or [source_url])[:10] if url]
        output_dir = get_settings().upload_path / "creative" / str(project_id)
        output_dir.mkdir(parents=True, exist_ok=True)
        urls: list[str] = []
        with httpx.Client(timeout=self.timeout) as client:
            for index in range(count):
                label = variant_labels[index] if variant_labels and index < len(variant_labels) else action
                request_prompt = f"{prompt}\n本张图片任务：{label}。保持所有参考商品的包装、瓶型、Logo与可见文字准确一致。"
                payload: dict = {
                    "model": self.model,
                    "prompt": request_prompt,
                    "size": _seedream_size(width, height),
                    "stream": False,
                    "response_format": "url",
                    "watermark": self.watermark,
                }
                if image_inputs:
                    payload["image"] = image_inputs
                response = client.post(
                    f"{self.base_url}/images/generations",
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json=payload,
                )
                if response.is_error:
                    raise RuntimeError(f"Seedream 请求失败 ({response.status_code}): {response.text[:500]}")
                data = response.json().get("data") or []
                if not data or not data[0].get("url"):
                    raise RuntimeError("Seedream 未返回图片 URL")
                image_response = client.get(data[0]["url"])
                image_response.raise_for_status()
                suffix = mimetypes.guess_extension(image_response.headers.get("content-type", "").split(";")[0]) or ".png"
                filename = f"seedream-{uuid.uuid4().hex}{suffix}"
                (output_dir / filename).write_bytes(image_response.content)
                urls.append(f"/uploads/creative/{project_id}/{filename}")
        return urls


class LocalDemoImageProvider:
    name = "local_demo"

    def generate(
        self,
        *,
        source_url: str,
        source_urls: Optional[list[str]] = None,
        variant_labels: Optional[list[str]] = None,
        prompt: str,
        action: str,
        count: int,
        width: int,
        height: int,
        project_id: int,
    ) -> list[str]:
        source_paths = [path for url in (source_urls or [source_url]) if (path := _local_path(url))]
        sources = [Image.open(path).convert("RGB") for path in source_paths]
        if not sources:
            sources = [Image.new("RGB", (width, height), "#eef3ef")]
        output_dir = get_settings().upload_path / "creative" / str(project_id)
        output_dir.mkdir(parents=True, exist_ok=True)
        palettes = [(235, 243, 237), (242, 236, 226), (226, 240, 239), (242, 229, 232)]
        urls = []
        for index in range(count):
            variant_label = variant_labels[index] if variant_labels and index < len(variant_labels) else action
            background = Image.new("RGB", (width, height), palettes[index % len(palettes)])
            visible_sources = sources[:3]
            slot_width = int(width * 0.78 / len(visible_sources))
            for source_index, source in enumerate(visible_sources):
                fitted = ImageOps.contain(ImageEnhance.Contrast(source).enhance(1.02 + index * 0.02), (slot_width, int(height * 0.66)))
                group_width = slot_width * len(visible_sources)
                x = (width - group_width) // 2 + source_index * slot_width + (slot_width - fitted.width) // 2 + (index - 1) * 8
                y = int(height * 0.18) + (int(height * 0.62) - fitted.height) // 2
                background.paste(fitted, (x, y))
            draw = ImageDraw.Draw(background)
            draw.rounded_rectangle((24, 22, width - 24, 128), radius=20, fill=(255, 255, 255), outline=(210, 220, 212), width=2)
            draw.text((45, 38), f"方案 {chr(65 + index)} · {variant_label}", font=ImageFont.truetype(FONT_PATH, 28), fill=(25, 75, 59))
            lines = textwrap.wrap(prompt or "基于所选商品与参考素材生成", width=26)[:2]
            draw.multiline_text((45, 78), "\n".join(lines), font=ImageFont.truetype(FONT_PATH, 17), fill=(80, 92, 84), spacing=4)
            filename = f"result-{uuid.uuid4().hex}.png"
            background.save(output_dir / filename, quality=95)
            urls.append(f"/uploads/creative/{project_id}/{filename}")
        return urls


def get_image_provider() -> ArkSeedreamImageProvider | LocalDemoImageProvider:
    settings = get_settings()
    if settings.image_generation_model and (settings.image_generation_api_key or settings.llm_api_key):
        return ArkSeedreamImageProvider()
    return LocalDemoImageProvider()
