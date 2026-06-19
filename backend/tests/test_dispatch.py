import pytest
from app.graph.nodes import dispatch as d_mod
from app.graph.nodes.dispatch import NormalizedReq


@pytest.mark.asyncio
async def test_dispatch_fills_top_level_fields(monkeypatch):
    from tests.conftest import make_fake_build_llm
    req = NormalizedReq(city="成都", start_date="2026-07-01", days=3, num_people=2,
                        preferences={"food": "辣"}, budget=2000.0)
    monkeypatch.setattr(d_mod, "build_llm", make_fake_build_llm(structured=req))
    out = await d_mod.dispatch({"query": "成都3天2人爱吃辣预算2000", "clarify_history": []}, None)
    assert out["city"] == "成都" and out["days"] == 3 and out["num_people"] == 2
    assert out["normalized_req"]["city"] == "成都"
    assert "messages" not in out  # M5: memory_update 统一写轻量消息历史
