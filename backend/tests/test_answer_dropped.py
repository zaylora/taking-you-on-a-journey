"""answer 节点把 dropped_attractions 纳入 QA 上下文，便于回答"为什么没排某景点"。"""
from app.graph.nodes import answer as answer_mod


async def test_answer_payload_includes_dropped(monkeypatch):
    captured = {}

    class _FakeLLM:
        async def ainvoke(self, messages, config=None):
            captured["user"] = messages[1]["content"]

            class _R:
                content = "因时间有限未安排该景点"
            return _R()

    monkeypatch.setattr(answer_mod, "build_llm", lambda *a, **k: _FakeLLM())

    state = {
        "query": "为什么没有沙面岛",
        "day_plans": [],
        "dropped_attractions": [{"name": "沙面岛", "rating": 3.2, "reason": "评分较低"}],
    }
    out = await answer_mod.answer(state, config={})
    # dropped 信息进入了送给 LLM 的 payload
    assert "沙面岛" in captured["user"]
    assert out["summary"] == "因时间有限未安排该景点"
    assert out["changed_days"] == []
