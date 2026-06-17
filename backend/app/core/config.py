"""应用配置（pydantic-settings）。

- Key 用 SecretStr 存储，绝不打印明文；传 SDK 时再 .get_secret_value()。
- .env 必须为无 BOM 的 UTF-8（Windows 易踩 BOM 坑）。
- 注意：环境变量 OPENAI_API_BASE 优先级高于 OPENAI_BASE_URL，二选一别同设。
"""
from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    llm_provider: str = "openai"

    openai_api_key: SecretStr = SecretStr("")
    openai_base_url: str | None = None  # 读 OPENAI_BASE_URL（自定义中转）
    openai_model: str = "gpt-4o-mini"

    anthropic_api_key: SecretStr = SecretStr("")
    anthropic_base_url: str | None = None
    anthropic_model: str = "claude-haiku-4-5-20251001"

    temperature: float = 0.0

    # 高德 Web 服务（后端代理，Key 不下发前端）
    amap_web_key: SecretStr = SecretStr("")

    # 前端直连需放行的源（开发期 Vite 默认 5173）。
    # 如需用环境变量 CORS_ORIGINS 覆盖，须传 JSON 数组字符串，例如：
    #   CORS_ORIGINS=["http://localhost:5173","https://example.com"]
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    def active_api_key(self) -> str:
        """返回当前 provider 的明文 Key（仅供启动校验/构造 SDK 用，勿记日志）。"""
        if self.llm_provider == "anthropic":
            return self.anthropic_api_key.get_secret_value()
        return self.openai_api_key.get_secret_value()


@lru_cache
def get_settings() -> Settings:
    return Settings()
