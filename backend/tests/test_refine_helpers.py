from app.graph.nodes.refine import (
    _resolve_selector, _recompute_center, _optimize_stops, _relax_stops,
)


def _stops():
    return [
        {"type": "attraction", "name": "武侯祠", "poi_id": "A1", "location": {"lng": 104.05, "lat": 30.65}},
        {"type": "meal", "name": "陈麻婆", "poi_id": "M1", "location": {"lng": 104.06, "lat": 30.66}},
        {"type": "attraction", "name": "锦里", "poi_id": "A2", "location": {"lng": 104.04, "lat": 30.64}},
    ]


def test_resolve_selector_by_name():
    assert _resolve_selector(_stops(), {"by": "name", "name": "锦里"}) == 2
    assert _resolve_selector(_stops(), {"by": "name", "name": "不存在"}) is None


def test_resolve_selector_by_ordinal_last_attraction():
    # 最后一个 attraction 是「锦里」(index 2)
    assert _resolve_selector(_stops(), {"by": "ordinal", "kind": "attraction", "index": -1}) == 2
    # 第一个 meal 是「陈麻婆」(index 1)
    assert _resolve_selector(_stops(), {"by": "ordinal", "kind": "meal", "index": 0}) == 1


def test_resolve_selector_out_of_range_returns_none():
    assert _resolve_selector(_stops(), {"by": "ordinal", "kind": "meal", "index": 5}) is None


def test_recompute_center_is_mean_of_stop_coords():
    c = _recompute_center(_stops())
    assert round(c["lng"], 3) == round((104.05 + 104.06 + 104.04) / 3, 3)
    assert round(c["lat"], 3) == round((30.65 + 30.66 + 30.64) / 3, 3)


def test_recompute_center_empty():
    assert _recompute_center([]) == {"lng": 0.0, "lat": 0.0}


def test_optimize_stops_starts_from_first_and_is_permutation():
    out = _optimize_stops(_stops())
    assert out[0]["poi_id"] == "A1"
    assert sorted(s["poi_id"] for s in out) == ["A1", "A2", "M1"]


def test_relax_stops_removes_at_least_one_when_over_budget():
    # 6 个景点（无 visit_minutes 时按默认估时）必定超 DAY_BUDGET → 至少删 1
    big = [{"type": "attraction", "name": f"P{i}", "poi_id": f"A{i}",
            "location": {"lng": 104.0 + i * 0.01, "lat": 30.6}} for i in range(6)]
    out = _relax_stops(big)
    assert len(out) < len(big)
