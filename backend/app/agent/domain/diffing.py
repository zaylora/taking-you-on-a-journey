"""changed_days 增量 diff：比对新旧 day_plans，确定性纯函数。

供 finalize_plan tool 在写入 day_plans 时计算前端增量重绘所需的 changed_days。
"""


def _item_fp(item: dict) -> str:
    return f"{item.get('type', '')}|{item.get('name', '')}|{item.get('poi_id', '')}"


def _hotel_fp(hotel: dict | None) -> str:
    if not hotel:
        return ""
    return f"{hotel.get('name', '')}|{hotel.get('poi_id', '')}"


def _day_fp(day_plan: dict) -> str:
    items = day_plan.get("items", []) or []
    items_fp = ";".join(_item_fp(it) for it in items)
    return f"{items_fp}#{_hotel_fp(day_plan.get('hotel'))}"


def diff_changed_days(old: list[dict], new: list[dict]) -> list[int]:
    """返回有变化的 day 号（升序）。新增/删除天也算变化。"""
    old_by_day = {d.get("day"): _day_fp(d) for d in (old or [])}
    new_by_day = {d.get("day"): _day_fp(d) for d in (new or [])}
    changed: set[int] = set()
    for day in set(old_by_day) | set(new_by_day):
        if old_by_day.get(day) != new_by_day.get(day):
            if day is not None:
                changed.add(day)
    return sorted(changed)
