from app.agent.prompt import TRIP_AGENT_SYS
from app.agent.build import _TOOLS


def test_prompt_covers_key_directives():
    p = TRIP_AGENT_SYS
    # 必须提及关键工具与约束，确保 agent 知道能力边界
    for kw in ("finalize_plan", "compute_budget", "预算", "信息不足"):
        assert kw in p, f"系统提示缺少关键指引：{kw}"
    assert len(p) > 200


def test_prompt_asks_for_missing_info_without_special_clarify_tool():
    p = TRIP_AGENT_SYS
    tool_names = {getattr(t, "name", "") for t in _TOOLS}
    assert "ask_user" not in tool_names
    assert "ask_user" not in p
    assert "澄清" not in p
    assert "直接回复提问" in p
