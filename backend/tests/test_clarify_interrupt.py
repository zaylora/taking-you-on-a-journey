"""M2 端到端测试：模糊输入 → session+clarify；同 thread resume → final。"""
import json
import re


def _stub_except_clarify(monkeypatch):
    """保留真实 clarify（触发 interrupt）：_evaluate_gaps 按 clarify_history 变化；其余节点打桩。"""
    from app.graph.nodes import clarify as c, dispatch_agent as d, itinerary as it, summarize as s
    from app.graph.nodes.clarify import Gap
    from app.graph.nodes.dispatch import NormalizedReq
    from app.graph.nodes.itinerary import DayPlans, DayPlan, PlanItem, Location, DayWeather
    from tests.conftest import make_fake_build_llm

    async def eval_gaps(state, config=None):
        if state.get("clarify_history"):
            return []  # 已答 → 放行
        return [Gap(field="city", question="去哪个城市？", options=["成都", "北京"])]
    monkeypatch.setattr(c, "_evaluate_gaps", eval_gaps)
    monkeypatch.setattr(d, "build_llm", make_fake_build_llm(
        structured=NormalizedReq(city="成都", days=1)))
    monkeypatch.setattr(it, "build_llm", make_fake_build_llm(structured=DayPlans(days=[
        DayPlan(day=1, center=Location(lng=104.0, lat=30.6),
                items=[PlanItem(type="attraction", name="武侯祠")])])))
    monkeypatch.setattr(s, "build_llm", make_fake_build_llm(tokens=["第一天", "：武侯祠"]))


def test_clarify_then_resume_to_final(client, fake_amap, monkeypatch):
    _stub_except_clarify(monkeypatch)
    first = client.post("/api/chat", json={"message": "我想出去玩"}).text
    assert "event: session" in first
    assert "event: clarify" in first
    tid = re.search(r'"thread_id":\s*"([0-9a-f]+)"', first).group(1)

    second = client.post("/api/chat", json={"message": "成都", "thread_id": tid}).text
    assert "event: final" in second
    assert "武侯祠" in second
    assert '"node": "memory"' not in second
    assert '"node": "dispatch_agent"' not in second
