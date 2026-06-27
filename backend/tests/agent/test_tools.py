# -*- coding: utf-8 -*-
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.agent import tools
from app.agent.time_context import current_time_payload
from app.agent.itinerary.schemas import DayPlans
from app.agent.itinerary.lodging import _AccoResult
from tests.conftest import make_fake_build_llm


def _schema_property(tool_obj, field_name: str) -> dict:
    return tool_obj.args_schema.model_json_schema()["properties"][field_name]


def test_plan_route_schema_describes_coordinate_inputs():
    origin = _schema_property(tools.plan_route, "origin")
    dest = _schema_property(tools.plan_route, "dest")
    mode = _schema_property(tools.plan_route, "mode")

    for prop in (origin, dest):
        description = prop.get("description", "")
        assert "lng,lat" in description
        assert "POI" in description
        assert "不要" in description
        assert "地名" in description

    assert "transit" in mode.get("description", "")


def test_current_time_payload_uses_requested_timezone():
    now = datetime(2026, 6, 27, 8, 9, 10, tzinfo=ZoneInfo("UTC"))
    out = current_time_payload("Asia/Shanghai", now=now)

    assert out["date"] == "2026-06-27"
    assert out["time"] == "16:09:10"
    assert out["timezone"] == "Asia/Shanghai"
    assert out["weekday"] == "Saturday"
    assert out["utc_offset"] == "+08:00"


def test_get_current_time_schema_and_output_shape():
    timezone = _schema_property(tools.get_current_time, "timezone")
    assert "IANA" in timezone.get("description", "")

    out = tools.get_current_time.invoke({"timezone": "UTC"})
    assert set(out) == {"iso", "timezone", "unix_ms", "date", "time", "weekday", "utc_offset"}
    assert out["timezone"] == "UTC"
    assert out["utc_offset"] == "+00:00"


@pytest.mark.asyncio
async def test_search_attractions_returns_pois(fake_amap):
    fake_amap["search_poi"] = [{"name": "故宫", "poi_id": "p1", "lng": 116.4, "lat": 39.9}]
    out = await tools.search_attractions.ainvoke({"city": "北京", "keywords": "热门景点"})
    assert out[0]["name"] == "故宫"


def test_search_attractions_schema_describes_query_limits():
    city = _schema_property(tools.search_attractions, "city")
    keywords = _schema_property(tools.search_attractions, "keywords")

    assert "地级市" in city.get("description", "")
    assert "不要" in city.get("description", "")
    assert "短关键词" in keywords.get("description", "")
    assert "自动拆词补查" in keywords.get("description", "")


@pytest.mark.asyncio
async def test_search_attractions_splits_keywords_when_sparse(monkeypatch):
    calls = []

    async def _search_poi(city, keywords, poi_type="", page_size=20):
        calls.append((city, keywords, poi_type, page_size))
        if keywords == "清晖园 顺峰山公园":
            return []
        return [{"name": keywords, "poi_id": keywords, "lng": 113.0, "lat": 23.0}]

    monkeypatch.setattr("app.tools.amap.search_poi", _search_poi)

    out = await tools.search_attractions.ainvoke({
        "city": "佛山",
        "keywords": "清晖园 顺峰山公园",
    })

    assert [poi["name"] for poi in out] == ["清晖园", "顺峰山公园"]
    assert calls == [
        ("佛山", "清晖园 顺峰山公园", "风景名胜", 20),
        ("佛山", "清晖园", "风景名胜", 10),
        ("佛山", "顺峰山公园", "风景名胜", 10),
    ]


@pytest.mark.asyncio
async def test_search_attractions_degrades_to_empty(fake_amap, monkeypatch):
    async def _boom(*a, **k):
        raise RuntimeError("amap down")
    monkeypatch.setattr("app.tools.amap.search_poi", _boom)
    out = await tools.search_attractions.ainvoke({"city": "北京", "keywords": "x"})
    assert out == []


@pytest.mark.asyncio
async def test_get_weather_tool(fake_amap):
    out = await tools.get_weather.ainvoke({"city": "成都"})
    assert out["text"] == "多云"


@pytest.mark.asyncio
async def test_assemble_itinerary_runs_ortools_pipeline(fake_amap, monkeypatch, tmp_path):
    # soft_fill 的 LLM 输出（structured DayPlans）
    fake = DayPlans(days=[{"day": 1, "items": [
        {"type": "attraction", "name": "故宫", "poi_id": "p1", "cost": 60}]}])
    monkeypatch.setattr("app.agent.tools.itinerary.build_llm", make_fake_build_llm(structured=fake))
    monkeypatch.setenv("CHECKPOINT_DB_PATH", str(tmp_path / "checkpoints.sqlite"))
    from app.core.config import get_settings
    get_settings.cache_clear()
    out = await tools.assemble_itinerary.ainvoke({
        "city": "北京", "days": 1,
        "attractions": [
            {"name": "故宫", "poi_id": "p1", "lng": 116.40, "lat": 39.92, "rating": 5.0},
            {"name": "天坛", "poi_id": "p2", "lng": 116.41, "lat": 39.88, "rating": 4.8},
        ],
        "restaurants": [], "weather": {"text": "晴"},
    })
    get_settings.cache_clear()
    assert out["day_plans"][0]["day"] == 1
    assert out["day_plans"][0]["items"][0]["name"] == "故宫"
    assert "daily_centers" in out


