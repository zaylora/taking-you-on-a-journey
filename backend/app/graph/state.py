"""图状态定义。

messages 必须用 add_messages reducer，否则多节点写 messages 会相互覆盖。
"""
from typing import Annotated

from typing_extensions import TypedDict
from langgraph.graph.message import add_messages


class TripState(TypedDict):
    # —— M1 使用 ——
    query: str                               # 用户原始输入
    messages: Annotated[list, add_messages]  # 消息累加（reducer 防覆盖）
    summary: str                             # summarize 输出文本

    # —— M2+ 预留字段（注释占位，不在 M1 路径上，按里程碑逐步启用）——
    # city: str                  # 目的地城市
    # start_date: str            # 出发日期
    # days: int                  # 天数
    # preferences: list[str]     # 偏好（亲子/美食/文艺…）
    # weather: dict              # weather 节点产出
    # attractions: list          # attractions 节点产出
    # restaurants: list          # restaurants 节点产出
    # transport: dict            # transport 节点产出
    # accommodation: list        # accommodation 节点产出（M4）
    # day_plans: list            # itinerary 节点编排的逐日行程
    # budget: dict               # budget_check 节点产出（M4）
