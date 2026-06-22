# -*- coding: utf-8 -*-
"""评分粗筛：把全城候选景点收口到求解可承受的规模（高德矩阵成本与求解规模）。"""
import math

from app.core.constants import PER_DAY_CAP, CANDIDATE_MULTIPLIER


def select_candidates(attractions: list[dict], days: int) -> tuple[list[dict], list[dict]]:
    """按评分降序保留到上限 = days × PER_DAY_CAP × CANDIDATE_MULTIPLIER（向下取整）。
    同分按 poi_id 升序保证确定性。返回 (candidates, dropped)，dropped 带 reason。
    点数不超上限时全保留。
    """
    cap = max(1, math.floor(max(1, days) * PER_DAY_CAP * CANDIDATE_MULTIPLIER))
    ranked = sorted(attractions, key=lambda p: (-p.get("rating", 0.0), p.get("poi_id", "")))
    candidates = ranked[:cap]
    dropped = [{"name": p.get("name", ""), "rating": p.get("rating", 0.0),
                "reason": "评分较低，候选阶段未入选"}
               for p in ranked[cap:]]
    return candidates, dropped
