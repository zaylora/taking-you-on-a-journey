"""collect_context：按 operations 类型确定性地预取数据（纯能力函数，不进图）。

设计 §8 的精简落地：仅 replace_plan 需要全量池（喂 OR-Tools）；局部 op 的检索
（add_poi/replace_poi/set_region）由 apply 复用的 refine handler 现场完成，故此处
对局部 op 不取数（返回空），避免重复检索与重写已测逻辑。
"""
import asyncio

from app.tools import amap


def _req(state: dict) -> dict:
    return state.get("normalized_req", {}) or {}


async def collect_context(operations: list[dict], state: dict, config=None) -> dict:
    """按需取数。当前仅 replace_plan 触发全量并发检索。"""
    empty = {"weather": {}, "attractions": [], "restaurants": []}
    replace = next((o for o in operations if o.get("op") == "replace_plan"), None)
    if replace is None:
        return empty

    req = {**_req(state), **(replace.get("requirements_patch") or {})}
    city = (req.get("city") or "").strip()
    prefs = req.get("preferences", {}) or {}
    attr_kw = prefs.get("travel") or prefs.get("theme") or "热门景点"
    food_kw = prefs.get("food") or "美食"
    if not city:
        return empty

    async def _weather():
        try:
            return await amap.get_weather(city)
        except Exception:  # noqa: BLE001
            return {}

    async def _attractions():
        try:
            return await amap.search_poi(city, attr_kw, "风景名胜")
        except Exception:  # noqa: BLE001
            return []

    async def _restaurants():
        try:
            return await amap.search_poi(city, food_kw, "餐饮")
        except Exception:  # noqa: BLE001
            return []

    w, a, r = await asyncio.gather(_weather(), _attractions(), _restaurants())
    return {"weather": w, "attractions": a, "restaurants": r}
