"""Fast deterministic quality gates used before and after image generation."""
from __future__ import annotations
from pathlib import Path
from PIL import Image, ImageStat
from app.config import get_settings
from app.services.storage import get_storage

PROTECTED = ["保持商品瓶型、盒型和比例准确", "保持包装主色准确", "保持Logo位置与形状", "保持可见包装文字，不新增或篡改", "保持商品数量与套装组成准确"]

LOCK_RULES = {
    "strict": "严格锁定商品：像素级保留商品主体，只允许生成背景、光影和周边元素",
    "balanced": "平衡保持商品：允许小幅调整角度和光影，不得改变结构、包装和文字",
    "creative": "创意演绎商品：允许更大的场景与角度变化，但包装识别特征必须准确",
}
VARIATION_RULES = {"composition":"候选图仅在构图和商品摆位上产生明显差异","scene":"候选图仅变化场景语义和背景元素","color":"候选图仅变化色调方案","model":"候选图仅变化模特或人物表达","lighting":"候选图仅变化布光和阴影"}

def validate_and_rewrite_prompt(prompt:str,module_title:str,facts:list[dict])->dict:
    issues=[];clean=(prompt or "").strip()
    if not clean:issues.append("缺少明确画面任务");clean=f"完成{module_title}的电商视觉设计"
    if len(clean)>1200:issues.append("要求过长，已压缩重点");clean=clean[:1200]
    if not any(x in clean for x in ["商品","产品"]):issues.append("缺少商品主体要求");clean+="。商品必须是画面主体"
    if len([x for x in ["高级","科技","自然","奢华","极简","活泼"] if x in clean])>3:issues.append("视觉方向过多，可能互相冲突")
    corrected=clean+"。"+"；".join(PROTECTED)+"。不得使用未经确认的成分、规格、功效或数量。每屏只表达一个核心目标。"
    return {"original":prompt,"corrected":corrected,"issues":issues,"passed":not issues,"fact_ids":[f.get("id") for f in facts]}

def apply_generation_controls(prompt:str,product_lock:str,variation_axis:str,stage:str)->str:
    stage_rule = "快速预览阶段：优先验证构图和方向，不追求终稿级细节" if stage == "preview" else "高清交付阶段：完整修复边缘、文字、Logo、材质、手指和倒影"
    return f"{prompt}。{LOCK_RULES[product_lock]}。{VARIATION_RULES[variation_axis]}。{stage_rule}。"

def _path(url:str)->Path|None:
    return get_storage().local_path(url)

def inspect_source(url:str)->dict:
    path=_path(url)
    if not path:return {"status":"review","score":50,"issues":["外部或缺失图片无法完成本地准入检查"]}
    image=Image.open(path).convert("RGB");issues=[]
    if image.width<512 or image.height<512:issues.append("分辨率低于512px")
    contrast=ImageStat.Stat(image.resize((128,128)).convert("L")).stddev[0]
    if contrast<10:issues.append("对比度过低，主体可能不清晰")
    ratio=image.width/max(1,image.height)
    if ratio<.35 or ratio>3:issues.append("画幅异常，可能存在严重裁切")
    score=max(0,100-len(issues)*20)
    return {"status":"passed" if not issues else "review","score":score,"issues":issues,"width":image.width,"height":image.height}

def score_output(url:str,module_type:str,brand:dict|None=None)->dict:
    technical=inspect_source(url);issues=list(technical.get("issues",[]));tech=technical.get("score",50)
    consistency=max(0,min(100,round(tech*.7+25)))
    brand_score=max(0,min(100,round(tech*.55+(35 if brand else 20))))
    commercial=max(0,min(100,round(tech*.65+28)))
    total=round(consistency*.5+brand_score*.25+commercial*.25)
    if consistency<75:issues.append("商品一致性置信度不足，建议视觉模型复核")
    recommendation="accept" if total>=82 else "review" if total>=65 else "regenerate"
    return {"total":total,"product_consistency":consistency,"brand_match":brand_score,"commercial_aesthetic":commercial,"technical":tech,"issues":issues,"recommendation":recommendation,"module_type":module_type}

def repair_instruction(scores:dict)->str:
    if scores.get("product_consistency",100)<75:return "锁定商品基准图，降低创意强度，只重做背景与光影，保持瓶型、包装、Logo、文字和数量。"
    if scores.get("brand_match",100)<75:return "重新应用品牌主色、字体气质和禁用元素规则，减少与品牌无关的视觉元素。"
    if scores.get("commercial_aesthetic",100)<75:return "突出商品主体与单一卖点，减少元素密度并增加文案留白。"
    return "保留商品和整体方向，仅优化构图、光影融合与信息层级。"
