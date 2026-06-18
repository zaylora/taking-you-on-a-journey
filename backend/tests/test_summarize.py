import pytest
from app.graph.nodes import summarize as s_mod


@pytest.mark.asyncio
async def test_summarize_streams_from_day_plans(monkeypatch):
    from tests.conftest import make_fake_build_llm
    monkeypatch.setattr(s_mod, "build_llm",
                        make_fake_build_llm(tokens=["第一天", "：武侯祠"]))
    state = {"day_plans": [{"day": 1, "items": [{"type": "attraction", "name": "武侯祠"}]}],
             "query": "成都3天"}
    out = await s_mod.summarize(state, None)
    assert out["summary"] == "第一天：武侯祠"
    assert out["messages"][0].content == "第一天：武侯祠"
