# -*- coding: utf-8 -*-
"""单元：_aggregate_messages 把 ReAct 一轮内多个 AIMessage 折叠成单条 assistant 消息。

回归点：旧实现逐条渲染 AIMessage，导致历史快照出现多条空气泡，与实时流
「单条消息内聚合工具链」形态不一致。
"""
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, SystemMessage

from app.api.sessions import _aggregate_messages
from app.api.sessions import _messages_with_xhs_sources
from app.services.message_history import reconstruct_messages_from_history
from app.services.message_history import build_segments, segments_for_assistant


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


def test_tool_step_labels_use_tool_call_args():
    messages = [
        HumanMessage(content="帮我做顺德攻略"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "research_xhs_travel_guide",
                    "args": {"city": "顺德", "days": 2, "travel_style": "美食"},
                    "id": "call_0",
                },
                {
                    "name": "search_restaurants",
                    "args": {"city": "佛山", "keywords": "顺德早茶"},
                    "id": "call_1",
                },
            ],
        ),
        AIMessage(content="好了。"),
    ]

    result = _aggregate_messages(messages)

    assert [step["label"] for step in result[1]["tool_steps"]] == [
        "研究顺德2天美食小红书攻略",
        "搜索佛山餐厅：顺德早茶",
    ]


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


def test_messages_with_xhs_sources_appends_to_latest_assistant_once():
    messages = [
        {"role": "user", "content": "帮我做顺德攻略", "kind": "text"},
        {
            "role": "assistant",
            "content": "这是顺德攻略。",
            "kind": "text",
            "tool_steps": [{"tool": "research_xhs_travel_guide", "label": "研究小红书攻略", "status": "done"}],
        },
    ]
    sources = [{"title": "顺德一日游", "url": "https://www.xiaohongshu.com/explore/note-1"}]

    result = _messages_with_xhs_sources(messages, sources)

    assert result[0]["role"] == "user"
    assert result[1]["content"] == (
        "这是顺德攻略。\n\n## 笔记来源\n"
        "- [顺德一日游](https://www.xiaohongshu.com/explore/note-1)"
    )
    assert result[1]["tool_steps"] == messages[1]["tool_steps"]
    assert messages[1]["content"] == "这是顺德攻略。"


def test_messages_with_xhs_sources_does_not_duplicate_existing_sources():
    messages = [
        {"role": "assistant", "content": "已有正文。\n\n## 笔记来源\n- [A](https://x/1)", "kind": "text"},
    ]

    result = _messages_with_xhs_sources(messages, [{"title": "B", "url": "https://x/2"}])

    assert result[0]["content"] == "已有正文。\n\n## 笔记来源\n- [A](https://x/1)"


def test_reconstruct_messages_from_history_merges_user_final_content_and_full_tools():
    history_values = [
        {
            "messages": [
                AIMessage(
                    content="最终完整攻略。",
                    tool_calls=[{"name": "finalize_plan", "args": {}, "id": "latest"}],
                )
            ]
        },
        {
            "messages": [
                HumanMessage(content="帮我做广州两天旅行攻略"),
                _ai_with_tool_calls("", ["search_attractions", "search_restaurants", "get_weather"]),
                ToolMessage(content="工具结果", tool_call_id="call_0"),
                _ai_with_tool_calls("", ["plan_route", "assemble_itinerary", "finalize_plan"]),
            ]
        },
        {"messages": [HumanMessage(content="帮我做广州两天旅行攻略")]},
    ]

    result = reconstruct_messages_from_history(history_values)

    assert [m["role"] for m in result] == ["user", "assistant"]
    assert result[0]["content"] == "帮我做广州两天旅行攻略"
    assert result[1]["content"] == "最终完整攻略。"
    assert [step["tool"] for step in result[1]["tool_steps"]] == [
        "search_attractions",
        "search_restaurants",
        "get_weather",
        "plan_route",
        "assemble_itinerary",
        "finalize_plan",
    ]


