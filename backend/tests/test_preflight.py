from app.planning.preflight import preflight, infer_city, OP_REQUIREMENTS, PreflightResult


def _plan():
    return [{"day": 1, "items": [{"type": "attraction", "name": "越秀公园"}]},
            {"day": 2, "items": [{"type": "attraction", "name": "陈家祠"}]}]


def test_op_requirements_covers_all_ops():
    for op in ("replace_plan", "set_region", "add_poi", "remove_poi", "replace_poi",
               "reorder", "set_pace", "set_budget", "set_hotel", "answer_only"):
        assert op in OP_REQUIREMENTS


def test_infer_city_from_normalized_req():
    assert infer_city({"normalized_req": {"city": "广州"}}) == "广州"


def test_infer_city_falls_back_to_top_level():
    assert infer_city({"city": "成都"}) == "成都"


def test_infer_city_empty_when_unknown():
    assert infer_city({"day_plans": _plan()}) == ""


def test_set_region_patches_city_from_normalized_req():
    ops = [{"op": "set_region", "day": 1, "area": "黄埔"}]
    res = preflight(ops, {"normalized_req": {"city": "广州"}, "day_plans": _plan()})
    assert isinstance(res, PreflightResult)
    assert res.operations[0]["requirements_patch"]["city"] == "广州"
    assert res.blocked == [] and res.clarification == ""


def test_set_region_missing_city_asks_clarification():
    ops = [{"op": "set_region", "day": 1, "area": "黄埔"}]
    res = preflight(ops, {"day_plans": _plan()})   # 无 city 任何来源
    assert res.clarification          # 反问城市
    assert any(b["op"] == "set_region" and "city" in b["missing"] for b in res.blocked)


def test_set_region_missing_day_is_blocked_for_render():
    ops = [{"op": "set_region", "day": 9, "area": "黄埔"}]
    res = preflight(ops, {"normalized_req": {"city": "广州"}, "day_plans": _plan()})
    assert any(b["op"] == "set_region" and "day_exists" in b["missing"] for b in res.blocked)


def test_replace_plan_needs_city_and_days():
    ok = preflight([{"op": "replace_plan", "requirements_patch": {"city": "广州", "days": 3}}], {})
    assert ok.blocked == [] and ok.clarification == ""
    bad = preflight([{"op": "replace_plan", "requirements_patch": {"days": 3}}], {})
    assert bad.clarification and any("city" in b["missing"] for b in bad.blocked)


def test_set_budget_missing_amount_blocked():
    res = preflight([{"op": "set_budget"}], {"day_plans": _plan()})
    assert any(b["op"] == "set_budget" and "amount" in b["missing"] for b in res.blocked)


def test_answer_only_always_ok():
    res = preflight([{"op": "answer_only", "question": "为什么这么赶"}], {})
    assert res.blocked == [] and res.clarification == ""


def test_local_op_ok_when_day_exists():
    res = preflight([{"op": "reorder", "day": 1}], {"day_plans": _plan()})
    assert res.blocked == [] and res.clarification == ""
