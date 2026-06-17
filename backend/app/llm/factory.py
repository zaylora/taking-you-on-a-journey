"""LLM 工厂：用 init_chat_model 构造 ChatModel，默认 OpenAI，支持自定义 base_url。

不同 provider 的 kwargs 不通用，按 provider 分支组装，不把 OpenAI 专属参数盲传给 Anthropic。
"""
from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel

from app.core.config import get_settings


def build_llm(provider: str | None = None, **overrides) -> BaseChatModel:
    s = get_settings()
    provider = provider or s.llm_provider

    if provider == "openai":
        return init_chat_model(
            model=overrides.pop("model", s.openai_model),
            model_provider="openai",
            api_key=s.openai_api_key.get_secret_value() or None,
            base_url=s.openai_base_url,
            temperature=s.temperature,
            **overrides,
        )

    if provider == "anthropic":
        return init_chat_model(
            model=overrides.pop("model", s.anthropic_model),
            model_provider="anthropic",
            api_key=s.anthropic_api_key.get_secret_value() or None,
            base_url=s.anthropic_base_url,
            temperature=s.temperature,
            **overrides,
        )

    raise ValueError(f"unsupported provider: {provider}")
