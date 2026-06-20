"""M5 fix 端到端：单一 dispatch_agent 派发 + refine 按 op 选择性重排/补检索/跳过。"""
import json
import re


def _extract(body: str, event: str) -> dict:
    m = re.search(rf"event: {event}\r?\ndata: (.+)", body)
    assert m, f"no {event} event in:\n{body}"
    return json.loads(m.group(1).strip())


def _stub_plan_new(monkeypatch, fake_amap=None):
    from app.graph.nodes import accommodation as acc, clarify as c, dispatch_agent as d, itinerary as it, summarize as s
    from app.graph.nodes.accommodation import _AccoResult
    from app.graph.nodes.dispatch import NormalizedReq
    from app.graph.nodes.itinerary import DayPlans, DayPlan, PlanItem, Location, DayWeather
    from tests.conftest import make_fake_build_llm

    # 新节点：景点来自算法（amap.search_poi），LLM 只填软字段。
    # 配置两个景点使算法分配到两天；search_around 使用 fake_amap 的空默认，餐厅来自城市池。
    if fake_amap is not None:
        fake_amap["search_poi"] = [
            {"name": "武侯祠", "poi_id": "B1", "lng": 104.0, "lat": 30.6},
            {"name": "杜甫草堂", "poi_id": "B2", "lng": 104.1, "lat": 30.7},
        ]

    async def no_gaps(_state, _config=None):
        return []
    monkeypatch.setattr(c, "_evaluate_gaps", no_gaps)
    monkeypatch.setattr(d, "build_llm", make_fake_build_llm(
        structured=NormalizedReq(city="成都", days=2, num_people=2, budget=4000)))
    # LLM stub 仅用于软字段填充（start/end/cost/note），结构由算法决定
    monkeypatch.setattr(it, "build_llm", make_fake_build_llm(structured=DayPlans(days=[
        DayPlan(day=1, weather=DayWeather(), center=Location(lng=104.0, lat=30.6), items=[
            PlanItem(type="attraction", name="武侯祠", poi_id="B1", location=Location(lng=104.0, lat=30.6)),
            PlanItem(type="meal", name="陈麻婆", poi_id="M1", location=Location(lng=104.0, lat=30.6), cost=80.0)]),
        DayPlan(day=2, weather=DayWeather(), center=Location(lng=104.1, lat=30.7), items=[
            PlanItem(type="attraction", name="杜甫草堂", poi_id="B2", location=Location(lng=104.1, lat=30.7))]),
    ])))
    monkeypatch.setattr(acc, "build_llm", make_fake_build_llm(structured=_AccoResult(assignments=[])))
    monkeypatch.setattr(s, "build_llm", make_fake_build_llm(tokens=["已处理", "完成"]))


def _new_plan(client, monkeypatch, fake_amap=None):
    _stub_plan_new(monkeypatch, fake_amap=fake_amap)
    first = client.post("/api/chat", json={"message": "成都2天2人预算4000"}).text
    return _extract(first, "session")["thread_id"]


def test_change_meal_only_target_day_and_runs_budget(client, fake_amap, monkeypatch):
    tid = _new_plan(client, monkeypatch, fake_amap=fake_amap)
    # 第二轮：把第一天晚餐换成火锅（search_poi 返回火锅店）
    fake_amap["search_poi"] = [{"name": "蜀大侠火锅", "poi_id": "M9", "lng": 104.0, "lat": 30.6}]
    body = client.post("/api/chat",
                       json={"message": "把第一天晚餐换成火锅", "thread_id": tid}).text
    patch = _extract(body, "plan_patch")
    final = _extract(body, "final")
    assert patch["changed_days"] == [1]
    meals = [i["name"] for i in final["day_plans"][0]["items"] if i["type"] == "meal"]
    assert meals == ["蜀大侠火锅"]
    # 第二天不动：新节点下第2天 items 由算法产生，cluster_by_day(2,2) → day2 只含杜甫草堂
    second_day_attraction_names = [i["name"] for i in final["day_plans"][1]["items"]
                                   if i["type"] == "attraction"]
    assert second_day_attraction_names == ["杜甫草堂"]


def test_reorder_skips_accommodation_and_budget(client, fake_amap, monkeypatch):
    tid = _new_plan(client, monkeypatch, fake_amap=fake_amap)

    import app.graph.nodes.accommodation as acc_node
    def boom_build_llm(*_a, **_k):
        raise AssertionError("reorder 不应触发 accommodation 节点")
    monkeypatch.setattr(acc_node, "build_llm", boom_build_llm)

    body = client.post("/api/chat",
                       json={"message": "第一天顺序调整一下", "thread_id": tid}).text
    patch = _extract(body, "plan_patch")
    assert patch["changed_days"] == [1]             # 走到 summarize，未碰 accommodation/budget


def test_change_budget_updates_limit(client, fake_amap, monkeypatch):
    tid = _new_plan(client, monkeypatch, fake_amap=fake_amap)
    body = client.post("/api/chat",
                       json={"message": "预算改成1500", "thread_id": tid}).text
    final = _extract(body, "final")
    assert final["budget"]["limit"] == 1500.0       # change_budget → budget 重新核算
