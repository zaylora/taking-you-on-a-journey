"""apply 单元节点（线性图 3/4）：薄壳，调 app.planning.apply.apply_operations。

把执行器的 applied/skipped 收进 refine_notes（render 据此诚实回报），其余字段原样写 state。
"""
from app.planning.apply import apply_operations


async def apply_node(state: dict, config=None) -> dict:
    res = await apply_operations(state.get("operations") or [],
                                 state.get("context") or {}, state, config)
    applied = res.pop("applied", [])
    skipped = res.pop("skipped", [])
    res["refine_notes"] = {"applied": applied, "skipped": skipped}
    return res
