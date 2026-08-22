"""Normalize provider errors into actionable user-facing diagnostics."""

def diagnose_generation_error(error: Exception) -> dict:
    message = str(error)
    lowered = message.lower()
    if "timeout" in lowered or "timed out" in lowered or "超时" in message:
        return {"code": "timeout", "title": "模型响应超时", "message": message, "suggestion": "减少参考图片数量后重试，或稍后再试。", "retryable": True}
    if "429" in lowered or "rate limit" in lowered or "限流" in message:
        return {"code": "rate_limited", "title": "模型请求过于频繁", "message": message, "suggestion": "等待30秒后重试；批量任务会自动按顺序执行。", "retryable": True}
    if any(term in lowered for term in ["insufficient", "balance", "quota", "余额", "额度"]):
        return {"code": "insufficient_balance", "title": "模型额度或余额不足", "message": message, "suggestion": "前往火山方舟检查账户余额和接入点额度。", "retryable": False}
    if any(term in lowered for term in ["moderation", "safety", "content policy", "审核", "敏感"]):
        return {"code": "content_rejected", "title": "内容未通过模型审核", "message": message, "suggestion": "删除医疗化、绝对化或敏感描述后重新生成。", "retryable": False}
    if "400" in lowered or "422" in lowered or "invalid" in lowered or "参数" in message:
        return {"code": "invalid_request", "title": "生成参数不符合模型要求", "message": message, "suggestion": "检查图片格式、尺寸和接入点模型类型。", "retryable": False}
    return {"code": "provider_error", "title": "模型服务暂时不可用", "message": message, "suggestion": "稍后重试；若持续失败，请检查模型配置。", "retryable": True}
