from app.graph.nodes.routing import route_after_plan, route_after_accommodation
from app.graph.nodes.answer import answer


def test_route_after_plan_hotel_goes_accommodation():
    state = {"last_intent": "refine_existing",
             "refine_request": {"needs_accommodation": True, "needs_budget_recheck": True}}
    assert route_after_plan(state) == "accommodation"


def test_route_after_plan_budget_then_summarize():
    assert route_after_plan({"last_intent": "refine_existing",
                             "refine_request": {"needs_budget_recheck": True}}) == "budget"
    assert route_after_plan({"last_intent": "refine_existing",
                             "refine_request": {"needs_budget_recheck": False}}) == "summarize"


def test_route_after_plan_plan_new_unchanged():
    assert route_after_plan({"last_intent": "plan_new"}) == "accommodation"


async def test_answer_returns_clarification_verbatim_without_llm(monkeypatch):
    def _boom(*_a, **_k):
        raise AssertionError("澄清分支不应调用 LLM")
    monkeypatch.setattr("app.graph.nodes.answer.build_llm", _boom)
    out = await answer({"refine_clarification": "你想把第几天换到哪里？"}, None)
    assert out["summary"] == "你想把第几天换到哪里？"
    assert out["changed_days"] == []


def test_route_after_accommodation_unchanged():
    # refine_existing：按 needs_budget_recheck 决定 budget / summarize
    assert route_after_accommodation(
        {"last_intent": "refine_existing", "refine_request": {"needs_budget_recheck": True}}) == "budget"
    assert route_after_accommodation(
        {"last_intent": "refine_existing", "refine_request": {"needs_budget_recheck": False}}) == "summarize"
