# -*- coding: utf-8 -*-
"""单元：_aggregate_messages 把 ReAct 一轮内多个 AIMessage 折叠成单条 assistant 消息。

回归点：旧实现逐条渲染 AIMessage，导致历史快照出现多条空气泡，与实时流
「单条消息内聚合工具链」形态不一致。
"""
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, SystemMessage

from app.api.sessions import _aggregate_messages


def _ai_with_tool_calls(content, tools):
    return AIMessage(
        content=content,
        tool_calls=[{"name": t, "args": {}, "id": f"call_{i}"} for i, t in enumerate(tools)],
    )


def test_multi_ai_round_collapses_into_single_assistant():
    messages = [
        HumanMessage(content="帮我规划成都3天"),
        _ai_with_tool_calls("", ["get_weather", "search_attractions"]),
        ToolMessage(content="晴", tool_call_id="call_0"),
        _ai_with_tool_calls("", ["plan_route"]),
        ToolMessage(content="路线OK", tool_call_id="call_0"),
        AIMessage(content="这是为你规划的3天行程。"),
    ]

    result = _aggregate_messages(messages)

    assert len(result) == 2
    assert result[0] == {"role": "user", "content": "帮我规划成都3天", "kind": "text"}

    assistant = result[1]
    assert assistant["role"] == "assistant"
    assert assistant["content"] == "这是为你规划的3天行程。"
    tools = [s["tool"] for s in assistant["tool_steps"]]
    assert tools == ["get_weather", "search_attractions", "plan_route"]
    assert all(s["status"] == "done" for s in assistant["tool_steps"])


def test_human_message_starts_new_assistant_round():
    messages = [
        HumanMessage(content="第一问"),
        AIMessage(content="第一答"),
        HumanMessage(content="第二问"),
        _ai_with_tool_calls("", ["get_weather"]),
        AIMessage(content="第二答"),
    ]

    result = _aggregate_messages(messages)

    assert [m["role"] for m in result] == ["user", "assistant", "user", "assistant"]
    assert result[1]["content"] == "第一答"
    assert result[1]["tool_steps"] == []
    assert result[3]["content"] == "第二答"
    assert [s["tool"] for s in result[3]["tool_steps"]] == ["get_weather"]


def test_system_and_tool_messages_skipped():
    messages = [
        SystemMessage(content="你是助手"),
        HumanMessage(content="你好"),
        ToolMessage(content="工具输出", tool_call_id="x"),
        AIMessage(content="你好呀"),
    ]

    result = _aggregate_messages(messages)

    assert [m["role"] for m in result] == ["user", "assistant"]
    assert result[1]["content"] == "你好呀"


def test_summarization_human_message_skipped():
    messages = [
        HumanMessage(
            content="Here is a summary of the conversation to date:\n\n用户想去广州。",
            additional_kwargs={"lc_source": "summarization"},
        ),
        HumanMessage(content="有没有推荐吃的店铺呢？广州和顺德"),
        AIMessage(content="有的。"),
    ]

    result = _aggregate_messages(messages)

    assert [m["role"] for m in result] == ["user", "assistant"]
    assert result[0]["content"] == "有没有推荐吃的店铺呢？广州和顺德"
