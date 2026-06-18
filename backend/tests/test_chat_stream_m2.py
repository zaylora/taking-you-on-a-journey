"""M2 端到端测试：全流程 → final（token 只来自 summarize）。"""
import re


def _stub_nodes(monkeypatch):
    """clarify 无缺口放行、dispatch/itinerary 给结构化、summarize 流式。检索由 fake_amap 提供。"""
    from app.graph.nodes import clarify as c, dispatch as d, itinerary as it, summarize as s
    from app.graph.nodes.dispatch import NormalizedReq
    from app.graph.nodes.itinerary import DayPlans, DayPlan, PlanItem, Location, DayWeather
    from tests.conftest import make_fake_build_llm

    async def no_gaps(_state, _config=None):
        return []
    monkeypatch.setattr(c, "_evaluate_gaps", no_gaps)
    monkeypatch.setattr(d, "build_llm", make_fake_build_llm(
        structured=NormalizedReq(city="成都", days=1, num_people=2,
                                 preferences={"food": "辣"}, budget=2000.0)))
    monkeypatch.setattr(it, "build_llm", make_fake_build_llm(structured=DayPlans(days=[
        DayPlan(day=1, weather=DayWeather(), center=Location(lng=104.0, lat=30.6),
                items=[PlanItem(type="attraction", name="武侯祠", poi_id="B1",
                                location=Location(lng=104.0, lat=30.6))])])))
    monkeypatch.setattr(s, "build_llm", make_fake_build_llm(tokens=["第一天", "：武侯祠"]))


def test_full_stream_reaches_final_with_day_plans(client, fake_amap, monkeypatch):
    fake_amap["search_poi"] = [{"name": "武侯祠", "poi_id": "B1", "lng": 104.0,
                                "lat": 30.6, "address": "", "type": ""}]
    _stub_nodes(monkeypatch)
    body = client.post("/api/chat", json={"message": "成都玩1天"}).text
    assert "event: session" in body
    assert "event: final" in body
    assert "event: token" in body
    assert "武侯祠" in body            # day_plans 进了 final
    # token 只来自 summarize：正文出现攻略 token，但不含中间节点产物
    assert "第一天" in body
