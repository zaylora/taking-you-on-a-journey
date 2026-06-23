from app.graph.nodes.refine import refine, _find_day, _finalize_day
from app.graph.nodes.itinerary import insert_transport


def _plan():
    day1 = [
        {"type": "attraction", "name": "武侯祠", "poi_id": "B1", "location": {"lng": 104.05, "lat": 30.65}},
        {"type": "meal", "name": "陈麻婆", "poi_id": "M1", "location": {"lng": 104.06, "lat": 30.66}},
    ]
    day2 = [
        {"type": "attraction", "name": "杜甫草堂", "poi_id": "B2", "location": {"lng": 104.04, "lat": 30.67}},
        {"type": "attraction", "name": "金沙遗址", "poi_id": "B3", "location": {"lng": 104.03, "lat": 30.68}},
    ]
    return [
        {"day": 1, "items": insert_transport(day1), "center": {"lng": 104.055, "lat": 30.655}},
        {"day": 2, "items": insert_transport(day2), "center": {"lng": 104.035, "lat": 30.675}},
    ]


def test_find_day():
    assert _find_day(_plan(), 2) == 1
    assert _find_day(_plan(), 9) is None
    assert _find_day(_plan(), None) is None


def test_finalize_day_inserts_transport_and_center():
    dp = _finalize_day({"day": 1, "items": [
        {"type": "attraction", "name": "A", "location": {"lng": 104.0, "lat": 30.0}},
        {"type": "attraction", "name": "B", "location": {"lng": 104.02, "lat": 30.0}},
    ]})
    assert [i["type"] for i in dp["items"]] == ["attraction", "transport", "attraction"]
    assert round(dp["center"]["lng"], 3) == 104.01


async def test_reorder_reverse_only_target_day():
    state = {"day_plans": _plan(), "plan_version": 1,
             "refine_request": {"operations": [{"op": "reorder", "day": 1, "strategy": "reverse"}]}}
    out = await refine(state)
    assert out["changed_days"] == [1]
    stops = [i for i in out["day_plans"][0]["items"] if i.get("type") != "transport"]
    assert [i["name"] for i in stops] == ["陈麻婆", "武侯祠"]
    assert out["day_plans"][1]["items"] == _plan()[1]["items"]   # 第二天不动
    assert out["refine_request"]["needs_budget_recheck"] is False  # 纯 reorder 不重算预算


async def test_set_pace_relax_removes_and_recheck_budget():
    state = {"day_plans": _plan(), "plan_version": 1,
             "refine_request": {"operations": [{"op": "set_pace", "day": 2, "direction": "relax"}]}}
    out = await refine(state)
    assert out["changed_days"] == [2]
    assert len(out["day_plans"][1]["items"]) == 1   # 2 景点删 1 → 1 停靠点（<2 不插交通）
    assert out["plan_version"] == 2
    assert out["refine_request"]["needs_budget_recheck"] is True


async def test_remove_poi_by_name():
    state = {"day_plans": _plan(), "plan_version": 1,
             "refine_request": {"operations": [
                 {"op": "remove_poi", "day": 1, "selector": {"by": "name", "name": "武侯祠"}}]}}
    out = await refine(state)
    stops = [i["name"] for i in out["day_plans"][0]["items"] if i.get("type") != "transport"]
    assert "武侯祠" not in stops and "陈麻婆" in stops
    assert out["changed_days"] == [1]


async def test_remove_poi_miss_is_skipped_not_destructive():
    state = {"day_plans": _plan(), "plan_version": 1,
             "refine_request": {"operations": [
                 {"op": "remove_poi", "day": 1, "selector": {"by": "name", "name": "不存在景点"}}]}}
    out = await refine(state)
    assert out["changed_days"] == []
    assert out["day_plans"] == _plan()                       # 行程一字未动
    assert out["plan_version"] == 1                           # 无结构变化不增版本
    assert out["refine_notes"]["skipped"]                     # 有跳过记录
    assert not out["refine_notes"]["applied"]


async def test_set_budget_updates_limit_without_touching_plan():
    state = {"day_plans": _plan(), "plan_version": 1, "budget": 5000,
             "refine_request": {"operations": [{"op": "set_budget", "amount": 3000.0}]}}
    out = await refine(state)
    assert out["budget"] == 3000.0
    assert out["changed_days"] == [] and out["day_plans"] == _plan()
    assert out["plan_version"] == 1
    assert out["refine_request"]["needs_budget_recheck"] is True


async def test_set_hotel_marks_overnight_and_flags_accommodation():
    state = {"day_plans": _plan(), "plan_version": 1,
             "refine_request": {"operations": [{"op": "set_hotel", "criteria": "离地铁近"}]}}
    out = await refine(state)
    assert out["changed_days"] == [1]                         # 过夜日（共 2 天 → 第 1 天过夜）
    assert out["day_plans"][0]["items"] == _plan()[0]["items"]  # items 不动
    assert out["refine_request"]["needs_accommodation"] is True
    assert out["plan_version"] == 2


async def test_compound_reorder_then_remove_applied_in_order():
    state = {"day_plans": _plan(), "plan_version": 1,
             "refine_request": {"operations": [
                 {"op": "reorder", "day": 2, "strategy": "reverse"},
                 {"op": "remove_poi", "day": 2, "selector": {"by": "ordinal", "kind": "attraction", "index": -1}}]}}
    out = await refine(state)
    # reverse: [金沙, 杜甫] → 删最后一个 attraction(杜甫) → 剩 [金沙]
    stops = [i["name"] for i in out["day_plans"][1]["items"] if i.get("type") != "transport"]
    assert stops == ["金沙遗址"]
    assert out["changed_days"] == [2]
    assert len(out["refine_notes"]["applied"]) == 2


async def test_empty_operations_no_changes():
    state = {"day_plans": _plan(), "plan_version": 1, "refine_request": {"operations": []}}
    out = await refine(state)
    assert out["changed_days"] == []
    assert out["plan_version"] == 1
    assert out["day_plans"] == _plan()
    assert out["refine_request"]["needs_budget_recheck"] is False
    assert out["refine_request"]["needs_accommodation"] is False
