# -*- coding: utf-8 -*-
"""ReAct Agent 状态：继承 create_agent 的 AgentState，叠加旅行业务字段。

业务字段由 tool 经 Command(update=...) 写、InjectedState 读，stream 层读出供 SSE。
messages 由 AgentState 提供（add_messages reducer），无需重复声明。
"""
from typing import Annotated

from langchain.agents import AgentState

from app.agent.reducers import merge_xhs_sources


class TripState(AgentState):
    # 当前会话里的结构化行程，供规划工具更新、前端展示和后续局部修改复用。
    day_plans: list
    # 本轮工具调用实际改动的日期索引，用于 SSE 只通知前端刷新受影响的天。
    changed_days: list
    # 行程版本号，每次成功写入计划时递增，帮助前端区分新旧计划。
    plan_version: int
    # 预算核算结果，通常由预算工具写入，供最终回复和前端预算面板读取。
    budget_check: dict
    # Agent 内部重试计数，避免同一轮规划在校验失败后无限重试。
    retry_count: int
    # 会话摘要，压缩历史上下文后继续提供用户偏好和已定约束。
    summary: str
    # 需要用户补充信息时写入的澄清问题，stream 层会转成 clarify 事件。
    clarification_request: dict
    # 带 reducer：同一 step 多个 xhs tool 各写增量时由 reducer 合并去重，避免并发写冲突
    xhs_sources: Annotated[list, merge_xhs_sources]
