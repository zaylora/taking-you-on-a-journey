"""M4 端到端：final 携 budget + day_plans 含 hotel/cost；超支触发回退并封顶。"""
import json
import re


def _extract_final(body: str) -> dict:
    m = re.search(r"event: final\r?\ndata: (.+)", body)
    assert m, f"no final event in:\n{body}"
    return json.loads(m.group(1).strip())


def _stub(monkeypatch, *, item_cost, hotel_price, budget_limit, days=2, num_people=2):
    from app.graph.nodes import understand as u, accommodation as acc, render as r
    from app.graph.nodes.dispatch import NormalizedReq
    from app.graph.nodes.itinerary import DayPlans, DayPlan, PlanItem, Location, DayWeather, Hotel
    from app.graph.nodes.accommodation import _AccoResult, _HotelForDay
    from app.itinerary import soft_fill as sf
    from tests.conftest import make_fake_build_llm

    async def no_gaps(_state, _config=None):
        return []
    # understand 直接导入 _evaluate_gaps，须 patch understand 模块属性
    monkeypatch.setattr(u, "_evaluate_gaps", no_gaps)
    # 新链路：understand.build_llm 承载标准化 LLM 调用
    monkeypatch.setattr(u, "build_llm", make_fake_build_llm(
        structured=NormalizedReq(city="成都", days=days, num_people=num_people,
                                 preferences={"住宿": "舒适"}, budget=float(budget_limit))))
    # 新管线：OR-Tools 决定分天/顺序，软填 stub 无法预知。让每一天都带上所有候选景点的
    # poi_id+cost，这样 merge_soft_fields(按 day+poi_id) 在任意分天结果下都能命中合并。
    all_items = [PlanItem(type="attraction", name=f"景点{j+1}", poi_id=f"B{j+1}",
                          location=Location(lng=104.0, lat=30.6), cost=float(item_cost))
                 for j in range(days)]
    dp_days = [DayPlan(day=i + 1, weather=DayWeather(), center=Location(lng=104.0, lat=30.6),
                       items=list(all_items))
               for i in range(days)]
    monkeypatch.setattr(sf, "build_llm", make_fake_build_llm(structured=DayPlans(days=dp_days)))
    monkeypatch.setattr(acc, "build_llm", make_fake_build_llm(structured=_AccoResult(assignments=[
        _HotelForDay(day=1, hotel=Hotel(name="如家", poi_id="H1",
                                        location=Location(lng=104.0, lat=30.6),
                                        price=float(hotel_price), level="舒适"))])))
    # 新链路：token 由 render 节点冒泡
    monkeypatch.setattr(r, "build_llm", make_fake_build_llm(tokens=["行程", "攻略"]))


def test_final_carries_budget_and_hotel_under_budget(client, fake_amap, monkeypatch):
    # 新管线：景点来自 search_poi（算法建骨架），2 景点分 2 天；软填 stub poi_id 须对齐
    fake_amap["search_poi"] = [
        {"name": "景点1", "poi_id": "B1", "lng": 104.0, "lat": 30.6, "address": "", "type": "", "rating": 4.5},
        {"name": "景点2", "poi_id": "B2", "lng": 104.2, "lat": 30.8, "address": "", "type": "", "rating": 4.0},
    ]
    # 每景点人均 100、2 人、酒店 400(仅 day1)。estimated 由新管线实际合并的 cost 决定
    _stub(monkeypatch, item_cost=100, hotel_price=400, budget_limit=2000)
    body = client.post("/api/chat", json={"message": "成都2天2人预算2000"}).text
    final = _extract_final(body)
    assert "budget" in final and final["budget"]["over"] is False
    assert final["budget"]["estimated"] <= 2000             # 在预算内
    assert final["budget"]["estimated"] > 0                  # 景点 cost 确有合并进来
    assert final["day_plans"][0]["hotel"]["name"] == "如家"   # 酒店嵌进 day1
    # 两个景点的 cost 都被软填合并（per-item 100）
    item_costs = [it["cost"] for day in final["day_plans"]
                  for it in day["items"] if it["type"] == "attraction"]
    assert all(c == 100 for c in item_costs) and len(item_costs) == 2


def test_over_budget_retries_then_caps(client, fake_amap, monkeypatch):
    fake_amap["search_poi"] = [{"name": "景点1", "poi_id": "B1", "lng": 104.0, "lat": 30.6,
                                "address": "", "type": ""}]
    # estimated = 2人 ×(2天×500) + 1000 = 3000 > 1000；每轮重排同样昂贵 → 封顶
    _stub(monkeypatch, item_cost=500, hotel_price=1000, budget_limit=1000)
    body = client.post("/api/chat", json={"message": "成都2天2人预算1000"}).text
    final = _extract_final(body)
    assert final["budget"]["over"] is True
    # 新链路：6节点直线图无超支回退循环，apply 只调一次 compute_budget（retry_count 从0开始+1=1）
    # 旧链路 route_after_budget 条件边回退两次 → retry_count=2；新链路正确行为 == 1
    assert final["budget"]["retry_count"] == 1
