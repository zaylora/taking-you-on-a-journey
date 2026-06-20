"""M5 replan turns clear stale plan state while preserving the conversation thread."""
import json
import re


def _extract(body: str, event: str) -> dict:
    match = re.search(rf"event: {event}\r?\ndata: (.+)", body)
    assert match, f"no {event} event in:\n{body}"
    return json.loads(match.group(1).strip())


def test_replan_replaces_old_city_and_day_plans(client, fake_amap, monkeypatch):
    from app.graph.nodes import accommodation as acc, clarify as c, dispatch_agent as d, itinerary as it, summarize as s
    from app.graph.nodes.accommodation import _AccoResult
    from app.graph.nodes.dispatch import NormalizedReq
    from app.graph.nodes.itinerary import DayPlans, DayPlan, PlanItem, Location, DayWeather
    from tests.conftest import make_fake_build_llm

    async def no_gaps(_state, _config=None):
        return []

    monkeypatch.setattr(c, "_evaluate_gaps", no_gaps)
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

    monkeypatch.setattr(d, "build_llm", dispatch_llm)
    monkeypatch.setattr(it, "build_llm", itinerary_llm)
    monkeypatch.setattr(acc, "build_llm", make_fake_build_llm(structured=_AccoResult(assignments=[])))
    monkeypatch.setattr(s, "build_llm", make_fake_build_llm(tokens=["攻略"]))

    first = client.post("/api/chat", json={"message": "成都1天"}).text
    thread_id = _extract(first, "session")["thread_id"]
    assert _extract(first, "final")["day_plans"][0]["items"][0]["name"] == "武侯祠"

    second = client.post(
        "/api/chat",
        json={"message": "重新做一个上海2天行程", "thread_id": thread_id},
    ).text
    final = _extract(second, "final")

    assert final["plan_version"] == 2
    assert [day["day"] for day in final["day_plans"]] == [1, 2]
    names = [item["name"] for day in final["day_plans"] for item in day["items"]]
    assert "外滩" in names
    assert "上海博物馆" in names
    assert "武侯祠" not in names
