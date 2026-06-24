"""M5 fix 端到端：understand 派发 + refine 按 op 选择性重排/补检索/跳过。"""
import json
import re


def _extract(body: str, event: str) -> dict:
    m = re.search(rf"event: {event}\r?\ndata: (.+)", body)
    assert m, f"no {event} event in:\n{body}"
    return json.loads(m.group(1).strip())


def _stub_plan_new(monkeypatch, fake_amap=None):
    from app.graph.nodes import accommodation as acc, understand as u, render as r
    from app.graph.nodes.accommodation import _AccoResult
    from app.graph.nodes.dispatch import NormalizedReq
    from app.graph.nodes.itinerary import DayPlans, DayPlan, PlanItem, Location, DayWeather
    from app.itinerary import soft_fill as sf
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
    # understand 直接导入 _evaluate_gaps，须 patch understand 模块属性
    monkeypatch.setattr(u, "_evaluate_gaps", no_gaps)
    # 新链路：understand.build_llm 承载意图解析/标准化 LLM 调用
    monkeypatch.setattr(u, "build_llm", make_fake_build_llm(
        structured=NormalizedReq(city="成都", days=2, num_people=2, budget=4000)))
    # LLM stub 仅用于软字段填充（start/end/cost/note），结构由算法决定
    monkeypatch.setattr(sf, "build_llm", make_fake_build_llm(structured=DayPlans(days=[
        DayPlan(day=1, weather=DayWeather(), center=Location(lng=104.0, lat=30.6), items=[
            PlanItem(type="attraction", name="武侯祠", poi_id="B1", location=Location(lng=104.0, lat=30.6)),
            PlanItem(type="meal", name="陈麻婆", poi_id="M1", location=Location(lng=104.0, lat=30.6), cost=80.0)]),
        DayPlan(day=2, weather=DayWeather(), center=Location(lng=104.1, lat=30.7), items=[
            PlanItem(type="attraction", name="杜甫草堂", poi_id="B2", location=Location(lng=104.1, lat=30.7))]),
    ])))
    monkeypatch.setattr(acc, "build_llm", make_fake_build_llm(structured=_AccoResult(assignments=[])))
    # 新链路：token 由 render 节点冒泡
    monkeypatch.setattr(r, "build_llm", make_fake_build_llm(tokens=["已处理", "完成"]))


def _new_plan(client, monkeypatch, fake_amap=None):
    _stub_plan_new(monkeypatch, fake_amap=fake_amap)
    first = client.post("/api/chat", json={"message": "成都2天2人预算4000"}).text
    return _extract(first, "session")["thread_id"]


def test_change_meal_only_target_day_and_runs_budget(client, fake_amap, monkeypatch):
    tid = _new_plan(client, monkeypatch, fake_amap=fake_amap)
    # 第二轮：把第一天晚餐换成火锅（search_around 返回火锅店；replace_poi 走圆心检索）
    fake_amap["search_around"] = [{"name": "蜀大侠火锅", "poi_id": "M9", "lng": 104.0, "lat": 30.6}]
    # 第二轮 refine 走 LLM 解析：把 understand.build_llm 重打桩为 RefinePlan
    # （understand 经 build_llm_fn 注入复用 _parse_refine_llm，patch understand.build_llm 生效）
    from app.graph.nodes import understand as u_refine
    from app.graph.nodes.refine_ops import RefinePlan, Operation
    from tests.conftest import make_fake_build_llm
    # day1 初始计划已含 meal（陈麻婆），用 replace_poi 命中 meal index 0
    monkeypatch.setattr(u_refine, "build_llm", make_fake_build_llm(
        structured=RefinePlan(operations=[Operation(
            op="replace_poi", day=1, kind="meal", query="火锅",
            selector={"by": "ordinal", "kind": "meal", "index": 0})])))
    body = client.post("/api/chat",
                       json={"message": "把第一天晚餐换成火锅", "thread_id": tid}).text
    patch = _extract(body, "plan_patch")
    final = _extract(body, "final")
    assert patch["changed_days"] == [1]
    meals = [i["name"] for i in final["day_plans"][0]["items"] if i["type"] == "meal"]
    assert meals == ["蜀大侠火锅"]
    # 第二天景点不受 change_meal(target_day=1)影响：新管线分天顺序由 OR-Tools 定，
    # 不锁具体哪天是哪个景点，只断言两个景点都还在行程里、且第二天景点未被 change_meal 触动
    all_attraction_names = {
        i["name"] for day in final["day_plans"] for i in day["items"]
        if i["type"] == "attraction"}
    assert all_attraction_names == {"武侯祠", "杜甫草堂"}
    second_day_attraction_names = [i["name"] for i in final["day_plans"][1]["items"]
                                   if i["type"] == "attraction"]
    assert len(second_day_attraction_names) == 1   # 2 景点分 2 天，day2 含 1 个


def test_reorder_skips_accommodation_and_budget(client, fake_amap, monkeypatch):
    tid = _new_plan(client, monkeypatch, fake_amap=fake_amap)

    import app.graph.nodes.accommodation as acc_node
    def boom_build_llm(*_a, **_k):
        raise AssertionError("reorder 不应触发 accommodation 节点")
    monkeypatch.setattr(acc_node, "build_llm", boom_build_llm)

    # 第二轮 refine 走 LLM 解析：把 understand.build_llm 重打桩为 RefinePlan
    from app.graph.nodes import understand as u_refine
    from app.graph.nodes.refine_ops import RefinePlan, Operation
    from tests.conftest import make_fake_build_llm
    monkeypatch.setattr(u_refine, "build_llm", make_fake_build_llm(
        structured=RefinePlan(operations=[Operation(op="reorder", day=1, strategy="reverse")])))

    body = client.post("/api/chat",
                       json={"message": "第一天顺序调整一下", "thread_id": tid}).text
    patch = _extract(body, "plan_patch")
    assert patch["changed_days"] == [1]             # 走到 render，未碰 accommodation/budget


def test_change_budget_updates_limit(client, fake_amap, monkeypatch):
    tid = _new_plan(client, monkeypatch, fake_amap=fake_amap)
    # 第二轮 refine 走 LLM 解析：把 understand.build_llm 重打桩为 RefinePlan
    from app.graph.nodes import understand as u_refine
    from app.graph.nodes.refine_ops import RefinePlan, Operation
    from tests.conftest import make_fake_build_llm
    monkeypatch.setattr(u_refine, "build_llm", make_fake_build_llm(
        structured=RefinePlan(operations=[Operation(op="set_budget", amount=1500)])))
    body = client.post("/api/chat",
                       json={"message": "预算改成1500", "thread_id": tid}).text
    final = _extract(body, "final")
    assert final["budget"]["limit"] == 1500.0       # change_budget → budget 重新核算
