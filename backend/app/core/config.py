"""
从 .env 读取配置，供数据库与各模块使用。
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator


DEVELOPMENT_JWT_SECRET = "fly-arrangement-dev-secret-change-in-production"


class Settings(BaseSettings):
    """应用配置，未设置时从环境变量与 .env 读取。"""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 数据库连接串：
    # - Docker/服务端部署通常使用 PostgreSQL（例如 postgresql+asyncpg://...）
    # - 桌面单机版默认使用 SQLite（相对路径更适合跨开发环境）
    # - 实际运行时始终以环境变量 DATABASE_URL 优先
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/fly_arrangement.db"

    # 飞书（仅服务端部署使用；桌面 SQLite 构建不注册飞书路由，缺省不报错）
    FEISHU_APP_ID: str = ""  # deprecated: server-only
    FEISHU_APP_SECRET: str = ""  # deprecated: server-only
    FEISHU_VERIFICATION_TOKEN: str = ""  # deprecated: server-only
    FEISHU_ENCRYPT_KEY: str = ""  # deprecated: server-only
    FEISHU_BOT_NAME: str = ""  # deprecated: server-only
    FEISHU_ENABLE_SIGNATURE_CHECK: bool = True  # deprecated: server-only
    FEISHU_ENABLE_WHITELIST: bool = False  # deprecated: server-only
    FEISHU_WHITELIST_OPEN_IDS: str = ""  # deprecated: server-only

    # 飞书卡片回调公网根地址（服务端）；桌面版可忽略
    PUBLIC_API_BASE_URL: str = "http://localhost:18000"

    # JWT 认证（账号体系）
    JWT_SECRET_KEY: str = DEVELOPMENT_JWT_SECRET
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 天

    # 可选：覆盖版本/环境（环境变量 APP_VERSION / ENVIRONMENT）
    APP_VERSION: str = "0.1.0"
    ENVIRONMENT: str = "dev"

    # 单次提醒：触发时间若距「现在」近于该秒数，自动顺延，避免解析/执行延迟导致误报「已过期」
    REMINDER_MIN_LEAD_SECONDS: int = 60

    # Ollama 主链路（/api/chat）超时与重试配置（兼容旧名：OLLAMA_CHAT_TIMEOUT_SECONDS 仍用于部分路径）
    OLLAMA_CHAT_TIMEOUT_SECONDS: int = 120
    # 桌面稳定性：默认不重试，避免同一卡死请求被放大为多次长耗时
    OLLAMA_CHAT_RETRIES: int = 0
    OLLAMA_CHAT_RETRY_DELAY_SECONDS: int = 2
    # 分阶段超时（秒）：连接失败应快速返回；工具规划与总结单独收紧，避免小模型卡死整轮
    AI_OLLAMA_CONNECT_TIMEOUT_SECONDS: float = 5.0
    AI_OLLAMA_READ_TIMEOUT_SECONDS: int = 90
    AI_OLLAMA_TOOL_PLANNING_TIMEOUT_SECONDS: int = 45
    AI_OLLAMA_SUMMARY_TIMEOUT_SECONDS: int = 20
    # 单次 /api/v1/ai/chat 外层硬上限（与 httpx 分阶段超时配合，防止整链路透传挂死）
    AI_OLLAMA_MAX_TOTAL_SECONDS: int = 75
    # 轻薄本 / 桌面：无工具闲聊直连 Ollama 的读超时（plain_ollama_chat_for_web 使用）
    AI_PLAIN_CHAT_TIMEOUT_SECONDS: int = 45
    # 工具规划首轮（chat_with_tools 非 summary 阶段）读超时，优先于 AI_OLLAMA_TOOL_PLANNING_TIMEOUT_SECONDS
    AI_TOOL_PLANNING_TIMEOUT_SECONDS: int = 35
    # 桌面普通对话（无工具）更短输出；工具链 token 上限（qwen3.5:4b 等）
    AI_CHAT_TEMPERATURE: float = 0.2
    AI_TOOL_CHAT_TEMPERATURE: float = 0.15
    AI_DESKTOP_SHORT_REPLY_NUM_PREDICT: int = 64
    AI_DESKTOP_SIMPLE_NUM_PREDICT: int = 128
    AI_TOOL_CHAT_NUM_PREDICT: int = 192
    # 工具执行成功后优先用后端模板总结，避免二次请求 Ollama 再超时（桌面推荐开启）
    AI_ACTION_SUMMARY_USE_TEMPLATE: bool = True
    # 轻薄本模式与快捷路径开关（桌面默认开；服务端可在 .env 关闭）
    AI_LIGHT_LAPTOP_MODE: bool = True
    AI_LOCAL_SMALLTALK_SHORTCUT_ENABLED: bool = True
    AI_SIMPLE_CALENDAR_SHORTCUT_ENABLED: bool = True
    # 对 qwen/qwen3 系普通闲聊在 system 中弱化长 thinking（见 ai_engine.plain_ollama_chat_for_web）
    AI_OLLAMA_DISABLE_THINKING: bool = True

    # Ollama 预热链路超时与重试配置
    OLLAMA_WARMUP_TIMEOUT_SECONDS: int = 60
    OLLAMA_WARMUP_RETRIES: int = 3
    OLLAMA_WARMUP_RETRY_DELAY_SECONDS: int = 3

    @model_validator(mode="after")
    def validate_production_jwt_secret(self) -> "Settings":
        """Reject the built-in development key in production deployments."""
        if self.ENVIRONMENT.strip().lower() in {"prod", "production"}:
            secret = self.JWT_SECRET_KEY.strip()
            if secret == DEVELOPMENT_JWT_SECRET or len(secret) < 32:
                raise ValueError(
                    "Production requires JWT_SECRET_KEY with at least 32 characters; "
                    "do not use the development default."
                )
        return self

    def get_async_database_url(self) -> str:
        """返回用于 AsyncEngine 的连接串（与 DATABASE_URL 一致，兼容旧调用）。"""
        return self.DATABASE_URL


settings = Settings()
