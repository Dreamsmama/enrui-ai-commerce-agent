"""Real multimodal quality review. Never returns a simulated passing result."""
from __future__ import annotations
from app.config import get_settings
from app.services.llm import get_llm


async def review_commercial_suite(product_name:str,brand_name:str,references:list[str],outputs:list[dict],quality_rules:list[str]|None=None)->dict:
    settings=get_settings()
    if settings.llm_mock_mode or not settings.llm_api_key:
        return {"status":"unavailable","score":0,"items":[],"issues":[],"message":"真实视觉模型未配置，禁止使用模拟质检结果。"}
    limited=outputs[:4];images=[*references[:2],*[row["image_url"] for row in limited]]
    prompt=f"""你是电商商业图像质检员。前 {min(2,len(references))} 张是商品基准图，后 {len(limited)} 张是 {brand_name} {product_name} 的生成页面。
当前品类专属质检规则：{quality_rules or ['使用通用电商质检规则']}
必须逐张检查：商品结构、包装颜色、Logo、可见文字、数量；品牌色调与气质；构图、光影、材质和商业可用性。再检查整套的色调漂移、构图重复、商品角度重复和视觉节奏。
输出JSON：{{"status":"passed|review|blocked","score":0-100,"items":[{{"output_index":1,"product_consistency":0-100,"brand_match":0-100,"commercial_aesthetic":0-100,"issues":["..."]}}],"suite_consistency":{{"score":0-100,"color_drift":false,"composition_repetition":false,"rhythm_issue":false}},"issues":[{{"severity":"high|medium","output_index":1,"message":"..."}}],"summary":"..."}}
任一商品结构、Logo、文字、数量错误必须 blocked。看不清时必须 review，不得猜测。"""
    result=await get_llm().chat_vision(prompt,images,system_prompt="只根据图像可观察事实质检，严格输出JSON。",temperature=.1,max_tokens=2600,as_json=True)
    if not isinstance(result,dict):return {"status":"unavailable","score":0,"items":[],"issues":[],"message":"视觉模型返回格式无效"}
    result["model"]=settings.llm_vision_model;result["checked_count"]=len(limited);result["is_real_model"]=True
    return result


async def compare_protected_text(source_url:str,output_url:str,regions:list[dict])->dict:
    settings=get_settings()
    if settings.llm_mock_mode or not settings.llm_api_key:return {"status":"unavailable","is_real_model":False,"issues":["真实视觉模型未配置"]}
    expected=[{"type":r.get("type"),"text":r.get("text","")} for r in regions]
    prompt=f'''图1是包装标准图，图2是生成结果。保护区期望Logo/文字为：{expected}。逐项对比形状、拼写、数字和位置，看不清必须review。输出JSON：{{"status":"passed|review|blocked","matches":[{{"expected":"...","observed":"...","same":true,"confidence":0-1}}],"issues":["..."]}}'''
    result=await get_llm().chat_vision(prompt,[source_url,output_url],system_prompt="严格比对包装文字与Logo，只输出JSON。",temperature=.1,max_tokens=1400,as_json=True)
    return {**result,"model":settings.llm_vision_model,"is_real_model":True} if isinstance(result,dict) else {"status":"unavailable","is_real_model":False,"issues":["返回格式无效"]}
