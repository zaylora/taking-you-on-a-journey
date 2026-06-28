# -*- coding: utf-8 -*-
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.agent import tools
from app.agent.build import _TOOLS
from app.agent.time_context import current_time_payload
from app.agent.tools import xhs as xhs_tools
from app.agent.itinerary.schemas import DayPlans
from app.agent.itinerary.lodging import _AccoResult
from tests.conftest import make_fake_build_llm


class _FailingStructuredRunnable:
    async def ainvoke(self, *_args, **_kwargs):
        raise TimeoutError("soft fill timed out")


class _FailingStructuredLLM:
    def with_structured_output(self, *_args, **_kwargs):
        return _FailingStructuredRunnable()


class _InvalidStructuredRunnable:
    async def ainvoke(self, *_args, **_kwargs):
        return object()


class _InvalidStructuredLLM:
    def with_structured_output(self, *_args, **_kwargs):
        return _InvalidStructuredRunnable()


class _RaisingBuildLLM:
    def __call__(self, *_args, **_kwargs):
        raise RuntimeError("llm construction failed")


class _CapturingStructuredRunnable:
    def __init__(self, result, calls):
        self._result = result
        self._calls = calls

    async def ainvoke(self, messages, **_kwargs):
        self._calls.append(messages)
        return self._result


class _CapturingStructuredLLM:
    def __init__(self, result, calls):
        self._result = result
        self._calls = calls

    def with_structured_output(self, *_args, **_kwargs):
        return _CapturingStructuredRunnable(self._result, self._calls)


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


def test_xhs_tools_are_registered_with_agent():
    tool_names = {getattr(t, "name", "") for t in _TOOLS}

    assert {
        "xhs_status",
        "research_xhs_travel_guide",
        "xhs_search_notes",
        "xhs_read_note",
        "xhs_note_comments",
        "xhs_hot_notes",
        "xhs_user_profile",
    } <= tool_names


def test_xhs_command_supports_configurable_binary(monkeypatch):
    monkeypatch.setenv("XHS_CLI_BIN", "uv run xhs")

    assert xhs_tools._xhs_command(["status"]) == ["uv", "run", "xhs", "status", "--json"]


def test_xhs_normalize_cli_result_preserves_success_envelope():
    out = xhs_tools._normalize_cli_result(
        0,
        b'{"ok": true, "schema_version": "1", "data": {"items": []}}',
        b"",
    )

    assert out["ok"] is True
    assert out["data"]["items"] == []


def test_xhs_normalize_cli_result_redacts_failure_text():
    out = xhs_tools._normalize_cli_result(
        1,
        b"",
        b"cookie=a1-secret web_session=secret-token failed",
    )

    assert out["ok"] is False
    assert "a1-secret" not in out["error"]["message"]
    assert "secret-token" not in out["error"]["message"]


def test_xhs_extract_note_targets_from_nested_search_result():
    result = {
        "ok": True,
        "data": {
            "items": [
                {"note_id": "note-a", "title": "A"},
                {"note": {"url": "https://xhslink.com/b", "title": "B"}},
                {"id": "user-1", "user_id": "user-1"},
                {"id": "note-c", "title": "C"},
            ]
        },
    }

    assert xhs_tools._extract_note_targets(result, limit=3) == [
        "note-a",
        "https://xhslink.com/b",
        "note-c",
    ]


def test_xhs_guide_keywords_are_strategy_oriented():
    out = xhs_tools._build_xhs_guide_keywords(
        city="顺德",
        days=1,
        travel_style="美食慢游",
        keywords=["避雷", "雨天", "双皮奶"],
    )

    assert out == [
        "顺德旅游攻略",
        "顺德1日游攻略",
        "顺德美食攻略",
        "顺德美食慢游攻略",
        "顺德避雷攻略",
        "顺德雨天攻略",
    ]
    assert all("攻略" in keyword for keyword in out)


