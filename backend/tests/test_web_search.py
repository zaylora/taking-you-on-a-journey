from app.tools import web_search
from app.core import config


def _settings(key):
    return config.Settings(tavily_api_key=key, _env_file=None)


def test_returns_none_when_no_key(monkeypatch):
    monkeypatch.setattr(web_search, "get_settings", lambda: _settings(""))
    assert web_search.build_tavily_tool() is None


def test_returns_tool_when_key_present(monkeypatch):
    monkeypatch.setattr(web_search, "get_settings", lambda: _settings("tvly-x"))
    tool = web_search.build_tavily_tool()
    assert tool is not None
    assert hasattr(tool, "name")  # LangChain 工具具备 name 属性
