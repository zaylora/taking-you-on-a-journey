from datetime import datetime
from zoneinfo import ZoneInfo

from app.agent.prompt import TRIP_AGENT_SYS
from app.agent.build import _TOOLS
from app.agent.time_context import build_system_prompt


def test_prompt_covers_key_directives():
    p = TRIP_AGENT_SYS
    # Prompt 只保留业务约束；具体工具名和参数格式交给注册的 tool schema。
    for kw in ("预算", "信息不足", "最终确认", "不要把对象或数组转成字符串"):
        assert kw in p, f"系统提示缺少关键指引：{kw}"
    assert len(p) > 200


def test_dynamic_system_prompt_injects_current_time_snapshot():
    now = datetime(2026, 6, 27, 8, 9, 10, tzinfo=ZoneInfo("UTC"))
    p = build_system_prompt(timezone_name="Asia/Shanghai", now=now)

    assert "当前时间上下文" in p
    assert "当前日期: 2026-06-27" in p
    assert "当前时间: 16:09:10" in p
    assert "时区: Asia/Shanghai (UTC+08:00)" in p
    assert "先调用已注册的当前时间工具" in p
    assert "不要凭历史消息或模型记忆推断" in p


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