def test_extract_xhs_image_urls_prefers_note_images_and_dedupes():
    note = {
        "ok": True,
        "data": {
            "items": [{
                "note_card": {
                    "image_list": [
                        {"url_default": "https://sns-img-qc.xhscdn.com/a.jpg"},
                        {"url_pre": "https://sns-img-qc.xhscdn.com/b.webp?x=1"},
                        {"url": "https://sns-img-qc.xhscdn.com/a.jpg"},
                    ],
                    "cover": "https://sns-img-qc.xhscdn.com/cover.jpg",
                    "user": {"avatar": "https://sns-avatar-qc.xhscdn.com/avatar.jpg"},
                }
            }]
        },
    }

    assert xhs_tools._extract_xhs_image_urls(note, limit=4) == [
        "https://sns-img-qc.xhscdn.com/a.jpg",
        "https://sns-img-qc.xhscdn.com/b.webp?x=1",
        "https://sns-img-qc.xhscdn.com/cover.jpg",
    ]


def test_build_xhs_image_messages_uses_multimodal_blocks():
    messages = xhs_tools._build_xhs_image_messages(
        target="note-1",
        note={"ok": True, "data": {"title": "顺德攻略"}},
        image_urls=["https://sns-img-qc.xhscdn.com/a.jpg"],
    )

    assert len(messages) == 2
    assert "图文解析" in messages[0].content
    assert messages[1].content[0]["type"] == "text"
    assert messages[1].content[1] == {
        "type": "image_url",
        "image_url": {"url": "https://sns-img-qc.xhscdn.com/a.jpg"},
    }


@pytest.mark.asyncio
async def test_xhs_search_notes_normalizes_travel_keyword_to_guide_query(monkeypatch):
    calls = []

    async def _fake_run(args):
        calls.append(args)
        return {"ok": True, "data": {"items": []}}

    monkeypatch.setattr(xhs_tools, "_run_xhs_json", _fake_run)

    out = await tools.xhs_search_notes.ainvoke({
        "keyword": "东京亲子游",
        "sort": "popular",
        "note_type": "image",
        "page": 1,
    })

    assert out["ok"] is True
    assert calls == [[
        "search", "东京亲子游攻略",
        "--sort", "popular",
        "--type", "image",
        "--page", "1",
    ]]


@pytest.mark.asyncio
async def test_xhs_search_notes_builds_safe_cli_args(monkeypatch):
    calls = []

    async def _fake_run(args):
        calls.append(args)
        return {"ok": True, "data": {"items": []}}

    monkeypatch.setattr(xhs_tools, "_run_xhs_json", _fake_run)

    out = await tools.xhs_search_notes.ainvoke({
        "keyword": "顺德美食",
        "sort": "popular",
        "note_type": "image",
        "page": 2,
    })

    assert out["ok"] is True
    assert calls == [[
        "search", "顺德美食攻略",
        "--sort", "popular",
        "--type", "image",
        "--page", "2",
    ]]


@pytest.mark.asyncio
async def test_xhs_note_comments_can_request_all_comments(monkeypatch):
    calls = []

    async def _fake_run(args):
        calls.append(args)
        return {"ok": True, "data": {"comments": []}}

    monkeypatch.setattr(xhs_tools, "_run_xhs_json", _fake_run)

    await tools.xhs_note_comments.ainvoke({"target": "note-1", "include_all": True})

    assert calls == [["comments", "note-1", "--all"]]


