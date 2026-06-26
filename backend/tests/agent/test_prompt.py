from app.agent.prompt import TRIP_AGENT_SYS
from app.agent.build import _TOOLS


def test_prompt_covers_key_directives():
    p = TRIP_AGENT_SYS
    # Prompt 只保留业务约束；具体工具名和参数格式交给注册的 tool schema。
    for kw in ("预算", "信息不足", "最终确认", "不要把对象或数组转成字符串"):
        assert kw in p, f"系统提示缺少关键指引：{kw}"
    assert len(p) > 200


def test_prompt_does_not_duplicate_registered_tool_catalog():
    p = TRIP_AGENT_SYS
    tool_names = {getattr(t, "name", "") for t in _TOOLS}
    leaked = sorted(name for name in tool_names if name and name in p)
    assert "可用工具" not in p
    assert leaked == []


def test_prompt_asks_for_missing_info_without_special_clarify_tool():
    p = TRIP_AGENT_SYS
    tool_names = {getattr(t, "name", "") for t in _TOOLS}
    assert "ask_user" not in tool_names
    assert "ask_user" not in p
    assert "澄清" not in p
    assert "直接回复提问" in p