@pytest.mark.asyncio
async def test_assemble_itinerary_empty_candidates(fake_amap, monkeypatch):
    monkeypatch.setattr("app.agent.tools.itinerary.build_llm",
                        make_fake_build_llm(structured=DayPlans(days=[])))
    out = await tools.assemble_itinerary.ainvoke({
        "city": "北京", "days": 2, "attractions": [], "restaurants": [], "weather": {},
    })
    assert out["day_plans"] == []
    assert out["daily_centers"] == []


@pytest.mark.asyncio
async def test_assemble_itinerary_accepts_stringified_budget_advice(fake_amap, monkeypatch):
    monkeypatch.setattr("app.agent.tools.itinerary.build_llm",
                        make_fake_build_llm(structured=DayPlans(days=[])))
    out = await tools.assemble_itinerary.ainvoke({
        "city": "佛山",
        "days": 2,
        "attractions": [],
        "restaurants": [],
        "weather": {"text": "雨"},
        "budget_advice": "{'over_amount': 100.0, 'cut_suggestions': []}",
    })

    assert out["day_plans"] == []
    assert out["daily_centers"] == []


def test_assemble_itinerary_schema_describes_budget_advice_as_object_not_string():
    budget_advice = _schema_property(tools.assemble_itinerary, "budget_advice")
    description = budget_advice.get("description", "")

    assert "对象" in description
    assert "不要" in description
    assert "字符串" in description
    assert "cut_suggestions" in description


@pytest.mark.asyncio
async def test_assign_hotels_embeds(fake_amap, monkeypatch):
    res = _AccoResult(assignments=[{"day": 1, "hotel": {"name": "如家", "price": 300, "level": "经济"}}])
    monkeypatch.setattr("app.agent.tools.lodging.build_llm", make_fake_build_llm(structured=res))
    dps = [{"day": 1, "items": []}, {"day": 2, "items": []}]  # 过夜日=第1天
    out = await tools.assign_hotels.ainvoke({"city": "北京", "day_plans": dps, "level": "经济"})
    assert out[0]["hotel"]["name"] == "如家"


@pytest.mark.asyncio
async def test_assign_hotels_accepts_stringified_daily_centers(fake_amap, monkeypatch):
    res = _AccoResult(assignments=[{"day": 1, "hotel": {"name": "如家", "price": 300, "level": "经济"}}])
    monkeypatch.setattr("app.agent.tools.lodging.build_llm", make_fake_build_llm(structured=res))
    dps = [{"day": 1, "items": []}, {"day": 2, "items": []}]

    out = await tools.assign_hotels.ainvoke({
        "city": "佛山",
        "day_plans": dps,
        "level": "舒适",
        "daily_centers": "[{'lng': 113.271077, 'lat': 22.780128}]",
    })

    assert out[0]["hotel"]["name"] == "如家"


def test_assign_hotels_schema_describes_daily_centers_as_array_not_string():
    daily_centers = _schema_property(tools.assign_hotels, "daily_centers")
    description = daily_centers.get("description", "")

    assert "数组" in description
    assert "assemble_itinerary" in description
    assert "不要" in description
    assert "字符串" in description


from langgraph.types import Command as _Command


@pytest.mark.asyncio
async def test_compute_budget_tool_writes_budget_check_to_state(fake_amap):
    """必须用 Command 把 budget_check/retry_count 写回 state，
    否则 stream 层 aget_state 读不到 → 前端预算条永远空。"""
    dps = [{"day": 1, "items": [
        {"type": "attraction", "name": "A", "cost": 100.0},
        {"type": "meal", "name": "B", "cost": 50.0},
    ]}]
    cmd = await tools.compute_budget_tool.ainvoke({
        "type": "tool_call",
        "name": "compute_budget_tool",
        "id": "call_b",
        "args": {"day_plans": dps, "num_people": 2, "limit": 0.0,
                 "state": {"retry_count": 0}},
    })
    assert isinstance(cmd, _Command), "必须返回 Command 才能写回 state"
    assert cmd.update["budget_check"]["estimated"] == 300.0  # (100+50)*2
    assert "retry_count" in cmd.update
    assert cmd.update.get("messages")  # 回传 ToolMessage 供 agent 据此决策


@pytest.mark.asyncio
async def test_compute_budget_tool_over_and_accumulates_retry(fake_amap):
    """超预算时 over=True，且 retry_count 递增写回，供 _MAX_RETRY 上限生效。"""
    dps = [{"day": 1, "items": [{"type": "attraction", "name": "A", "cost": 5000}]},
           {"day": 2, "items": []}]
    cmd = await tools.compute_budget_tool.ainvoke({
        "type": "tool_call",
        "name": "compute_budget_tool",
        "id": "call_b",
        "args": {"day_plans": dps, "num_people": 1, "limit": 100,
                 "state": {"retry_count": 0}},
    })
    assert isinstance(cmd, _Command)
    assert cmd.update["budget_check"]["over"] is True
    assert cmd.update["retry_count"] == 1  # 0 → 1


@pytest.mark.asyncio
async def test_finalize_plan_writes_and_diffs(fake_amap):
    new_dps = [{"day": 1, "items": [{"type": "attraction", "name": "故宫", "poi_id": "p1"}]}]
    cmd = await tools.finalize_plan.ainvoke({
        "type": "tool_call",
        "name": "finalize_plan",
        "id": "call_x",
        "args": {
            "day_plans": new_dps,
            "state": {"day_plans": [], "plan_version": 0},
        },
    })
    assert isinstance(cmd, _Command)
    assert cmd.update["day_plans"] == new_dps
    assert cmd.update["changed_days"] == [1]
    assert cmd.update["plan_version"] == 1
