"""summarize 节点（M2 升级）：按 day_plans 渲染逐日简体中文攻略，逐字流式。
⚠️ 必须 async + 接收 config + astream(..., config=config)，token 方能冒泡（M1 实测结论）。
"""
from langchain_core.runnables import RunnableConfig

from app.llm.factory import build_llm

_SYS = "你是旅行攻略撰写助手。请用简体中文，按天输出清晰、可读的逐日行程攻略，语气友好实用。"


async def summarize(state: dict, config: RunnableConfig) -> dict:
    day_plans = state.get("day_plans") or []
    if day_plans:
        user = f"请根据以下结构化逐日行程，写成中文攻略：\n{day_plans}"
    else:
        user = f"请根据用户需求给出中文旅行建议：{state.get('query', '')}"
    parts: list[str] = []
    async for chunk in build_llm().astream(
        [{"role": "system", "content": _SYS}, {"role": "user", "content": user}],
        config=config,
    ):
        if chunk.content:
            parts.append(chunk.content)
    text = "".join(parts)
    return {"summary": text}
