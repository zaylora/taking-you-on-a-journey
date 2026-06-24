from app.graph.nodes.render import render
from tests.conftest import make_fake_build_llm


async def test_render_clarification_verbatim_no_llm(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("澄清分支不应调用 LLM")
    monkeypatch.setattr("app.graph.nodes.render.build_llm", _boom)
    out = await render({"refine_clarification": "你想把第几天换到哪里？"}, None)
    assert out["summary"] == "你想把第几天换到哪里？"


async def test_render_summary_streams_day_plans(monkeypatch):
    monkeypatch.setattr("app.graph.nodes.render.build_llm", make_fake_build_llm(tokens=["成都", "攻略"]))
    out = await render({"operations": [{"op": "reorder", "day": 1}],
                        "day_plans": [{"day": 1, "items": []}],
                        "refine_notes": {"applied": ["第1天顺序已调整"], "skipped": []}}, None)
    assert out["summary"] == "成都攻略"


async def test_render_answer_only_streams_qa(monkeypatch):
    monkeypatch.setattr("app.graph.nodes.render.build_llm", make_fake_build_llm(tokens=["回答"]))
    out = await render({"operations": [{"op": "answer_only", "question": "为什么"}],
                        "day_plans": [{"day": 1, "items": []}],
                        "conversation_summary": "成都3天"}, None)
    assert out["summary"] == "回答"
