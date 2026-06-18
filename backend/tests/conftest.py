"""复用打桩件：假 LLM（流式 / 结构化）与假高德 tool。所有测试不依赖真实 Key/网络。"""
import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, AIMessageChunk


class FakeStreamingLLM:
    """模拟 build_llm() 返回的可流式 ChatModel，仅实现 astream。
    注意：此类不继承 BaseChatModel，不会触发 on_chat_model_stream 事件。
    仅用于单节点测试（test_summarize 等），不用于端到端 SSE 流测试。
    """
    def __init__(self, tokens):
        self._tokens = list(tokens)

    async def astream(self, _messages, config=None, **kw):
        for t in self._tokens:
            yield AIMessageChunk(content=t)


class _StructuredRunnable:
    def __init__(self, result):
        self._result = result

    async def ainvoke(self, *_a, **_k):
        return self._result

    def invoke(self, *_a, **_k):
        return self._result


class FakeStructuredLLM:
    """模拟 build_llm()；with_structured_output(Schema) 返回固定结果的 runnable。"""
    def __init__(self, result):
        self._result = result

    def with_structured_output(self, _schema, **_kw):
        return _StructuredRunnable(self._result)


def make_fake_build_llm(*, tokens=None, structured=None):
    """生成可 monkeypatch 进各节点模块的 build_llm 替身。

    - structured 参数：返回 FakeStructuredLLM（with_structured_output 用于 dispatch/itinerary）
    - tokens 参数：返回 GenericFakeChatModel（真正的 BaseChatModel，
      在 astream_events(v2) 中会触发 on_chat_model_stream 事件，供 summarize 节点使用）
    """
    def _factory(*_a, **_k):
        if structured is not None:
            return FakeStructuredLLM(structured)
        # GenericFakeChatModel 每次消费一条消息，必须在 _factory 内重新创建
        text = "".join(tokens or ["占位"])
        return GenericFakeChatModel(messages=iter([AIMessage(content=text)]))
    return _factory


@pytest.fixture
def fake_amap(monkeypatch):
    """把 app.tools.amap 的四个函数 patch 成可控异步返回。返回一个可配置 dict。"""
    import app.tools.amap as amap

    cfg = {
        "geocode": {"lng": 104.06, "lat": 30.65},
        "search_poi": [],
        "get_weather": {"text": "多云", "temp": "24~31℃", "is_rainy": False, "source": "forecast"},
        "plan_route": {},
    }

    async def _geocode(city): return cfg["geocode"]
    async def _search_poi(city, keywords, poi_type="", page_size=20): return cfg["search_poi"]
    async def _get_weather(city): return cfg["get_weather"]
    async def _plan_route(origin, dest, mode="transit"): return cfg["plan_route"]

    monkeypatch.setattr(amap, "geocode", _geocode)
    monkeypatch.setattr(amap, "search_poi", _search_poi)
    monkeypatch.setattr(amap, "get_weather", _get_weather)
    monkeypatch.setattr(amap, "plan_route", _plan_route)
    return cfg


@pytest.fixture
def client(monkeypatch):
    """启动 fail-fast 需要 LLM + 高德 Key：用假 Key 绕过；清 settings 缓存让 lifespan 重读。
    节点级 build_llm/_evaluate_gaps 由各测试自行 patch（运行时解析，无需重建 GRAPH）。
    """
    from fastapi.testclient import TestClient
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")
    monkeypatch.setenv("AMAP_WEB_KEY", "amap-test-fake")
    from app.core.config import get_settings
    get_settings.cache_clear()
    from app.main import app
    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()
