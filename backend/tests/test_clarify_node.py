import pytest
from app.graph.nodes import clarify as clarify_mod
from app.graph.nodes.clarify import route_after_clarify, ClarifyGaps, Gap


def test_route_after_clarify():
    assert route_after_clarify({"clarified": True}) == "dispatch"
    assert route_after_clarify({"clarified": False}) == "clarify"
    assert route_after_clarify({}) == "clarify"


@pytest.mark.asyncio
async def test_no_gaps_passes_through(monkeypatch):
    from tests.conftest import make_fake_build_llm
    monkeypatch.setattr(clarify_mod, "build_llm",
                        make_fake_build_llm(structured=ClarifyGaps(gaps=[])))
    out = await clarify_mod.clarify({"query": "成都3天2人爱吃辣预算2000", "clarify_round": 0}, None)
    assert out == {"clarified": True}


@pytest.mark.asyncio
async def test_round_cap_forces_passthrough(monkeypatch):
    from tests.conftest import make_fake_build_llm
    # 即使 LLM 还想追问，到达上限也直接放行
    monkeypatch.setattr(clarify_mod, "build_llm", make_fake_build_llm(
        structured=ClarifyGaps(gaps=[Gap(field="budget", question="预算？", options=[])])))
    out = await clarify_mod.clarify({"query": "x", "clarify_round": 4}, None)
    assert out == {"clarified": True}