@pytest.mark.asyncio
async def test_xhs_read_note_adds_image_analysis_without_changing_envelope(monkeypatch):
    calls = []

    async def _fake_run(args):
        calls.append(args)
        return {
            "ok": True,
            "data": {
                "items": [{
                    "note_card": {
                        "title": "顺德攻略",
                        "image_list": [{"url_default": "https://sns-img-qc.xhscdn.com/a.jpg"}],
                    }
                }]
            },
        }

    async def _fake_analyze(target, note, *, max_images):
        assert target == "note-1"
        assert max_images == 2
        assert note["ok"] is True
        return {
            "target": target,
            "image_count": 1,
            "visible_text": ["清晖园 09:00"],
            "places": ["清晖园"],
            "foods": [],
            "route_or_time_clues": ["09:00 人少"],
            "tips": [],
            "confidence": "high",
            "warnings": [],
            "image_urls": ["https://sns-img-qc.xhscdn.com/a.jpg"],
        }

    monkeypatch.setattr(xhs_tools, "_run_xhs_json", _fake_run)
    monkeypatch.setattr(xhs_tools, "_analyze_xhs_note_images", _fake_analyze)

    out = await tools.xhs_read_note.ainvoke({
        "target": "note-1",
        "analyze_images": True,
        "max_images": 2,
    })

    assert out["ok"] is True
    assert out["data"]["items"][0]["note_card"]["title"] == "顺德攻略"
    assert out["image_analysis"]["places"] == ["清晖园"]
    assert out["meta"]["image_analysis"]["attempted"] is True
    assert out["meta"]["image_analysis"]["image_count"] == 1
    assert calls == [["read", "note-1"]]


@pytest.mark.asyncio
async def test_research_xhs_travel_guide_extracts_structured_brief(monkeypatch):
    calls = []

    async def _fake_run(args):
        calls.append(args)
        if args[0] == "search":
            return {"ok": True, "data": {"items": [{"note_id": "note-1"}, {"note_id": "note-2"}]}}
        if args[0] == "read":
            return {"ok": True, "data": {"title": f"{args[1]} 攻略", "desc": "09:00 去清晖园，人少好拍"}}
        if args[0] == "comments":
            return {"ok": True, "data": {"comments": [{"content": "节假日排队久"}]}}
        return {"ok": True, "data": {}}

    brief = xhs_tools.XhsTravelBrief(
        city="顺德",
        summary="早上适合清晖园，午餐围绕华盖路。",
        recommended_places=[
            xhs_tools.XhsRecommendedPlace(
                name="清晖园",
                reason="多篇攻略提到上午人少，适合拍照。",
                priority="high",
                source_count=2,
            )
        ],
        time_suggestions=[
            xhs_tools.XhsTimeSuggestion(
                time="09:00",
                place="清晖园",
                activity="游览拍照",
                reason="上午人少。",
            )
        ],
        route_patterns=["清晖园 -> 华盖路步行街"],
        food_keywords=["双皮奶"],
        tips=["节假日注意排队"],
        avoid_notes=["网红店评价两极分化"],
        amap_query_hints=["清晖园", "华盖路步行街", "双皮奶"],
    )

    monkeypatch.setattr(xhs_tools, "_run_xhs_json", _fake_run)
    monkeypatch.setattr(xhs_tools, "build_llm", make_fake_build_llm(structured=brief))

    out = await tools.research_xhs_travel_guide.ainvoke({
        "city": "顺德",
        "days": 1,
        "travel_style": "美食慢游",
        "keywords": ["避雷"],
        "max_notes": 2,
        "include_comments": True,
        "analyze_images": False,
    })

    assert out["ok"] is True
    assert out["data"]["recommended_places"][0]["name"] == "清晖园"
    assert out["data"]["time_suggestions"][0]["time"] == "09:00"
    assert out["data"]["amap_query_hints"] == ["清晖园", "华盖路步行街", "双皮奶"]
    assert out["meta"]["source_note_count"] == 2
    assert calls == [
        ["search", "顺德旅游攻略", "--sort", "popular", "--type", "all", "--page", "1"],
        ["read", "note-1"],
        ["comments", "note-1"],
        ["read", "note-2"],
        ["comments", "note-2"],
    ]


