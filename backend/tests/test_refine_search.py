from app.graph.nodes.refine import refine
from app.graph.nodes.itinerary import insert_transport


def _plan():
    day1 = [
        {"type": "attraction", "name": "武侯祠", "poi_id": "B1", "location": {"lng": 104.05, "lat": 30.65}},
        {"type": "meal", "name": "陈麻婆", "poi_id": "M1", "location": {"lng": 104.06, "lat": 30.66}},
    ]
    return [{"day": 1, "items": insert_transport(day1), "center": {"lng": 104.05, "lat": 30.65}}]


async def test_add_poi_appends_searched_attraction(fake_amap):
    fake_amap["search_around"] = [
        {"name": "杜甫草堂", "poi_id": "NEW1", "lng": 104.04, "lat": 30.67, "type": "风景名胜"}]
    state = {"day_plans": _plan(), "plan_version": 1, "city": "成都",
             "refine_request": {"operations": [
                 {"op": "add_poi", "day": 1, "query": "草堂", "kind": "attraction"}]}}
    out = await refine(state)
    names = [i["name"] for i in out["day_plans"][0]["items"] if i.get("type") != "transport"]
    assert "杜甫草堂" in names
    assert out["changed_days"] == [1]


async def test_replace_poi_swaps_meal_by_name(fake_amap):
    fake_amap["search_around"] = [
        {"name": "蜀大侠火锅", "poi_id": "HOT1", "lng": 104.06, "lat": 30.66, "type": "餐饮"}]
    state = {"day_plans": _plan(), "plan_version": 1, "city": "成都",
             "refine_request": {"operations": [
                 {"op": "replace_poi", "day": 1, "kind": "meal", "query": "火锅",
                  "selector": {"by": "name", "name": "陈麻婆"}}]}}
    out = await refine(state)
    names = [i["name"] for i in out["day_plans"][0]["items"] if i.get("type") != "transport"]
    assert "蜀大侠火锅" in names and "陈麻婆" not in names


async def test_add_poi_empty_search_is_skipped(fake_amap):
    fake_amap["search_around"] = []   # 检索为空
    state = {"day_plans": _plan(), "plan_version": 1, "city": "成都",
             "refine_request": {"operations": [{"op": "add_poi", "day": 1, "query": "无结果"}]}}
    out = await refine(state)
    assert out["changed_days"] == []
    assert out["day_plans"] == _plan()
    assert out["refine_notes"]["skipped"]
