"""render 单元节点（线性图 4/4）：summarize + answer 合一。

- refine_clarification（understand 透传无法解析的反问）→ 原样返回，不调 LLM。
- answer_only / 无 day_plans → 基于会话与现有方案回答（流式）。
- 有 day_plans → 渲染逐日攻略（流式）+ 诚实回报 refine_notes 里的 skipped。

⚠️ 必须 async + astream(..., config=config)，token 才能冒泡；stream.py 放行 langgraph_node=="render"。
"""
from langchain_core.runnables import RunnableConfig

from app.llm.factory import build_llm

_SUMMARY_SYS = "你是旅行攻略撰写助手。请用简体中文，按天输出清晰、可读的逐日行程攻略，语气友好实用。"
_ANSWER_SYS = ("你是旅行助手。只基于当前会话摘要和已有行程回答用户问题，不要重新规划或修改 day_plans。"
               "若用户问及某景点为何未安排，可参考 dropped_attractions（含未排入景点及原因）说明。")


def _question(state: dict) -> str:
    for op in state.get("operations") or []:
        if op.get("op") == "answer_only":
            return op.get("question") or state.get("query", "")
    return state.get("query", "")


async def render(state: dict, config: RunnableConfig = None) -> dict:
    # 澄清分支：直接透传，不调 LLM
    clar = state.get("refine_clarification")
    if clar:
        return {"summary": clar}

    operations = state.get("operations") or []
    is_answer = any(o.get("op") == "answer_only" for o in operations)
    day_plans = state.get("day_plans") or []

    if is_answer or not day_plans:
        # QA 分支：基于会话摘要和现有行程回答问题
        sys = _ANSWER_SYS
        user = str({
            "question": _question(state),
            "conversation_summary": state.get("conversation_summary", ""),
            "day_plans": day_plans,
            "budget": state.get("budget_check", {}) or {},
            "dropped_attractions": state.get("dropped_attractions", []) or [],
        })
    else:
        # 攻略分支：渲染逐日行程 + 诚实回报 skipped
        notes = state.get("refine_notes") or {}
        extra = (f"\n本轮修改记录（applied/skipped）：{notes}"
                 f"\n若有 skipped 项，请如实简述未能完成的部分。") if notes else ""
        sys = _SUMMARY_SYS
        user = f"请根据以下结构化逐日行程，写成中文攻略：\n{day_plans}{extra}"

    parts: list[str] = []
    async for chunk in build_llm().astream(
        [{"role": "system", "content": sys}, {"role": "user", "content": user}],
        config=config,
    ):
        if chunk.content:
            parts.append(chunk.content)
    return {"summary": "".join(parts)}
