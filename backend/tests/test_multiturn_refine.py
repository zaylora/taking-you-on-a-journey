"""M5 true multiturn refine behavior."""
import json
import re


def _extract(body: str, event: str) -> dict:
    match = re.search(rf"event: {event}\r?\ndata: (.+)", body)
    assert match, f"no {event} event in:\n{body}"
    return json.loads(match.group(1).strip())


def _stub_initial_plan(monkeypatch):
    from app.graph.nodes import accommodation as acc, clarify as c, dispatch_agent as d, itinerary as it, summarize as s
    from app.graph.nodes.accommodation import _AccoResult
    from app.graph.nodes.dispatch import NormalizedReq
    from app.graph.nodes.itinerary import DayPlans, DayPlan, PlanItem, Location, DayWeather
    from app.itinerary import soft_fill as sf
    from tests.conftest import make_fake_build_llm

    async def no_gaps(_state, _config=None):
        return []

    monkeypatch.setattr(c, "_evaluate_gaps", no_gaps)
    monkeypatch.setattr(d, "build_llm", make_fake_build_llm(
        structured=NormalizedReq(city="成都", days=2, num_people=2, budget=4000)))
    monkeypatch.setattr(sf, "build_llm", make_fake_build_llm(structured=DayPlans(days=[
        DayPlan(day=1, weather=DayWeather(), center=Location(lng=104.0, lat=30.6), items=[
            PlanItem(type="attraction", name="武侯祠", poi_id="B1", location=Location(lng=104.0, lat=30.6)),
        ]),
        DayPlan(day=2, weather=DayWeather(), center=Location(lng=104.1, lat=30.7), items=[
            PlanItem(type="attraction", name="杜甫草堂", poi_id="B2", location=Location(lng=104.1, lat=30.7)),
            PlanItem(type="attraction", name="金沙遗址", poi_id="B3", location=Location(lng=104.2, lat=30.8)),
        ]),
    ])))
    monkeypatch.setattr(acc, "build_llm", make_fake_build_llm(structured=_AccoResult(assignments=[])))
    monkeypatch.setattr(s, "build_llm", make_fake_build_llm(tokens=["已生成", "成都行程"]))


def test_second_turn_relaxes_only_target_day(client, fake_amap, monkeypatch):
    # 新节点：景点来自算法（amap.search_poi），LLM 只填软字段。
    # 配置三个景点：算法 cluster_by_day(3景点, 2天) → 第1天1个、第2天2个
    fake_amap["search_poi"] = [
        {"name": "武侯祠", "poi_id": "B1", "lng": 104.0, "lat": 30.6},
        {"name": "杜甫草堂", "poi_id": "B2", "lng": 104.1, "lat": 30.7},
        {"name": "金沙遗址", "poi_id": "B3", "lng": 104.2, "lat": 30.8},
    ]
    _stub_initial_plan(monkeypatch)

    first = client.post("/api/chat", json={"message": "成都2天2人预算4000"}).text
    thread_id = _extract(first, "session")["thread_id"]
    initial = _extract(first, "final")
    # 新节点：景点来自算法 cluster_by_day(3景点, 2天) → divmod(3,2)=(1,1)
    # 前 1 天多 1 个 → day1 得 2 个景点，day2 得 1 个景点
    assert len(initial["day_plans"]) == 2
    attraction_counts = [
        sum(1 for it in day["items"] if it["type"] == "attraction")
        for day in initial["day_plans"]
    ]
    assert attraction_counts == [2, 1]

    second = client.post(
        "/api/chat",
        json={"message": "第二天太赶了，少安排一个景点", "thread_id": thread_id},
    ).text
    final = _extract(second, "final")
    patch = _extract(second, "plan_patch")

    assert final["plan_version"] == 2
    assert patch == {"plan_version": 2, "changed_days": [2]}
    # 第一天不动（refine 只改 target_day=2）
    assert final["day_plans"][0]["items"] == initial["day_plans"][0]["items"]
    # 第二天被 relax（items 减少 1 个）
    assert len(final["day_plans"][1]["items"]) < len(initial["day_plans"][1]["items"])
