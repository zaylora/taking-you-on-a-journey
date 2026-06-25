# -*- coding: utf-8 -*-
"""候选景点粗筛：按评分降序取前 days*per_day 个，控制 VRPTW 求解规模。纯函数。"""


def select_candidates(attractions: list[dict], days: int, per_day: int = 4) -> list[dict]:
    cap = max(1, days) * max(1, per_day)
    valid = [a for a in (attractions or []) if a.get("lng") and a.get("lat")]
    ranked = sorted(valid, key=lambda a: -(a.get("rating", 0.0) or 0.0))
    return ranked[:cap]
