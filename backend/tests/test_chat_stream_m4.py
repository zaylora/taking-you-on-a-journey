"""M4 端到端：final 携 budget + day_plans 含 hotel/cost；超支触发回退并封顶。"""
import json
import re


def _extract_final(body: str) -> dict:
    m = re.search(r"event: final\r?\ndata: (.+)", body)
    assert m, f"no final event in:\n{body}"
    return json.loads(m.group(1).strip())


def _stub(monkeypatch, *, item_cost, hotel_price, budget_limit, days=2, num_people=2):
    from app.graph.nodes import (clarify as c, dispatch_agent as d, itinerary as it,
                                  accommodation as acc, summarize as s)
    from app.graph.nodes.dispatch import NormalizedReq
    from app.graph.nodes.itinerary import DayPlans, DayPlan, PlanItem, Location, DayWeather, Hotel
    from app.graph.nodes.accommodation import _AccoResult, _HotelForDay
    from app.itinerary import soft_fill as sf
    from tests.conftest import make_fake_build_llm

    async def no_gaps(_state, _config=None):
        return []
    monkeypatch.setattr(c, "_evaluate_gaps", no_gaps)
    monkeypatch.setattr(d, "build_llm", make_fake_build_llm(
        structured=NormalizedReq(city="成都", days=days, num_people=num_people,
                                 preferences={"住宿": "舒适"}, budget=float(budget_limit))))
    dp_days = [DayPlan(day=i + 1, weather=DayWeather(), center=Location(lng=104.0, lat=30.6),
                       items=[PlanItem(type="attraction", name=f"景点{i+1}", poi_id=f"B{i+1}",
                                       location=Location(lng=104.0, lat=30.6),
                                       cost=float(item_cost))])
               for i in range(days)]
    monkeypatch.setattr(sf, "build_llm", make_fake_build_llm(structured=DayPlans(days=dp_days)))
    monkeypatch.setattr(acc, "build_llm", make_fake_build_llm(structured=_AccoResult(assignments=[
        _HotelForDay(day=1, hotel=Hotel(name="如家", poi_id="H1",
                                        location=Location(lng=104.0, lat=30.6),
                                        price=float(hotel_price), level="舒适"))])))
    monkeypatch.setattr(s, "build_llm", make_fake_build_llm(tokens=["行程", "攻略"]))


def test_final_carries_budget_and_hotel_under_budget(client, fake_amap, monkeypatch):
    fake_amap["search_poi"] = [{"name": "景点1", "poi_id": "B1", "lng": 104.0, "lat": 30.6,
                                "address": "", "type": ""}]
    # estimated = 2人 ×(2天×100) + 400 = 800 < 2000
    _stub(monkeypatch, item_cost=100, hotel_price=400, budget_limit=2000)
    body = client.post("/api/chat", json={"message": "成都2天2人预算2000"}).text
    final = _extract_final(body)
    assert "budget" in final and final["budget"]["over"] is False
    assert final["budget"]["estimated"] == 800
    assert final["day_plans"][0]["hotel"]["name"] == "如家"   # 酒店嵌进 day1
    assert "hotel" not in final["day_plans"][1] or final["day_plans"][1]["hotel"] is None
    assert final["day_plans"][0]["items"][0]["cost"] == 100


def test_over_budget_retries_then_caps(client, fake_amap, monkeypatch):
    fake_amap["search_poi"] = [{"name": "景点1", "poi_id": "B1", "lng": 104.0, "lat": 30.6,
                                "address": "", "type": ""}]
    # estimated = 2人 ×(2天×500) + 1000 = 3000 > 1000；每轮重排同样昂贵 → 封顶
    _stub(monkeypatch, item_cost=500, hotel_price=1000, budget_limit=1000)
    body = client.post("/api/chat", json={"message": "成都2天2人预算1000"}).text
    final = _extract_final(body)
    assert final["budget"]["over"] is True
    assert final["budget"]["retry_count"] == 2          # 回退 2 次后封顶
    assert final["budget"]["note"].startswith("已尽力压缩")