@pytest.mark.asyncio
async def test_research_xhs_travel_guide_includes_image_analysis_in_brief_payload(monkeypatch):
    run_calls = []
    llm_calls = []

    async def _fake_run(args):
        run_calls.append(args)
        if args[0] == "search":
            return {"ok": True, "data": {"items": [{"note_id": "note-1"}]}}
        if args[0] == "read":
            return {
                "ok": True,
                "data": {
                    "items": [{
                        "note_card": {
                            "title": "顺德旅游攻略",
                            "desc": "正文提到清晖园。",
                            "image_list": [{"url_default": "https://sns-img-qc.xhscdn.com/a.jpg"}],
                        }
                    }]
                },
            }
        return {"ok": True, "data": {}}

    async def _fake_analyze(target, note, *, max_images):
        return {
            "target": target,
            "image_count": 1,
            "visible_text": ["清晖园 09:00"],
            "places": ["清晖园"],
            "foods": ["双皮奶"],
            "route_or_time_clues": ["上午人少"],
            "tips": ["图片信息待地图校验"],
            "confidence": "high",
            "warnings": [],
            "image_urls": ["https://sns-img-qc.xhscdn.com/a.jpg"],
        }

    brief = xhs_tools.XhsTravelBrief(
        city="顺德",
        summary="图片和正文都支持上午去清晖园。",
        visual_clues=["图片文字显示清晖园 09:00"],
        amap_query_hints=["清晖园", "双皮奶"],
    )

    class _CaptureRunnable:
        async def ainvoke(self, messages, **_kwargs):
            llm_calls.append(messages)
            return brief

    class _CaptureLLM:
        def with_structured_output(self, *_args, **_kwargs):
            return _CaptureRunnable()

    monkeypatch.setattr(xhs_tools, "_run_xhs_json", _fake_run)
    monkeypatch.setattr(xhs_tools, "_analyze_xhs_note_images", _fake_analyze)
    monkeypatch.setattr(xhs_tools, "build_llm", lambda *_a, **_k: _CaptureLLM())

    out = await tools.research_xhs_travel_guide.ainvoke({
        "city": "顺德",
        "days": 1,
        "travel_style": "",
        "keywords": [],
        "max_notes": 1,
        "include_comments": False,
        "analyze_images": True,
        "max_images_per_note": 1,
    })

    payload = json.loads(llm_calls[0][1].content)
    assert payload["notes"][0]["image_analysis"]["places"] == ["清晖园"]
    assert payload["notes"][0]["image_analysis"]["foods"] == ["双皮奶"]
    assert out["data"]["visual_clues"] == ["图片文字显示清晖园 09:00"]
    assert out["meta"]["image_analysis_count"] == 1
    assert run_calls[0] == ["search", "顺德旅游攻略", "--sort", "popular", "--type", "all", "--page", "1"]


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

    monkeypatch.setattr("app.agent.tools.trip.amap.search_poi", _search_poi)

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
    monkeypatch.setattr("app.agent.tools.trip.amap.search_poi", _boom)
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
    assert {item["name"] for item in out["day_plans"][0]["items"] if item["type"] == "attraction"} == {"故宫", "天坛"}
    assert "daily_centers" in out


@pytest.mark.asyncio
async def test_assemble_itinerary_success_uses_note_enrichment_payload(fake_amap, monkeypatch, tmp_path):
    calls = []
    fake = DayPlans(days=[{"day": 1, "items": [
        {"type": "attraction", "name": "祖庙", "poi_id": "p1", "cost": 20}]}])
    monkeypatch.setattr(
        "app.agent.tools.itinerary.build_llm",
        lambda *_a, **_k: _CapturingStructuredLLM(fake, calls),
    )
    monkeypatch.setenv("CHECKPOINT_DB_PATH", str(tmp_path / "checkpoints.sqlite"))
    from app.core.config import get_settings
    get_settings.cache_clear()

    await tools.assemble_itinerary.ainvoke({
        "city": "佛山",
        "days": 1,
        "attractions": [
            {"name": "祖庙", "poi_id": "p1", "lng": 113.11351, "lat": 23.028945, "rating": 5.0},
            {"name": "岭南天地", "poi_id": "p2", "lng": 113.11519, "lat": 23.028895, "rating": 4.8},
        ],
        "restaurants": [{"name": "民信老铺", "poi_id": "r1", "lng": 113.114509, "lat": 23.031653}],
        "weather": {"text": "晴"},
        "start_date": "2026-07-01",
        "num_people": 2,
        "budget_advice": {"over_amount": 100.0},
    })
    get_settings.cache_clear()

    payload = json.loads(calls[0][1].content)
    assert set(payload) == {"day_plans", "weather", "instruction"}
    assert "skeleton" not in payload
    assert "restaurants" not in payload
    assert "budget_advice" not in payload
    assert "只润色 note 字段" in payload["instruction"]
    assert payload["day_plans"][0]["weather"] == {"text": "晴", "temp": "", "is_rainy": False}
    assert any(
        item["type"] == "meal" and item["name"] == "民信老铺"
        for item in payload["day_plans"][0]["items"]
    )
    assert payload["weather"] == {"text": "晴"}


