"""enrich_duration 节点：分天前给候选景点估「建议游玩时长」visit_minutes。

配了 Tavily key 时，用绑定 Tavily 工具的 agent 联网研究知名景点该玩多久，
返回结构化 {poi_id: minutes}；未配或失败时全部用静态类型表兜底（attraction_minutes）。
visit_minutes 是供 itinerary 算法消费的硬数据，不进 LLM 软填。
"""
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.graph.nodes.time_budget import attraction_minutes
from app.llm.factory import build_llm
from app.tools.web_search import build_tavily_tool


class _Duration(BaseModel):
    poi_id: str = Field(description="景点 poi_id，原样回填")
    minutes: int = Field(description="建议游玩时长（分钟，整数）")


class _Durations(BaseModel):
    items: list[_Duration] = Field(default_factory=list)


_SYS = (
    "你是行程时长估算助手。给定景点列表（name + poi_id），估每个景点的建议游玩时长（分钟）。"
    "可用联网工具查证知名景点（如故宫约一天、小观景台约半小时）。"
    "只返回 poi_id 与整数分钟，不要编造 poi_id。"
)


def apply_durations(attractions: list[dict], duration_map: dict[str, int]) -> list[dict]:
    """把 duration_map（poi_id→分钟）写入每个景点的 visit_minutes；缺失用静态表兜底。纯函数。"""
    out = []
    for a in attractions:
        m = duration_map.get(a.get("poi_id"))
        merged = dict(a)
        merged["visit_minutes"] = int(m) if isinstance(m, (int, float)) and m > 0 else attraction_minutes(a)
        out.append(merged)
    return out


async def enrich_duration(state, config) -> dict:
    attractions = state.get("attractions", []) or []
    if not attractions:
        return {"attractions": attractions}

    tool = build_tavily_tool()
    duration_map: dict[str, int] = {}
    if tool is not None:
        try:
            llm = build_llm(temperature=0).bind_tools([tool])
            payload = [{"name": a.get("name", ""), "poi_id": a.get("poi_id", "")}
                       for a in attractions]
            # 先让模型（可调用 Tavily）研究，再用结构化输出收口
            research = await llm.ainvoke([
                SystemMessage(content=_SYS),
                HumanMessage(content=str(payload)),
            ], config=config)
            extractor = build_llm(temperature=0).with_structured_output(
                _Durations, method="function_calling")
            result = await extractor.ainvoke([
                SystemMessage(content="把下面内容整理成 poi_id→minutes 列表。"),
                HumanMessage(content=str(getattr(research, "content", "")) or str(payload)),
            ], config=config)
            duration_map = {d.poi_id: d.minutes for d in result.items if d.minutes > 0}
        except Exception:  # noqa: BLE001 —— 联网/解析失败，全静态表兜底
            duration_map = {}

    return {"attractions": apply_durations(attractions, duration_map)}
