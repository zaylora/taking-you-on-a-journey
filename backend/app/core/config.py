"""应用配置（pydantic-settings）。

- Key 用 SecretStr 存储，绝不打印明文；传 SDK 时再 .get_secret_value()。
- .env 必须为无 BOM 的 UTF-8（Windows 易踩 BOM 坑）。
- 注意：环境变量 OPENAI_API_BASE 优先级高于 OPENAI_BASE_URL，二选一别同设。
"""
from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """让 .env 文件优先于 OS 环境变量。

        默认 pydantic 顺序是 env > .env，导致终端里全局的 ANTHROPIC_*/OPENAI_*
        变量（如 Claude Code 注入的中转地址）会顶掉本项目 .env 的配置。
        这里把 dotenv 排到 env 前面；init（显式构造参数）仍最高，便于测试覆盖。
        """
        return init_settings, dotenv_settings, env_settings, file_secret_settings

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

    # Tavily 联网检索（后端代理，Key 不下发前端）
    tavily_api_key: SecretStr = SecretStr("")

    # LangSmith 追踪（可选；设 LANGCHAIN_TRACING_V2=true 启用）
    langchain_tracing_v2: bool = False
    langchain_api_key: SecretStr = SecretStr("")
    langchain_project: str = "trip-planner"
    langchain_endpoint: str = "https://api.smith.langchain.com"

    # 前端直连需放行的源（开发期 Vite 默认 5173）。
    # 如需用环境变量 CORS_ORIGINS 覆盖，须传 JSON 数组字符串，例如：
    cors_origins: list[str] = ["*"]

    # LangGraph SQLite checkpointer + 本地匿名会话元数据。
    checkpoint_db_path: str = "./data/checkpoints.sqlite"

    def active_api_key(self) -> str:
        """返回当前 provider 的明文 Key（仅供启动校验/构造 SDK 用，勿记日志）。"""
        if self.llm_provider == "anthropic":
            return self.anthropic_api_key.get_secret_value()
        return self.openai_api_key.get_secret_value()


@lru_cache
def get_settings() -> Settings:
    return Settings()
