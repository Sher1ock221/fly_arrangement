from datetime import datetime, timezone
from fastapi import APIRouter

from app.core.config import settings
from app.services.ollama_service import get_ollama_status

router = APIRouter()


@router.get("/health")
async def health():
    """公开健康检查，供部署层或反向代理探针使用。不返回敏感信息。"""
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": getattr(settings, "APP_VERSION", "0.1.0"),
    }


@router.get("/ai/ready")
async def ai_ready():
    """AI 就绪状态：供前端显示「AI 正在预热」或允许发送首条请求。"""
    status = get_ollama_status()
    return {
        "ollama_reachable": status.get("ollama_reachable", False),
        "model_ready": status.get("model_ready", False),
        "last_warmup_at": status.get("last_warmup_at"),
        "ready": status.get("model_ready", False),
    }
