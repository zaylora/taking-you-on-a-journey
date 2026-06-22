import pytest

from app.graph.nodes.refine import refine


def _plan():
    """M6 结构：停靠点含 location，items 已插入交通段（与 itinerary 节点输出对齐）。"""
    from app.graph.nodes.itinerary import insert_transport
    day1_stops = [
        {"type": "attraction", "name": "武侯祠", "poi_id": "B1",
         "location": {"lng": 104.05, "lat": 30.65}},
        {"type": "meal", "name": "陈麻婆", "poi_id": "M1",
         "location": {"lng": 104.06, "lat": 30.66}},
    ]
    day2_stops = [
        {"type": "attraction", "name": "杜甫草堂", "poi_id": "B2",
         "location": {"lng": 104.04, "lat": 30.67}},
    ]
    return [
        {"day": 1, "items": insert_transport(day1_stops)},
        {"day": 2, "items": insert_transport(day2_stops)},
    ]


@pytest.mark.asyncio
async def test_change_meal_swaps_target_day_meal(fake_amap):
    fake_amap["search_poi"] = [{"name": "蜀大侠火锅", "poi_id": "M9", "lng": 104.0, "lat": 30.6}]
    state = {"query": "把第一天晚餐换成火锅", "city": "成都", "day_plans": _plan(), "plan_version": 1,
             "refine_request": {"op": "change_meal", "target_day": 1, "needs_search": True,
                                "constraints": {"keywords": "火锅"}, "needs_budget_recheck": True}}
    out = await refine(state)
    assert out["changed_days"] == [1]
    meals = [i["name"] for i in out["day_plans"][0]["items"] if i["type"] == "meal"]
    assert meals == ["蜀大侠火锅"]
    assert out["day_plans"][1]["items"] == _plan()[1]["items"]   # 第二天不动


@pytest.mark.asyncio
async def test_add_attraction_appends_to_target_day(fake_amap):
    fake_amap["search_poi"] = [{"name": "宽窄巷子", "poi_id": "B9", "lng": 104.0, "lat": 30.6}]
    state = {"query": "第二天加一个景点", "city": "成都", "day_plans": _plan(), "plan_version": 1,
             "refine_request": {"op": "add", "target_day": 2, "needs_search": True,
                                "constraints": {}, "needs_budget_recheck": True}}
    out = await refine(state)
    assert out["changed_days"] == [2]
    # add + rebuild：检查停靠点顺序（items 含交通段，过滤后取名称）
    day2_stops = [i for i in out["day_plans"][1]["items"] if i.get("type") != "transport"]
    assert [i["name"] for i in day2_stops] == ["杜甫草堂", "宽窄巷子"]


@pytest.mark.asyncio
async def test_search_empty_degrades_to_no_change(fake_amap):
    fake_amap["search_poi"] = []   # 检索空 → 不改，changed_days 空
    state = {"query": "第一天晚餐换成日料", "city": "成都", "day_plans": _plan(), "plan_version": 1,
             "refine_request": {"op": "change_meal", "target_day": 1, "needs_search": True,
                                "constraints": {"keywords": "日料"}, "needs_budget_recheck": True}}
    out = await refine(state)
    assert out["changed_days"] == []
    assert out["day_plans"] == _plan()
    assert out["plan_version"] == 1
