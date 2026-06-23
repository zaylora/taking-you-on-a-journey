import pytest

from app.graph.nodes.dispatch_agent import (
    dispatch_agent, route_after_dispatch, reset_for_plan_new, IntentResult,
)
from app.graph.nodes.dispatch import NormalizedReq
from app.graph.nodes.refine_ops import RefinePlan, Operation
from tests.conftest import make_fake_build_llm


def test_route_after_dispatch_maps_intent():
    assert route_after_dispatch({"last_intent": "plan_new"}) == "plan_new"
    assert route_after_dispatch({"last_intent": "refine_existing"}) == "refine"
    assert route_after_dispatch({"last_intent": "qa"}) == "answer"
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
async def test_qa_turn_only_sets_intent(monkeypatch):
    def _boom(*_a, **_k):
        raise AssertionError("qa 不应调用 LLM")
    monkeypatch.setattr("app.graph.nodes.dispatch_agent.build_llm", _boom)
    out = await dispatch_agent(
        {"query": "刚才那个行程适合带老人吗？", "day_plans": [{"day": 1}]}, None)
    assert out["last_intent"] == "qa"
    assert "normalized_req" not in out and "refine_request" not in out


@pytest.mark.asyncio
async def test_refine_turn_parses_to_operations_via_llm(monkeypatch):
    plan = RefinePlan(operations=[Operation(op="set_region", day=1, area="黄埔")])
    monkeypatch.setattr("app.graph.nodes.dispatch_agent.build_llm",
                        make_fake_build_llm(structured=plan))
    out = await dispatch_agent(
        {"query": "把第一天改成黄埔", "day_plans": [{"day": 1, "items": []}]}, None)
    assert out["last_intent"] == "refine_existing"
    ops = out["refine_request"]["operations"]
    assert ops[0]["op"] == "set_region" and ops[0]["area"] == "黄埔" and ops[0]["day"] == 1


@pytest.mark.asyncio
async def test_refine_no_ops_with_clarification_routes_to_qa(monkeypatch):
    plan = RefinePlan(operations=[], clarification="你想把第几天换到哪里？")
    monkeypatch.setattr("app.graph.nodes.dispatch_agent.build_llm",
                        make_fake_build_llm(structured=plan))
    out = await dispatch_agent(
        {"query": "改一下那个", "day_plans": [{"day": 1, "items": []}]}, None)
    assert out["last_intent"] == "qa"
    assert out["refine_clarification"].startswith("你想")
    assert "refine_request" not in out