@pytest.mark.asyncio
async def test_assemble_itinerary_success_only_merges_matching_llm_notes(fake_amap, monkeypatch, tmp_path):
    fake = DayPlans(days=[{"day": 1, "items": [
        {
            "type": "attraction",
            "name": "祖庙",
            "poi_id": "p1",
            "location": {"lng": 999, "lat": 999},
            "note": "适合雨天慢逛。",
            "cost": 999,
        },
        {
            "type": "attraction",
            "name": "不存在景点",
            "poi_id": "fake",
            "location": {"lng": 0, "lat": 0},
            "note": "must ignore",
        },
    ]}])
    monkeypatch.setattr("app.agent.tools.itinerary.build_llm", make_fake_build_llm(structured=fake))
    monkeypatch.setenv("CHECKPOINT_DB_PATH", str(tmp_path / "checkpoints.sqlite"))
    from app.core.config import get_settings
    get_settings.cache_clear()

    out = await tools.assemble_itinerary.ainvoke({
        "city": "佛山",
        "days": 1,
        "attractions": [
            {"name": "祖庙", "poi_id": "p1", "lng": 113.11351, "lat": 23.028945, "rating": 5.0},
            {"name": "岭南天地", "poi_id": "p2", "lng": 113.11519, "lat": 23.028895, "rating": 4.8},
        ],
        "restaurants": [
            {"name": "民信老铺", "poi_id": "r1", "lng": 113.114509, "lat": 23.031653},
        ],
        "weather": {"text": "雷阵雨", "temp": "26~32℃", "is_rainy": True},
    })
    get_settings.cache_clear()

    items = out["day_plans"][0]["items"]
    attractions = [item for item in items if item["type"] == "attraction"]
    assert {item["name"] for item in attractions} == {"祖庙", "岭南天地"}
    zumiao = next(item for item in attractions if item["poi_id"] == "p1")
    assert zumiao["location"] == {"lng": 113.11351, "lat": 23.028945}
    assert zumiao["cost"] == 0.0
    assert zumiao["note"] == "雨天适当放慢节奏。"
    assert all(item["poi_id"] != "fake" for item in items)


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
async def test_assemble_itinerary_degrades_to_skeleton_when_soft_fill_fails(fake_amap, monkeypatch, tmp_path):
    monkeypatch.setattr("app.agent.tools.itinerary.build_llm", lambda *_a, **_k: _FailingStructuredLLM())
    monkeypatch.setenv("CHECKPOINT_DB_PATH", str(tmp_path / "checkpoints.sqlite"))
    from app.core.config import get_settings
    get_settings.cache_clear()

    out = await tools.assemble_itinerary.ainvoke({
        "city": "佛山",
        "days": 1,
        "attractions": [
            {"name": "祖庙", "poi_id": "p1", "lng": 113.11351, "lat": 23.028945, "rating": 5.0},
            {"name": "岭南天地", "poi_id": "p2", "lng": 113.11519, "lat": 23.028895, "rating": 4.8},
        ],
        "restaurants": [
            {"name": "民信老铺", "poi_id": "r1", "lng": 113.114509, "lat": 23.031653},
        ],
        "weather": {"text": "雷阵雨", "temp": "26~32℃", "is_rainy": True},
    })
    get_settings.cache_clear()

    names = {item["name"] for item in out["day_plans"][0]["items"]}
    assert {"祖庙", "岭南天地", "民信老铺"} <= names
    assert out["day_plans"][0]["weather"]["text"] == "雷阵雨"
    assert out["day_plans"][0]["center"] == out["daily_centers"][0]
    assert all(item["start"] and item["end"] for item in out["day_plans"][0]["items"])
    assert out["warnings"] == ["itinerary_note_enrichment_failed"]


