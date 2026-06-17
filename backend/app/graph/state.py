"""图状态定义。messages 用 add_messages、clarify_history 用 add，避免多节点/多轮写覆盖。"""
from operator import add
from typing import Annotated

from typing_extensions import TypedDict
from langgraph.graph.message import add_messages


class TripState(TypedDict, total=False):
    # —— 沿用 ——
    query: str
    messages: Annotated[list, add_messages]
    summary: str

    # —— 结构化需求（dispatch 标准化产出 + clarify 累积）——
    city: str
    start_date: str
    days: int
    num_people: int
    preferences: dict
    budget: float
    normalized_req: dict

    # —— 需求澄清 ——
    clarify_history: Annotated[list, add]   # [{field, question, options, answer}]
    clarified: bool
    clarify_round: int

    # —— 并行检索产出（各写独立字段，避免写冲突）——
    weather: dict
    attractions: list
    restaurants: list
    transport: dict

    # —— 行程编排产出 ——
    daily_centers: list
    day_plans: list

    # —— M4 预留（注释占位）——
    # hotels: list
    # budget_check: dict
    # retry_count: int
