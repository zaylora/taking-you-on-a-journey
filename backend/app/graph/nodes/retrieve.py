"""retrieve 节点（M5 fix）：clarify 放行后的并行检索 fan-out 锚点。

本身不做事（pass-through），仅作为「clarify → 4 个检索子 Agent 并行」的单一上游，
让 LangGraph 从这里 fan-out 到 weather/attractions/restaurants/transport。
"""


async def retrieve(state, config) -> dict:
    return {}
