"""M5 replan turns clear stale plan state while preserving the conversation thread."""
import json
import re


def _extract(body: str, event: str) -> dict:
    match = re.search(rf"event: {event}\r?\ndata: (.+)", body)
    assert match, f"no {event} event in:\n{body}"
    return json.loads(match.group(1).strip())


def test_replan_replaces_old_city_and_day_plans(client, fake_amap, monkeypatch):
    from app.graph.nodes import accommodation as acc, understand as u, render as r
    from app.itinerary import soft_fill as sf
    from app.graph.nodes.accommodation import _AccoResult
    from app.graph.nodes.dispatch import NormalizedReq
    from app.graph.nodes.itinerary import DayPlans, DayPlan, PlanItem, Location, DayWeather
    from tests.conftest import make_fake_build_llm

    async def no_gaps(_state, _config=None):
        return []

    # understand 直接导入 _evaluate_gaps，须 patch understand 模块属性
    monkeypatch.setattr(u, "_evaluate_gaps", no_gaps)
    reqs = iter([
        NormalizedReq(city="成都", days=1, num_people=1),
        NormalizedReq(city="上海", days=2, num_people=1),
    ])
    plans = iter([
        DayPlans(days=[DayPlan(day=1, weather=DayWeather(), center=Location(lng=104.0, lat=30.6), items=[
            PlanItem(type="attraction", name="武侯祠", poi_id="C1", location=Location(lng=104.0, lat=30.6)),
        ])]),
        DayPlans(days=[
            DayPlan(day=1, weather=DayWeather(), center=Location(lng=121.4, lat=31.2), items=[
                PlanItem(type="attraction", name="外滩", poi_id="S1", location=Location(lng=121.4, lat=31.2)),
            ]),
            DayPlan(day=2, weather=DayWeather(), center=Location(lng=121.5, lat=31.2), items=[
                PlanItem(type="attraction", name="上海博物馆", poi_id="S2", location=Location(lng=121.5, lat=31.2)),
            ]),
        ]),
    ])

    def dispatch_llm(*_args, **_kwargs):
        return make_fake_build_llm(structured=next(reqs))()

    def itinerary_llm(*_args, **_kwargs):
        return make_fake_build_llm(structured=next(plans))()

    # 新链路：understand.build_llm 承载标准化 LLM 调用（每轮迭代 next(reqs)）
    monkeypatch.setattr(u, "build_llm", dispatch_llm)
    monkeypatch.setattr(sf, "build_llm", itinerary_llm)
    monkeypatch.setattr(acc, "build_llm", make_fake_build_llm(structured=_AccoResult(assignments=[])))
    # 新链路：token 由 render 节点冒泡
    monkeypatch.setattr(r, "build_llm", make_fake_build_llm(tokens=["攻略"]))

    # 新节点：景点来自算法（amap.search_poi），LLM 只填软字段。
    # 第一轮：成都武侯祠；第二轮：上海外滩+上海博物馆
    fake_amap["search_poi"] = [
        {"name": "武侯祠", "poi_id": "C1", "lng": 104.0, "lat": 30.6},
    ]
    first = client.post("/api/chat", json={"message": "成都1天"}).text
    thread_id = _extract(first, "session")["thread_id"]
    first_day_plans = _extract(first, "final")["day_plans"]
    assert len(first_day_plans) == 1
    names_first = [it["name"] for it in first_day_plans[0]["items"] if it["type"] == "attraction"]
    assert "武侯祠" in names_first

    # 第二轮：切换到上海2天
    fake_amap["search_poi"] = [
        {"name": "外滩", "poi_id": "S1", "lng": 121.4, "lat": 31.2},
        {"name": "上海博物馆", "poi_id": "S2", "lng": 121.5, "lat": 31.2},
    ]
    second = client.post(
        "/api/chat",
        json={"message": "重新做一个上海2天行程", "thread_id": thread_id},
    ).text
    final = _extract(second, "final")

    assert final["plan_version"] == 2
    assert [day["day"] for day in final["day_plans"]] == [1, 2]
    names = [item["name"] for day in final["day_plans"] for item in day["items"]
             if item["type"] == "attraction"]
    assert "外滩" in names
    assert "上海博物馆" in names
    assert "武侯祠" not in names
