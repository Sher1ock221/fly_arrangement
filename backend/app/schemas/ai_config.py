"""
AI 配置相关 Pydantic 模型与连接测试请求。
"""
from pydantic import BaseModel, ConfigDict, Field


class AIConfigBase(BaseModel):
    """AI 配置通用字段。"""

    model_name: str = Field(..., min_length=1, max_length=128, description="模型名称，如 qwen2.5:9b")
    base_url: str = Field(..., min_length=1, max_length=512, description="Ollama 服务地址，如 http://127.0.0.1:11434")
    is_active: bool = Field(True, description="是否当前生效（仅一条可为 True）")


class AIConfigCreate(AIConfigBase):
    """保存 AI 配置请求体。"""

    pass


class AIConfigInDB(AIConfigBase):
    """数据库返回。"""

    model_config = ConfigDict(from_attributes=True)
    id: int = Field(..., description="主键")


class AIConfigGetResponse(BaseModel):
    """GET /config 返回：有配置时与 AIConfigInDB 一致，无配置时返回默认空值（避免前端 404/报错）。"""

    model_config = ConfigDict(from_attributes=True)
    id: int = Field(0, description="主键，无配置时为 0")
    model_name: str = Field("", max_length=128, description="模型名称")
    base_url: str = Field("", max_length=512, description="Ollama 服务地址")
    is_active: bool = Field(False, description="是否当前生效")


class AIConfigTestRequest(BaseModel):
    """连接测试请求体。"""

    base_url: str = Field(..., min_length=1, max_length=512)
    model_name: str = Field(..., min_length=1, max_length=128)


class AIConfigConnectionTestResult(BaseModel):
    """POST /test-connection 返回：成功与失败均使用同一结构，便于前端展示诊断信息。"""

    ok: bool
    status: str = Field(
        ...,
        description="ok|connection_refused|timeout|model_not_found|http_error|unknown_error|invalid_base_url",
    )
    detail: str = Field("", description="面向用户的说明，不含敏感信息")
    base_url: str = Field("", description="规范化后的 Ollama 根地址")
    model_name: str = Field("", description="请求的模型名")
    available_models: list[str] = Field(default_factory=list, description="tags 中可见的模型名列表（截断前若干条由后端控制）")
    elapsed_ms: int = Field(0, description="本次测试总耗时（毫秒）")
    model_found: bool = Field(False, description="在 tags 列表中是否找到目标模型")
    available_models_count: int = Field(0, description="Ollama 返回的模型总数（未截断计数，失败时可能为 0）")
