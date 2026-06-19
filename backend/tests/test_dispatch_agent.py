import pytest

from app.graph.nodes.dispatch_agent import (
    dispatch_agent, route_after_dispatch, reset_for_plan_new,
    _parse_refine, _refine_flags, IntentResult,
)
from app.graph.nodes.dispatch import NormalizedReq
from tests.conftest import make_fake_build_llm


def test_refine_flags_by_op():
    assert _refine_flags("reorder") == {"needs_search": False, "needs_budget_recheck": False}
    assert _refine_flags("change_meal") == {"needs_search": True, "needs_budget_recheck": True}
    assert _refine_flags("relax") == {"needs_search": False, "needs_budget_recheck": True}
    assert _refine_flags("change_hotel") == {"needs_search": False, "needs_budget_recheck": True}


def test_parse_refine_extracts_op_day_and_flags():
    r = _parse_refine("第二天太赶了，少安排一个景点", target_day=2)
    assert r["op"] == "relax" and r["target_day"] == 2
    assert r["needs_search"] is False and r["needs_budget_recheck"] is True

    r2 = _parse_refine("把第一天晚餐换成火锅", target_day=1)
    assert r2["op"] == "change_meal" and r2["needs_search"] is True
    assert r2["constraints"].get("keywords") == "火锅"

    r3 = _parse_refine("预算改成3000", target_day=None)
    assert r3["op"] == "change_budget" and r3["constraints"].get("budget") == 3000.0
    assert r3["needs_search"] is False


def test_route_after_dispatch_maps_intent():
    assert route_after_dispatch({"last_intent": "plan_new"}) == "plan_new"
    assert route_after_dispatch({"last_intent": "refine_existing"}) == "refine"
    assert route_after_dispatch({"last_intent": "qa"}) == "qa"
    assert route_after_dispatch({}) == "plan_new"


def test_reset_for_plan_new_clears_dirty_state():
    out = reset_for_plan_new({"clarified": True, "retry_count": 2, "day_plans": [{"day": 1}]})
    assert out["clarified"] is False and out["retry_count"] == 0
    assert out["day_plans"] == [] and out["changed_days"] == []


@pytest.mark.asyncio
async def test_first_turn_is_plan_new_and_normalizes(monkeypatch):
    # 无 day_plans → 规则直接判 plan_new（不调 IntentResult LLM）；只调 NormalizedReq
    monkeypatch.setattr("app.graph.nodes.dispatch_agent.build_llm",
                        make_fake_build_llm(structured=NormalizedReq(city="成都", days=2, num_people=2, budget=4000)))
    out = await dispatch_agent({"query": "成都2天2人预算4000"}, None)
    assert out["last_intent"] == "plan_new"
    assert out["city"] == "成都" and out["days"] == 2
    assert out["normalized_req"]["city"] == "成都"


@pytest.mark.asyncio
async def test_refine_turn_parses_by_rule_without_llm(monkeypatch):
    # 已有 day_plans + "第二天少一个" → 规则判 refine_existing 且规则解析 op，不调任何 LLM
    def _boom(*_a, **_k):
        raise AssertionError("refine 解析不应调用 LLM")
    monkeypatch.setattr("app.graph.nodes.dispatch_agent.build_llm", _boom)
    out = await dispatch_agent(
        {"query": "第二天太赶了，少安排一个景点", "day_plans": [{"day": 1}, {"day": 2}]}, None)
    assert out["last_intent"] == "refine_existing"
    assert out["refine_request"]["op"] == "relax"
    assert out["refine_request"]["target_day"] == 2
    assert out["refine_request"]["needs_budget_recheck"] is True


@pytest.mark.asyncio
async def test_qa_turn_only_sets_intent(monkeypatch):
    def _boom(*_a, **_k):
        raise AssertionError("qa 不应调用 LLM")
    monkeypatch.setattr("app.graph.nodes.dispatch_agent.build_llm", _boom)
    out = await dispatch_agent(
        {"query": "刚才那个行程适合带老人吗？", "day_plans": [{"day": 1}]}, None)
    assert out["last_intent"] == "qa"
    assert "normalized_req" not in out and "refine_request" not in out
