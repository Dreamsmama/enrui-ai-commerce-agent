"""Vision-model comparison of protected product facts against generated images."""

from app.services.llm import get_llm
from app.config import get_settings


async def compare_product_images(product_name: str, references: list[str], outputs: list[dict]) -> dict:
    settings=get_settings()
    if settings.llm_mock_mode or not settings.llm_api_key:
        return {"status":"unavailable","checked_count":0,"issues":[],"message":"未配置真实视觉模型，商品一致性不会使用模拟结果。"}
    if not references:
        return {"status": "unavailable", "checked_count": 0, "issues": [], "message": "未上传商品原图，无法进行商品一致性对比。"}
    if not outputs:
        return {"status": "unavailable", "checked_count": 0, "issues": [], "message": "暂无生成结果可检查。"}
    sources = [*references[:2], *[item["image_url"] for item in outputs[:4]]]
    prompt = f"""你是电商商品一致性质检员。前 {min(2, len(references))} 张是商品原始参考图，后续图片是“{product_name}”的生成结果。
逐张生成结果与原图对比，只检查可观察事实：瓶型/盒型、包装主色、Logo形状与位置、可见包装文字、商品数量、套装组成。不要评价审美，不要猜测看不清的文字。
输出 JSON：{{"status":"passed|review|blocked","score":0-100,"issues":[{{"output_index":1,"severity":"high|medium","field":"瓶型|包装颜色|Logo|包装文字|商品数量","message":"具体差异","confidence":0-1}}],"summary":"一句话结论"}}"""
    result = await get_llm().chat_vision(prompt, sources, system_prompt="严格进行商品事实对比，输出 JSON。", temperature=0.1, max_tokens=1800, as_json=True)
    issues = result.get("issues") if isinstance(result, dict) else []
    return {"status": result.get("status", "review") if isinstance(result, dict) else "review", "score": result.get("score", 0) if isinstance(result, dict) else 0, "checked_count": min(4, len(outputs)), "issues": issues if isinstance(issues, list) else [], "summary": result.get("summary", "视觉模型已完成对比") if isinstance(result, dict) else "视觉模型返回格式异常，需要人工复核"}
