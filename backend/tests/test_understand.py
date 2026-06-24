import pytest

from app.graph.nodes.understand import understand
from app.graph.nodes.dispatch_agent import IntentResult
from app.graph.nodes.refine_ops import RefinePlan, Operation
from app.graph.nodes.dispatch import NormalizedReq
from tests.conftest import make_fake_build_llm


def _plan():
    return [{"day": 1, "items": [{"type": "attraction", "name": "越秀公园"}]}]


def _async_return(value):
    async def _f(*a, **k):
        return value
    return _f


async def test_qa_produces_answer_only(monkeypatch):
    # 无 plan 时规则判定为 plan_new；要测 qa，给 has_plan 且问句
    out = await understand({"query": "第二天为什么这么赶？", "day_plans": _plan()}, None)
    assert out["last_intent"] == "qa"
    assert out["operations"][0]["op"] == "answer_only"
    assert out["operations"][0]["question"] == "第二天为什么这么赶？"


async def test_refine_produces_operations_with_preflight_patch(monkeypatch):
    plan = RefinePlan(operations=[Operation(op="set_region", day=1, area="黄埔")])
    monkeypatch.setattr("app.graph.nodes.understand.build_llm", make_fake_build_llm(structured=plan))
    out = await understand(
        {"query": "把第一天改成黄埔", "day_plans": _plan(),
         "normalized_req": {"city": "广州"}}, None)
    assert out["last_intent"] == "refine_existing"
    op = out["operations"][0]
    assert op["op"] == "set_region" and op["requirements_patch"]["city"] == "广州"


async def test_refine_unparseable_routes_to_answer_only(monkeypatch):
    plan = RefinePlan(operations=[], clarification="你想把第几天换到哪里？")
    monkeypatch.setattr("app.graph.nodes.understand.build_llm", make_fake_build_llm(structured=plan))
    out = await understand({"query": "改一下那个", "day_plans": _plan()}, None)
    assert out["last_intent"] == "qa"
    assert out["operations"][0]["op"] == "answer_only"
    assert out["refine_clarification"].startswith("你想")


async def test_plan_new_no_gaps_produces_replace_plan(monkeypatch):
    norm = NormalizedReq(city="广州", days=3, num_people=2, budget=5000.0)
    monkeypatch.setattr("app.graph.nodes.understand.build_llm", make_fake_build_llm(structured=norm))
    # 无缺口：桩 _evaluate_gaps 返回空
    monkeypatch.setattr("app.graph.nodes.understand._evaluate_gaps",
                        _async_return([]))
    out = await understand({"query": "去广州玩3天"}, None)   # 无 day_plans → plan_new
    assert out["last_intent"] == "plan_new"
    op = out["operations"][0]
    assert op["op"] == "replace_plan"
    assert op["requirements_patch"]["city"] == "广州" and op["requirements_patch"]["days"] == 3
    assert out["city"] == "广州"
