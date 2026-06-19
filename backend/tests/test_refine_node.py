import pytest

from app.graph.nodes.refine import refine, _find_day, _reorder_day


def _plan():
    return [
        {"day": 1, "items": [
            {"type": "attraction", "name": "武侯祠", "poi_id": "B1"},
            {"type": "meal", "name": "陈麻婆", "poi_id": "M1"}]},
        {"day": 2, "items": [
            {"type": "attraction", "name": "杜甫草堂", "poi_id": "B2"},
            {"type": "attraction", "name": "金沙遗址", "poi_id": "B3"}]},
    ]


def test_find_day():
    assert _find_day(_plan(), 2) == 1
    assert _find_day(_plan(), 9) is None
    assert _find_day(_plan(), None) is None


def test_reorder_day_reverses_items():
    out = _reorder_day({"day": 1, "items": [{"name": "A"}, {"name": "B"}]})
    assert [i["name"] for i in out["items"]] == ["B", "A"]


@pytest.mark.asyncio
async def test_relax_only_target_day():
    state = {"query": "第二天太赶了，少一个景点", "day_plans": _plan(), "plan_version": 1,
             "refine_request": {"op": "relax", "target_day": 2, "needs_budget_recheck": True}}
    out = await refine(state)
    assert out["changed_days"] == [2]
    assert [i["name"] for i in out["day_plans"][0]["items"]] == ["武侯祠", "陈麻婆"]  # 第一天不动
    assert len(out["day_plans"][1]["items"]) == 1
    assert out["plan_version"] == 2


@pytest.mark.asyncio
async def test_reorder_changes_only_order():
    state = {"query": "第一天顺序调一下", "day_plans": _plan(), "plan_version": 1,
             "refine_request": {"op": "reorder", "target_day": 1, "needs_budget_recheck": False}}
    out = await refine(state)
    assert out["changed_days"] == [1]
    assert [i["name"] for i in out["day_plans"][0]["items"]] == ["陈麻婆", "武侯祠"]


@pytest.mark.asyncio
async def test_change_budget_updates_limit_without_touching_plan():
    state = {"query": "预算改成3000", "day_plans": _plan(), "plan_version": 1, "budget": 5000,
             "refine_request": {"op": "change_budget", "target_day": None,
                                "constraints": {"budget": 3000.0}, "needs_budget_recheck": True}}
    out = await refine(state)
    assert out["budget"] == 3000.0
    assert out["changed_days"] == []
    assert out["day_plans"] == _plan()       # 行程不动
    assert out["plan_version"] == 1           # 行程未变，版本不增


@pytest.mark.asyncio
async def test_change_hotel_marks_overnight_days_for_refresh():
    state = {"query": "换个离地铁近的酒店", "day_plans": _plan(), "plan_version": 1,
             "refine_request": {"op": "change_hotel", "target_day": None, "needs_budget_recheck": True}}
    out = await refine(state)
    # items 不动；标记过夜日（第一天）待 accommodation 重排 + 前端刷新
    assert out["changed_days"] == [1]
    assert out["day_plans"][0]["items"] == _plan()[0]["items"]
    assert out["plan_version"] == 2
