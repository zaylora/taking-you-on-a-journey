import pytest

from app.graph.nodes.enrich_duration import apply_durations, enrich_duration


def _a(name, **kw):
    return {"name": name, "poi_id": name, "type": kw.get("type", ""), **kw}


def test_apply_durations_maps_by_poi_id():
    atts = [_a("故宫"), _a("公园", type="公园")]
    out = apply_durations(atts, {"故宫": 300})
    assert out[0]["visit_minutes"] == 300       # 来自 map
    assert out[1]["visit_minutes"] == 120        # 静态兜底（公园）


def test_apply_durations_static_fallback_for_unmapped():
    out = apply_durations([_a("某地")], {})
    assert out[0]["visit_minutes"] == 90         # 默认


async def test_enrich_duration_without_tavily(monkeypatch):
    import app.graph.nodes.enrich_duration as ed
    monkeypatch.setattr(ed, "build_tavily_tool", lambda: None)
    atts = [_a("博物馆", type="博物馆"), _a("广场", type="广场")]
    out = await enrich_duration({"attractions": atts}, config={})
    vms = {a["name"]: a["visit_minutes"] for a in out["attractions"]}
    assert vms["博物馆"] == 150
    assert vms["广场"] == 60
