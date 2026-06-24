from app.planning.apply import apply_operations
from app.graph.nodes.itinerary import insert_transport


def _plan():
    day1 = [{"type": "attraction", "name": "武侯祠", "poi_id": "B1", "location": {"lng": 104.05, "lat": 30.65}},
            {"type": "meal", "name": "陈麻婆", "poi_id": "M1", "location": {"lng": 104.06, "lat": 30.66}}]
    day2 = [{"type": "attraction", "name": "杜甫草堂", "poi_id": "B2", "location": {"lng": 104.04, "lat": 30.67}},
            {"type": "attraction", "name": "金沙遗址", "poi_id": "B3", "location": {"lng": 104.03, "lat": 30.68}}]
    return [{"day": 1, "items": insert_transport(day1), "center": {"lng": 104.055, "lat": 30.655}},
            {"day": 2, "items": insert_transport(day2), "center": {"lng": 104.035, "lat": 30.675}}]


async def test_apply_reorder_only_target_day():
    state = {"day_plans": _plan(), "plan_version": 1}
    out = await apply_operations([{"op": "reorder", "day": 1, "strategy": "reverse"}], {}, state)
    assert out["changed_days"] == [1]
    stops = [i["name"] for i in out["day_plans"][0]["items"] if i.get("type") != "transport"]
    assert stops == ["陈麻婆", "武侯祠"]
    assert out["needs_budget_recheck"] is False
    assert out["day_plans"][1]["items"] == _plan()[1]["items"]


async def test_apply_remove_poi_miss_is_honest_skip():
    state = {"day_plans": _plan(), "plan_version": 1}
    out = await apply_operations(
        [{"op": "remove_poi", "day": 1, "selector": {"by": "name", "name": "不存在"}}], {}, state)
    assert out["changed_days"] == [] and out["plan_version"] == 1
    assert out["skipped"] and not out["applied"]


async def test_apply_set_budget_sets_flag_and_value():
    state = {"day_plans": _plan(), "plan_version": 1, "budget": 5000}
    out = await apply_operations([{"op": "set_budget", "amount": 3000.0}], {}, state)
    assert out["budget"] == 3000.0 and out["needs_budget_recheck"] is True
    assert out["changed_days"] == []


async def test_apply_set_hotel_flags_accommodation():
    state = {"day_plans": _plan(), "plan_version": 1}
    out = await apply_operations([{"op": "set_hotel", "criteria": "离地铁近"}], {}, state)
    assert out["needs_accommodation"] is True and out["changed_days"] == [1]
    assert out["plan_version"] == 2


async def test_apply_replace_plan_sets_both_flags(fake_amap, monkeypatch):
    from app.planning import apply as apply_mod

    async def _fake_replace(req, context, state, config=None):
        return {"daily_centers": [{"lng": 113.2, "lat": 23.1}],
                "day_plans": [{"day": 1, "items": [], "center": {"lng": 113.2, "lat": 23.1}}],
                "dropped_attractions": [], "relax_level": 0}
    monkeypatch.setattr(apply_mod, "replace_plan", _fake_replace)
    out = await apply_operations(
        [{"op": "replace_plan", "requirements_patch": {"city": "广州", "days": 1}}],
        {"attractions": [], "restaurants": []}, {"plan_version": 2})
    assert out["needs_accommodation"] is True and out["needs_budget_recheck"] is True
    assert out["changed_days"] == [1] and out["plan_version"] == 3


async def test_apply_answer_only_is_noop_on_plan():
    state = {"day_plans": _plan(), "plan_version": 1}
    out = await apply_operations([{"op": "answer_only", "question": "为什么"}], {}, state)
    assert out["day_plans"] == _plan() and out["changed_days"] == []
    assert out["plan_version"] == 1
