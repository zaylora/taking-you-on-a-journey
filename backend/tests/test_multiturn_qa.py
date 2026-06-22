"""M5 QA turns answer from existing plan without rerunning retrieval or mutating plans."""
import json
import re

def _extract(body: str, event: str) -> dict:
    match = re.search(rf"event: {event}\r?\ndata: (.+)", body)
    assert match, f"no {event} event in:\n{body}"
    return json.loads(match.group(1).strip())


def test_qa_turn_does_not_retrieve_or_modify_plan(client, fake_amap, monkeypatch):
    from app.graph.nodes import accommodation as acc, answer as ans, clarify as c, dispatch_agent as d, itinerary as it, summarize as s
    from app.graph.nodes.accommodation import _AccoResult
    from app.graph.nodes.dispatch import NormalizedReq
    from app.graph.nodes.itinerary import DayPlans, DayPlan, PlanItem, Location, DayWeather
    from app.itinerary import soft_fill as sf
    from tests.conftest import make_fake_build_llm

    async def no_gaps(_state, _config=None):
        return []

    monkeypatch.setattr(c, "_evaluate_gaps", no_gaps)
    monkeypatch.setattr(d, "build_llm", make_fake_build_llm(
        structured=NormalizedReq(city="成都", days=1, num_people=2, budget=4000)))
    monkeypatch.setattr(sf, "build_llm", make_fake_build_llm(structured=DayPlans(days=[
        DayPlan(day=1, weather=DayWeather(), center=Location(lng=104.0, lat=30.6), items=[
            PlanItem(type="attraction", name="武侯祠", poi_id="B1", location=Location(lng=104.0, lat=30.6)),
        ]),
    ])))
    monkeypatch.setattr(acc, "build_llm", make_fake_build_llm(structured=_AccoResult(assignments=[])))
    monkeypatch.setattr(s, "build_llm", make_fake_build_llm(tokens=["已生成", "成都行程"]))

    first = client.post("/api/chat", json={"message": "成都1天2人"}).text
    thread_id = _extract(first, "session")["thread_id"]
    initial = _extract(first, "final")

    async def fail_if_retrieved(*_args, **_kwargs):
        raise AssertionError("QA turn must not call retrieval")

    fake_amap["search_poi"] = []
    import app.tools.amap as amap
    monkeypatch.setattr(amap, "search_poi", fail_if_retrieved)

    monkeypatch.setattr(ans, "build_llm", make_fake_build_llm(tokens=["整体适合老人，但建议放慢节奏。"]))

    second = client.post(
        "/api/chat",
        json={"message": "刚才那个行程适合带老人吗？", "thread_id": thread_id},
    ).text
    final = _extract(second, "final")

    assert final["answer"] == "整体适合老人，但建议放慢节奏。"
    assert final["day_plans"] == initial["day_plans"]
    assert final["plan_version"] == initial["plan_version"]
    assert "event: plan_patch" not in second
