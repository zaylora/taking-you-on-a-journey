"""M2 端到端测试：模糊输入 → session+clarify；同 thread resume → final。
interrupt 现由 understand 节点抛出（understand 内 while 循环调 _evaluate_gaps）。
"""
import json
import re


def _stub_except_clarify(monkeypatch):
    """understand 内 _evaluate_gaps 按 clarify_history 变化产生 gap → interrupt。
    其余节点打桩：understand.build_llm 返回 NormalizedReq，render.build_llm 流式。
    """
    from app.graph.nodes import understand as u, render as r
    from app.graph.nodes.clarify import Gap
    from app.graph.nodes.dispatch import NormalizedReq
    from app.graph.nodes.itinerary import DayPlans, DayPlan, PlanItem, Location, DayWeather
    from app.itinerary import soft_fill as sf
    from tests.conftest import make_fake_build_llm

    async def eval_gaps(state, config=None):
        if state.get("clarify_history"):
            return []  # 已答 → 放行
        return [Gap(field="city", question="去哪个城市？", options=["成都", "北京"])]
    # understand 直接导入 _evaluate_gaps，须 patch understand 模块属性
    monkeypatch.setattr(u, "_evaluate_gaps", eval_gaps)
    # 新链路：understand.build_llm 承载标准化 LLM 调用
    monkeypatch.setattr(u, "build_llm", make_fake_build_llm(
        structured=NormalizedReq(city="成都", days=1)))
    monkeypatch.setattr(sf, "build_llm", make_fake_build_llm(structured=DayPlans(days=[
        DayPlan(day=1, center=Location(lng=104.0, lat=30.6),
                items=[PlanItem(type="attraction", name="武侯祠")])])))
    # 新链路：token 由 render 节点冒泡
    monkeypatch.setattr(r, "build_llm", make_fake_build_llm(tokens=["第一天", "：武侯祠"]))


def test_clarify_then_resume_to_final(client, fake_amap, monkeypatch):
    _stub_except_clarify(monkeypatch)
    first = client.post("/api/chat", json={"message": "我想出去玩"}).text
    assert "event: session" in first
    assert "event: clarify" in first
    tid = re.search(r'"thread_id":\s*"([0-9a-f]+)"', first).group(1)

    second = client.post("/api/chat", json={"message": "成都", "thread_id": tid}).text
    assert "event: final" in second
    assert "武侯祠" in second
    # resume 从 understand 节点 interrupt 处恢复，不重走 memory 节点
    assert '"node": "memory"' not in second
    # 新链路：dispatch_agent 不再作为独立节点，不会出现 node_start 事件
    assert '"node": "dispatch_agent"' not in second
