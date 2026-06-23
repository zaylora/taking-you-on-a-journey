"""M6 几何不变量守护测试：refine 改 items 后必须重派生交通段。

覆盖：
(a) reorder：停靠顺序倒序后交通段 from/to 随之更新
(b) relax：移除一个停靠点后无悬空交通、总数正确
(c) change_meal：换餐后周边交通段引用新餐厅名称/坐标
"""
import pytest

from app.graph.nodes.itinerary import insert_transport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stop(name: str, lng: float, lat: float, type_: str = "attraction") -> dict:
    return {
        "type": type_,
        "name": name,
        "poi_id": name,
        "location": {"lng": lng, "lat": lat},
    }


def _make_day(day_no: int, stops: list[dict]) -> dict:
    """用 insert_transport 构造真实的行程天，与 itinerary 节点输出结构一致。"""
    return {"day": day_no, "items": insert_transport(stops)}


def _stops_from(items: list[dict]) -> list[dict]:
    return [it for it in items if it.get("type") != "transport"]


def _transports_from(items: list[dict]) -> list[dict]:
    return [it for it in items if it.get("type") == "transport"]


# ---------------------------------------------------------------------------
# (a) reorder：倒序后交通段 from/to 随之更新
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reorder_rebuilds_transport_segments():
    """倒序 [A,B,C] → [C,B,A]，交通段 from/to 必须跟随新顺序，首尾为停靠点。"""
    stops = [
        _stop("A", 104.0, 30.0),
        _stop("B", 104.1, 30.1),
        _stop("C", 104.2, 30.2),
    ]
    day1 = _make_day(1, stops)
    state = {
        "query": "第一天顺序调一下",
        "day_plans": [day1],
        "plan_version": 1,
        "refine_request": {"operations": [{"op": "reorder", "day": 1, "strategy": "reverse"}]},
    }

    from app.graph.nodes.refine import refine
    out = await refine(state)

    result_items = out["day_plans"][0]["items"]
    result_stops = _stops_from(result_items)
    result_transports = _transports_from(result_items)

    # 停靠顺序倒序
    assert [s["name"] for s in result_stops] == ["C", "B", "A"]
    # 恰好 N-1 段交通
    assert len(result_transports) == 2
    # 首尾为停靠点（无悬空交通）
    assert result_items[0].get("type") != "transport"
    assert result_items[-1].get("type") != "transport"
    # 交通段 from/to 正确匹配相邻停靠点
    assert result_transports[0]["from"] == "C"
    assert result_transports[0]["to"] == "B"
    assert result_transports[1]["from"] == "B"
    assert result_transports[1]["to"] == "A"
    # mode 必须在合法值内
    valid_modes = {"步行", "公交", "驾车"}
    for t in result_transports:
        assert t["mode"] in valid_modes


# ---------------------------------------------------------------------------
# (b) relax：移除停靠点后无悬空交通
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_relax_no_dangling_transport():
    """relax 删最后一个停靠点，剩余 2 停靠点 → 1 段交通，末项为停靠点。"""
    stops = [
        _stop("X", 104.0, 30.0),
        _stop("Y", 104.1, 30.1),
        _stop("Z", 104.2, 30.2),
    ]
    day1 = _make_day(1, stops)
    state = {
        "query": "太赶了，少去一个",
        "day_plans": [day1],
        "plan_version": 1,
        "refine_request": {"operations": [{"op": "set_pace", "day": 1, "direction": "relax"}]},
    }

    from app.graph.nodes.refine import refine
    out = await refine(state)

    result_items = out["day_plans"][0]["items"]
    result_stops = _stops_from(result_items)
    result_transports = _transports_from(result_items)

    # 停靠点减少了 1 个
    assert len(result_stops) == 2
    # 交通段 = 停靠点 - 1
    assert len(result_transports) == len(result_stops) - 1
    # 末项是停靠点（无悬空交通）
    assert result_items[-1].get("type") != "transport"
    # 首项是停靠点
    assert result_items[0].get("type") != "transport"
    # 交通段 from/to 正确
    assert result_transports[0]["from"] == result_stops[0]["name"]
    assert result_transports[0]["to"] == result_stops[1]["name"]


# ---------------------------------------------------------------------------
# (c) change_meal：换餐后周边交通段引用新餐厅
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_change_meal_updates_surrounding_transport(fake_amap):
    """换餐后，紧邻 meal 的交通段 from/to 应指向新餐厅，而非旧餐厅。"""
    old_meal = _stop("旧饭馆", 104.05, 30.05, type_="meal")
    attraction = _stop("景点A", 104.0, 30.0, type_="attraction")
    stops = [attraction, old_meal]
    day1 = _make_day(1, stops)

    new_restaurant_name = "新火锅"
    fake_amap["search_around"] = [
        {"name": new_restaurant_name, "poi_id": "NEW_MEAL", "lng": 104.09, "lat": 30.09}
    ]

    state = {
        "query": "把第一天晚餐换成火锅",
        "city": "成都",
        "day_plans": [day1],
        "plan_version": 1,
        "refine_request": {
            "operations": [{"op": "replace_poi", "day": 1, "kind": "meal", "query": "火锅",
                            "selector": {"by": "ordinal", "kind": "meal", "index": 0}}]
        },
    }

    from app.graph.nodes.refine import refine
    out = await refine(state)

    result_items = out["day_plans"][0]["items"]
    result_stops = _stops_from(result_items)
    result_transports = _transports_from(result_items)

    # meal 已被替换
    meals = [s for s in result_stops if s.get("type") == "meal"]
    assert len(meals) == 1
    assert meals[0]["name"] == new_restaurant_name

    # 交通段 to 应指向新餐厅（不是旧饭馆）
    assert len(result_transports) == 1
    assert result_transports[0]["from"] == "景点A"
    assert result_transports[0]["to"] == new_restaurant_name
    # 确保不再引用旧餐厅
    assert result_transports[0]["to"] != "旧饭馆"

    # 末项为停靠点
    assert result_items[-1].get("type") != "transport"
