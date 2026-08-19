"""OpenAI-compatible LLM client with text, vision, and embedding support."""

from __future__ import annotations

import base64
import json
import logging
import mimetypes
import re
from pathlib import Path
from typing import Any, Optional

from openai import AsyncOpenAI
import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(self) -> None:
        settings = get_settings()
        self.settings = settings
        self.client = AsyncOpenAI(
            api_key=settings.llm_api_key or "sk-placeholder",
            base_url=settings.llm_api_base,
            timeout=settings.llm_timeout_seconds,
            max_retries=1,
        )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: Optional[dict] = None,
    ) -> str:
        kwargs: dict[str, Any] = {
            "model": model or self.settings.llm_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            kwargs["response_format"] = response_format
        if self.settings.llm_disable_thinking:
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

        response = await self.client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content or ""
        return content.strip()

    async def chat_json(
        self,
        messages: list[dict[str, Any]],
        *,
        model: Optional[str] = None,
        temperature: float = 0.5,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        if self.settings.llm_mock_mode:
            return self._mock_json(messages)
        # Prefer native JSON mode; fall back to markdown fence extraction
        try:
            raw = await self.chat(
                messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
        except Exception:
            system_hint = {
                "role": "system",
                "content": "You must respond with valid JSON only. No markdown fences.",
            }
            raw = await self.chat(
                [system_hint, *messages],
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        return self._parse_json(raw)

    async def chat_vision(
        self,
        text_prompt: str,
        image_sources: list[str],
        *,
        system_prompt: Optional[str] = None,
        temperature: float = 0.5,
        max_tokens: int = 4096,
        as_json: bool = True,
    ) -> Any:
        content: list[dict[str, Any]] = [{"type": "text", "text": text_prompt}]
        for src in image_sources[:6]:  # limit images
            image_url = await self._resolve_image_url(src)
            if image_url:
                content.append({"type": "image_url", "image_url": {"url": image_url}})

        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": content})

        if as_json:
            return await self.chat_json(
                messages,
                model=self.settings.llm_vision_model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        return await self.chat(
            messages,
            model=self.settings.llm_vision_model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self.settings.llm_mock_mode:
            return [self._mock_embedding(text) for text in texts]
        if self.settings.embedding_mode == "multimodal":
            return await self._embed_multimodal_texts(texts)
        # Batch in chunks of 64
        all_embeddings: list[list[float]] = []
        batch_size = 64
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            response = await self.client.embeddings.create(
                model=self.settings.embedding_model,
                input=batch,
            )
            sorted_data = sorted(response.data, key=lambda x: x.index)
            all_embeddings.extend([d.embedding for d in sorted_data])
        return all_embeddings

    async def _embed_multimodal_texts(self, texts: list[str]) -> list[list[float]]:
        base_url = (self.settings.embedding_base_url or self.settings.llm_api_base).rstrip("/")
        api_key = self.settings.embedding_api_key or self.settings.llm_api_key
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        embeddings: list[list[float]] = []
        async with httpx.AsyncClient(timeout=60.0) as client:
            for text in texts:
                response = await client.post(
                    f"{base_url}/embeddings/multimodal",
                    headers=headers,
                    json={
                        "model": self.settings.embedding_model,
                        "encoding_format": "float",
                        "input": [{"type": "text", "text": text}],
                    },
                )
                response.raise_for_status()
                payload = response.json()
                data = payload.get("data") or []
                item = data[0] if isinstance(data, list) and data else data
                embedding = item.get("embedding") if isinstance(item, dict) else None
                if embedding and isinstance(embedding[0], list):
                    embedding = embedding[0]
                if not isinstance(embedding, list):
                    raise ValueError("多模态向量接口未返回有效 embedding")
                if len(embedding) != self.settings.embedding_dimension:
                    logger.warning(
                        "Embedding dimension mismatch: expected %s, got %s",
                        self.settings.embedding_dimension,
                        len(embedding),
                    )
                embeddings.append([float(value) for value in embedding])
        return embeddings

    async def _resolve_image_url(self, src: str) -> Optional[str]:
        if src.startswith("data:"):
            return src
        if src.startswith("http://") or src.startswith("https://"):
            return src

        # Local file path → base64 data URI
        path = Path(src)
        if not path.is_absolute():
            path = get_settings().upload_path / src.lstrip("/")
        if not path.exists():
            # Try relative to uploads/images
            alt = get_settings().upload_path / "images" / Path(src).name
            if alt.exists():
                path = alt
            else:
                logger.warning("Image not found: %s", src)
                return None

        mime, _ = mimetypes.guess_type(str(path))
        mime = mime or "image/jpeg"
        data = path.read_bytes()
        b64 = base64.b64encode(data).decode("ascii")
        return f"data:{mime};base64,{b64}"

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        raw = raw.strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
        # Extract from markdown fence
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass
        # Find outermost braces
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                pass
        logger.error("Failed to parse JSON from LLM: %s", raw[:500])
        return {"raw": raw}

    @staticmethod
    def _mock_embedding(text: str, dimensions: int = 64) -> list[float]:
        vector = [0.0] * dimensions
        for index, char in enumerate(text):
            vector[(ord(char) + index) % dimensions] += 1.0
        norm = sum(value * value for value in vector) ** 0.5 or 1.0
        return [value / norm for value in vector]

    @staticmethod
    def _mock_json(messages: list[dict[str, Any]]) -> dict[str, Any]:
        prompt = json.dumps(messages, ensure_ascii=False)
        if "marketing_copy" in prompt:
            return {
                "title": "专业成分护理，让每一次使用更安心",
                "selling_points": "- 核心成分清晰\n- 商品资料可追溯\n- 使用步骤简单\n- 适配日常护理场景\n- 专业克制的品牌表达",
                "advantages": "从商品资料与品牌知识出发，准确表达产品价值。",
                "scenarios": "## 日常护理\n适合早晚护肤与换季护理。",
                "pain_solutions": "将复杂商品信息转化为清晰易懂的购买理由。",
                "purchase_reasons": "信息完整、成分明确、使用方便。",
                "faq": "**Q：如何使用？**\n\nA：按商品说明在清洁后使用。\n\n**Q：适合谁？**\n\nA：请结合商品资料与个人肤质判断。",
                "after_sales": "请以品牌正式售后政策与商品包装信息为准。",
                "marketing_copy": "把复杂成分讲清楚，把真实价值呈现出来。",
                "main_image_copy": "- 专业成分护理\n- 商品知识驱动",
            }
        if "product_type" in prompt:
            return {
                "product_type": "美妆护肤商品",
                "features": ["配方信息清晰", "适合日常护理", "商品资料可追溯"],
                "core_advantages": ["基于商品知识生成", "突出核心成分与使用体验"],
                "purchase_reasons": ["信息完整", "使用方法明确"],
                "visual_insights": "建议使用产品正面图、成分特写与简洁留白布局。",
            }
        if "target_consumers" in prompt:
            return {
                "target_consumers": [{"persona": "品质护肤用户", "demographics": "关注成分与体验", "needs": "稳定、清晰的护理方案"}],
                "usage_scenarios": ["早晚日常护理", "换季肌肤护理"],
                "pain_points": ["商品信息复杂", "难以判断是否适合自己"],
                "decision_factors": ["成分", "功效依据", "使用方法"],
            }
        if "positioning" in prompt:
            return {
                "positioning": "以真实商品知识支撑的专业护理方案",
                "selling_points_ranked": [{"rank": 1, "point": "核心成分清晰", "reason": "降低购买决策成本"}],
                "competitive_advantages": ["资料完整", "表达专业"],
                "tone_style": "专业、克制、可信",
                "main_image_copy_suggestions": ["科学护理，简单有效", "核心成分，一目了然"],
            }
        return {"raw": "Mock LLM response"}


_llm: Optional[LLMClient] = None


def get_llm() -> LLMClient:
    global _llm
    if _llm is None:
        _llm = LLMClient()
    return _llm