@pytest.mark.asyncio
async def test_assemble_itinerary_degrades_to_skeleton_when_llm_construction_fails(fake_amap, monkeypatch, tmp_path):
    monkeypatch.setattr("app.agent.tools.itinerary.build_llm", _RaisingBuildLLM())
    monkeypatch.setenv("CHECKPOINT_DB_PATH", str(tmp_path / "checkpoints.sqlite"))
    from app.core.config import get_settings
    get_settings.cache_clear()

    out = await tools.assemble_itinerary.ainvoke({
        "city": "佛山",
        "days": 1,
        "attractions": [
            {"name": "祖庙", "poi_id": "p1", "lng": 113.11351, "lat": 23.028945, "rating": 5.0},
            {"name": "岭南天地", "poi_id": "p2", "lng": 113.11519, "lat": 23.028895, "rating": 4.8},
        ],
        "restaurants": [
            {"name": "民信老铺", "poi_id": "r1", "lng": 113.114509, "lat": 23.031653},
        ],
        "weather": {"text": "雷阵雨", "temp": "26~32℃", "is_rainy": True},
    })
    get_settings.cache_clear()

    assert out["daily_centers"]
    assert out["day_plans"][0]["center"] == out["daily_centers"][0]
    assert out["day_plans"][0]["weather"]["text"] == "雷阵雨"
    assert {item["name"] for item in out["day_plans"][0]["items"]} >= {"祖庙", "岭南天地", "民信老铺"}
    assert out["warnings"] == ["itinerary_note_enrichment_failed"]


@pytest.mark.asyncio
async def test_assemble_itinerary_degrades_to_skeleton_when_soft_fill_output_invalid(fake_amap, monkeypatch, tmp_path):
    monkeypatch.setattr("app.agent.tools.itinerary.build_llm", lambda *_a, **_k: _InvalidStructuredLLM())
    monkeypatch.setenv("CHECKPOINT_DB_PATH", str(tmp_path / "checkpoints.sqlite"))
    from app.core.config import get_settings
    get_settings.cache_clear()

    out = await tools.assemble_itinerary.ainvoke({
        "city": "佛山",
        "days": 1,
        "attractions": [
            {"name": "祖庙", "poi_id": "p1", "lng": 113.11351, "lat": 23.028945, "rating": 5.0},
            {"name": "岭南天地", "poi_id": "p2", "lng": 113.11519, "lat": 23.028895, "rating": 4.8},
        ],
        "restaurants": [
            {"name": "民信老铺", "poi_id": "r1", "lng": 113.114509, "lat": 23.031653},
        ],
        "weather": {"text": "雷阵雨", "temp": "26~32℃", "is_rainy": True},
    })
    get_settings.cache_clear()

    names = {item["name"] for item in out["day_plans"][0]["items"]}
    assert {"祖庙", "岭南天地", "民信老铺"} <= names
    assert out["day_plans"][0]["weather"]["text"] == "雷阵雨"
    assert out["day_plans"][0]["center"] == out["daily_centers"][0]
    assert all(item["start"] and item["end"] for item in out["day_plans"][0]["items"])
    assert out["warnings"] == ["itinerary_note_enrichment_failed"]


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
