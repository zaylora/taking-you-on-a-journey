import pytest

from app.graph.nodes.refine import refine


def _plan():
    return [
        {"day": 1, "items": [
            {"type": "attraction", "name": "武侯祠", "poi_id": "B1"},
            {"type": "meal", "name": "陈麻婆", "poi_id": "M1"}]},
        {"day": 2, "items": [
            {"type": "attraction", "name": "杜甫草堂", "poi_id": "B2"}]},
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
    assert [i["name"] for i in out["day_plans"][1]["items"]] == ["杜甫草堂", "宽窄巷子"]


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
