from app.graph.nodes.refine import refine
from app.graph.nodes.itinerary import insert_transport

# 黄埔区参考坐标（经度 > 113.45）
HUANGPU = {"lng": 113.46, "lat": 23.10}


def _gz_plan():
    # 第一天在广州市区（经度约 113.27）
    day1 = [
        {"type": "attraction", "name": "越秀公园", "poi_id": "G1", "location": {"lng": 113.27, "lat": 23.13}},
        {"type": "attraction", "name": "陈家祠", "poi_id": "G2", "location": {"lng": 113.24, "lat": 23.13}},
    ]
    return [{"day": 1, "items": insert_transport(day1), "center": {"lng": 113.276, "lat": 23.1154}}]


async def test_set_region_moves_center_and_researches(fake_amap):
    fake_amap["geocode"] = HUANGPU
    fake_amap["search_around"] = [
        {"name": "黄埔军校旧址", "poi_id": "H1", "lng": 113.47, "lat": 23.09, "type": "风景名胜"},
        {"name": "南海神庙", "poi_id": "H2", "lng": 113.46, "lat": 23.11, "type": "风景名胜"},
    ]
    state = {"day_plans": _gz_plan(), "plan_version": 4, "city": "广州",
             "refine_request": {"operations": [{"op": "set_region", "day": 1, "area": "黄埔"}]}}
    out = await refine(state)
    day1 = out["day_plans"][0]
    # center 迁到黄埔（经度 > 113.45），不再是市区 113.27
    assert day1["center"]["lng"] > 113.45
    # 景点已换成黄埔的新检索结果
    names = [i["name"] for i in day1["items"] if i.get("type") == "attraction"]
    assert "黄埔军校旧址" in names and "越秀公园" not in names
    assert out["changed_days"] == [1]
    assert out["plan_version"] == 5
    assert out["refine_request"]["needs_budget_recheck"] is True


async def test_set_region_geocode_fail_is_skipped(fake_amap):
    fake_amap["geocode"] = {}   # 定位失败
    state = {"day_plans": _gz_plan(), "plan_version": 4, "city": "广州",
             "refine_request": {"operations": [{"op": "set_region", "day": 1, "area": "不存在区"}]}}
    out = await refine(state)
    assert out["changed_days"] == []
    assert out["day_plans"] == _gz_plan()
    assert out["refine_notes"]["skipped"]


async def test_set_region_compound_with_pace(fake_amap):
    fake_amap["geocode"] = HUANGPU
    fake_amap["search_around"] = [
        {"name": f"黄埔景点{i}", "poi_id": f"H{i}", "lng": 113.46 + i * 0.001, "lat": 23.10, "type": "风景名胜"}
        for i in range(5)
    ]
    state = {"day_plans": _gz_plan(), "plan_version": 4, "city": "广州",
             "refine_request": {"operations": [
                 {"op": "set_region", "day": 1, "area": "黄埔"},
                 {"op": "set_pace", "day": 1, "direction": "relax"}]}}
    out = await refine(state)
    assert out["changed_days"] == [1]
    assert len(out["refine_notes"]["applied"]) == 2   # 两步都生效
