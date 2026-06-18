from app.core.config import get_settings
from app.llm.factory import build_llm


def test_openai_llm_disables_streaming_for_tool_calling_by_default(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")
    get_settings.cache_clear()

    llm = build_llm()

    assert llm.disable_streaming == "tool_calling"
    get_settings.cache_clear()


def test_explicit_disable_streaming_override_is_respected(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")
    get_settings.cache_clear()

    llm = build_llm(disable_streaming=False)

    assert llm.disable_streaming is False
    get_settings.cache_clear()
