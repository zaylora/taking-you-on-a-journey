from app.core.config import Settings


def test_tavily_api_key_defaults_empty():
    s = Settings(_env_file=None)
    assert s.tavily_api_key.get_secret_value() == ""


def test_tavily_api_key_is_secret():
    s = Settings(tavily_api_key="tvly-xxx")
    # SecretStr 不应在 repr 中明文泄露
    assert "tvly-xxx" not in repr(s.tavily_api_key)
    assert s.tavily_api_key.get_secret_value() == "tvly-xxx"


def test_sklearn_and_tavily_importable():
    import sklearn.cluster  # noqa: F401
    from langchain_tavily import TavilySearch  # noqa: F401