def test_reconstruct_messages_from_history_keeps_repeated_tool_calls():
    history_values = [
        {"messages": [AIMessage(content="最终答案。", tool_calls=[
            {"name": "finalize_plan", "args": {}, "id": "final"}
        ])]},
        {
            "messages": [
                HumanMessage(content="做攻略"),
                AIMessage(content="", tool_calls=[
                    {"name": "search_attractions", "args": {}, "id": "a1"},
                    {"name": "search_attractions", "args": {}, "id": "a2"},
                    {"name": "search_restaurants", "args": {}, "id": "r1"},
                    {"name": "search_restaurants", "args": {}, "id": "r2"},
                ]),
            ]
        },
    ]

    result = reconstruct_messages_from_history(history_values)

    assert [step["tool"] for step in result[1]["tool_steps"]] == [
        "search_attractions",
        "search_attractions",
        "search_restaurants",
        "search_restaurants",
        "finalize_plan",
    ]



def test_build_segments_interleaves_text_and_tools():
    messages = [
        AIMessage(content="我先查一下天气。", tool_calls=[
            {"name": "get_weather", "args": {"city": "成都"}, "id": "c0"},
        ]),
        ToolMessage(content="晴", tool_call_id="c0"),
        AIMessage(content="天气不错，再看看景点。", tool_calls=[
            {"name": "search_attractions", "args": {"city": "成都"}, "id": "c1"},
        ]),
        ToolMessage(content="武侯祠等", tool_call_id="c1"),
        AIMessage(content="这是你的成都行程。"),
    ]

    segments = build_segments(messages)

    assert segments == [
        {"kind": "text", "text": "我先查一下天气。"},
        {"kind": "tool", "tool": "get_weather", "label": "查询成都天气", "status": "done"},
        {"kind": "text", "text": "天气不错，再看看景点。"},
        {"kind": "tool", "tool": "search_attractions", "label": "搜索成都景点", "status": "done"},
        {"kind": "text", "text": "这是你的成都行程。"},
    ]


def test_build_segments_skips_empty_text_and_tool_messages():
    messages = [
        SystemMessage(content="你是助手"),
        AIMessage(content="", tool_calls=[{"name": "get_weather", "args": {}, "id": "c0"}]),
        ToolMessage(content="晴", tool_call_id="c0"),
        AIMessage(content="好了。"),
    ]

    segments = build_segments(messages)

    assert segments == [
        {"kind": "tool", "tool": "get_weather", "label": "查询天气", "status": "done"},
        {"kind": "text", "text": "好了。"},
    ]


def test_segments_for_assistant_returns_only_last_round():
    messages = [
        HumanMessage(content="第一问"),
        AIMessage(content="第一答"),
        HumanMessage(content="第二问"),
        AIMessage(content="第二答", tool_calls=[{"name": "get_weather", "args": {"city": "成都"}, "id": "c0"}]),
        ToolMessage(content="晴", tool_call_id="c0"),
        AIMessage(content="最终答"),
    ]
    segments = segments_for_assistant(messages)
    assert segments == [
        {"kind": "text", "text": "第二答"},
        {"kind": "tool", "tool": "get_weather", "label": "查询成都天气", "status": "done"},
        {"kind": "text", "text": "最终答"},
    ]


def test_segments_for_assistant_no_human_uses_all():
    messages = [
        AIMessage(content="直接答", tool_calls=[{"name": "get_weather", "args": {}, "id": "c0"}]),
        ToolMessage(content="晴", tool_call_id="c0"),
        AIMessage(content="收尾"),
    ]
    segments = segments_for_assistant(messages)
    assert segments == [
        {"kind": "text", "text": "直接答"},
        {"kind": "tool", "tool": "get_weather", "label": "查询天气", "status": "done"},
        {"kind": "text", "text": "收尾"},
    ]


def test_messages_with_xhs_sources_appends_to_last_text_segment():
    sources_md_marker = "## 笔记来源"
    messages = [
        {
            "role": "assistant",
            "content": "这是顺德攻略。",
            "kind": "text",
            "tool_steps": [],
            "segments": [{"kind": "text", "text": "这是顺德攻略。"}],
        },
    ]
    sources = [{"title": "顺德一日游", "url": "https://www.xiaohongshu.com/explore/note-1"}]

    result = _messages_with_xhs_sources(messages, sources)

    last_text = [s for s in result[0]["segments"] if s["kind"] == "text"][-1]
    assert sources_md_marker in last_text["text"]
    assert "note-1" in last_text["text"]
    assert sources_md_marker in result[0]["content"]
