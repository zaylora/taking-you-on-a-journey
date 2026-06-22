# -*- coding: utf-8 -*-
"""LLM 软填：算法骨架 -> LLM 只补 start/end/cost/indoor/note -> 按 poi_id 合并。

几何（顺序/坐标/交通段）一律以骨架为准，LLM 即便乱动也被丢弃。软填失败降级骨架。
"""
from langchain_core.messages import HumanMessage, SystemMessage

from app.itinerary.schemas import DayPlans
from app.llm.factory import build_llm

_SYS = (
    "你是行程编排助手。下面给你的是已经排好顺序、坐标固定的逐日骨架（景点/餐饮/交通段都已确定）。"
    "你的唯一任务：为每个『景点』和『餐饮』项补充 start/end（HH:MM）、cost（人均元）、indoor（是否室内）、note（一句话）。"
    "严禁修改名称、坐标、顺序，严禁增删项，严禁改交通段。雨天优先把户外项标注合理。"
    "若项含 opentime（营业时间），设置 start/end 时务必落在营业时间内（避免早到未开/晚到已闭）。"
    "若输入含 budget_advice（上轮超支额），据此压低 cost 估计。"
    "按给定结构返回（poi_id/type 原样不动，只补软字段）。"
)

_SOFT_FIELDS = ("start", "end", "cost", "indoor", "note")


def merge_soft_fields(skeleton_days: list[dict], llm_days: list[dict]) -> list[dict]:
    """把 LLM 的软字段合并进算法骨架：按 day + poi_id 对齐非交通项，仅覆盖非空软字段；
    顺序、坐标、交通段一律以骨架为准。纯函数，不改输入。"""
    llm_by_day = {d.get("day"): d for d in llm_days}
    out = []
    for sd in skeleton_days:
        ld = llm_by_day.get(sd.get("day"), {}) or {}
        soft_by_poi = {it.get("poi_id"): it for it in ld.get("items", [])
                       if it.get("type") != "transport" and it.get("poi_id")}
        new_items = []
        for it in sd.get("items", []):
            merged = dict(it)
            if it.get("type") != "transport":
                src = soft_by_poi.get(it.get("poi_id"))
                if src:
                    for k in _SOFT_FIELDS:
                        v = src.get(k)
                        if v not in (None, ""):
                            merged[k] = v
            new_items.append(merged)
        nd = dict(sd)
        nd["items"] = new_items
        out.append(nd)
    return out


def build_soft_payload(skeleton_days: list, state: dict) -> dict:
    """构造软填 LLM 的输入：骨架（仅供补软字段）+ 天气 + 可选 budget_advice。纯函数，便于单测。"""
    payload = {
        "skeleton": [{"day": d["day"],
                      "items": [{"type": it["type"], "name": it.get("name", ""),
                                 "poi_id": it.get("poi_id", ""),
                                 **({"opentime": it["opentime"]} if it.get("opentime") else {})}
                                for it in d["items"]]}
                     for d in skeleton_days],
        "weather": state.get("weather", {}),
        "num_people": state.get("num_people", 1) or 1,
    }
    advice = state.get("budget_advice")
    if advice:
        payload["budget_advice"] = advice
    return payload


async def annotate_soft_fields(skeleton_days: list[dict], state: dict, config) -> list[dict]:
    """调 LLM 软填；失败则全用骨架默认。返回 merge 后的 day_plans。"""
    llm = build_llm(temperature=0).with_structured_output(DayPlans, method="function_calling")
    try:
        result = await llm.ainvoke([
            SystemMessage(content=_SYS),
            HumanMessage(content=str(build_soft_payload(skeleton_days, state))),
        ], config=config)
        llm_days = [d.model_dump(by_alias=True) for d in result.days]
    except Exception:  # noqa: BLE001 —— 软填失败不阻断，几何已就绪
        llm_days = []
    return merge_soft_fields(skeleton_days, llm_days)
