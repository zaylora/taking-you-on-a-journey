"""collect_context 单元节点（线性图 2/4）：薄壳，调 app.planning.context.collect_context。"""
from app.planning.context import collect_context


async def collect_context_node(state: dict, config=None) -> dict:
    ctx = await collect_context(state.get("operations") or [], state, config)
    return {"context": ctx}
