from datetime import datetime
from zoneinfo import ZoneInfo

from app.agent import prompt
from app.agent.prompt import (
    ACCOMMODATION_SYS, CURRENT_TIME_CONTEXT_TEMPLATE, ITINERARY_SYS,
    TRIP_AGENT_SYS, TRIP_SUMMARY_PROMPT, XHS_RESEARCH_SYS,
)
from app.agent.build import _TOOLS
from app.agent.time_context import build_system_prompt


def test_prompt_covers_key_directives():
    p = TRIP_AGENT_SYS
    # Prompt 只保留业务约束；具体工具名和参数格式交给注册的 tool schema。
    for kw in ("预算", "信息不足", "最终确认", "不要把对象或数组转成字符串"):
        assert kw in p, f"系统提示缺少关键指引：{kw}"
    assert len(p) > 200


def test_prompt_requires_retrieval_for_recommendable_places():
    p = TRIP_AGENT_SYS

    for kw in ("推荐具体可到访地点", "餐厅", "店铺", "小红书", "高德"):
        assert kw in p
    for kw in ("标准名称", "地址", "poi_id", "经纬度", "不要编造坐标"):
        assert kw in p
    assert "不属于纯问答" in p
    assert "默认" in p
    assert "例外" in p
    assert "已有足够新的检索结果" in p


def test_prompt_prefers_xhs_guide_style_keywords():
    p = TRIP_AGENT_SYS

    for kw in ("攻略型描述", "顺德旅游攻略", "东京亲子游攻略", "避免只搜宽泛词"):
        assert kw in p


def test_prompt_uses_structured_sections_for_agent_policy():
    p = TRIP_AGENT_SYS

    for heading in (
        "## 角色",
        "## 判断流程",
        "## 工作流",
        "## 硬性约束",
        "## 回复要求",
    ):
        assert heading in p
    assert "先判断请求类型" in p
    assert "信息缺口" in p
    assert "证据来源分工" in p


def test_all_runtime_prompts_use_markdown_sections():
    prompts = [
        TRIP_AGENT_SYS,
        TRIP_SUMMARY_PROMPT,
        XHS_RESEARCH_SYS,
        ITINERARY_SYS,
        ACCOMMODATION_SYS,
        CURRENT_TIME_CONTEXT_TEMPLATE,
    ]

    assert all("## " in p for p in prompts)
    assert all("<role>" not in p and "</role>" not in p for p in prompts)


def test_dynamic_system_prompt_injects_current_time_snapshot():
    now = datetime(2026, 6, 27, 8, 9, 10, tzinfo=ZoneInfo("UTC"))
    p = build_system_prompt(timezone_name="Asia/Shanghai", now=now)

    assert "当前时间上下文" in p
    assert "当前日期: 2026-06-27" in p
    assert "当前时间: 16:09:10" in p
    assert "时区: Asia/Shanghai (UTC+08:00)" in p
    assert "先调用已注册的当前时间工具" in p
    assert "不要凭历史消息或模型记忆推断" in p


def test_runtime_prompts_are_colocated_in_prompt_module():
    assert prompt.TRIP_AGENT_SYS is TRIP_AGENT_SYS
    assert "长期上下文整理助手" in TRIP_SUMMARY_PROMPT
    assert "旅行攻略研究助手" in XHS_RESEARCH_SYS
    assert "行程文案润色助手" in ITINERARY_SYS
    assert "住宿规划助手" in ACCOMMODATION_SYS
    assert "当前时间上下文" in CURRENT_TIME_CONTEXT_TEMPLATE


def test_xhs_research_prompt_mentions_image_text_analysis():
    p = XHS_RESEARCH_SYS

    for kw in ("图片解析结果", "店名", "菜单", "营业时间", "待校验线索", "不确定性"):
        assert kw in p


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
