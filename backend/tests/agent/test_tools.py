# -*- coding: utf-8 -*-
import pytest

from app.agent import tools
from app.agent.planning import DayPlans
from app.agent.lodging import _AccoResult
from tests.conftest import make_fake_build_llm


@pytest.mark.asyncio
async def test_search_attractions_returns_pois(fake_amap):
    fake_amap["search_poi"] = [{"name": "故宫", "poi_id": "p1", "lng": 116.4, "lat": 39.9}]
    out = await tools.search_attractions.ainvoke({"city": "北京", "keywords": "热门景点"})
    assert out[0]["name"] == "故宫"


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
    monkeypatch.setattr("app.agent.tools.build_llm", make_fake_build_llm(structured=fake))
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
    monkeypatch.setattr("app.agent.tools.build_llm",
                        make_fake_build_llm(structured=DayPlans(days=[])))
    out = await tools.assemble_itinerary.ainvoke({
        "city": "北京", "days": 2, "attractions": [], "restaurants": [], "weather": {},
    })
    assert out["day_plans"] == []
    assert out["daily_centers"] == []


@pytest.mark.asyncio
async def test_assign_hotels_embeds(fake_amap, monkeypatch):
    res = _AccoResult(assignments=[{"day": 1, "hotel": {"name": "如家", "price": 300, "level": "经济"}}])
    monkeypatch.setattr("app.agent.tools.build_llm", make_fake_build_llm(structured=res))
    dps = [{"day": 1, "items": []}, {"day": 2, "items": []}]  # 过夜日=第1天
    out = await tools.assign_hotels.ainvoke({"city": "北京", "day_plans": dps, "level": "经济"})
    assert out[0]["hotel"]["name"] == "如家"


from langgraph.types import Command as _Command


@pytest.mark.asyncio
async def test_compute_budget_tool_reports_over(fake_amap):
    dps = [{"day": 1, "items": [{"type": "attraction", "name": "A", "cost": 5000}]}, {"day": 2, "items": []}]
    out = await tools.compute_budget_tool.ainvoke({
        "day_plans": dps, "num_people": 1, "limit": 100,
        "state": {"retry_count": 0},
    })
    assert out["budget_check"]["over"] is True
    assert isinstance(out["cut_suggestions"], list)


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
