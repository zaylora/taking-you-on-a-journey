# -*- coding: utf-8 -*-
"""解析高德 POI opentime 字符串 -> VRPTW 到达时间窗(以 09:00 为 0 分钟基准)。

高德 opentime 格式多样:'09:00-17:00' / '08:30-18:00' / 多段(午休)'09:00-12:00,14:00-18:00'
/ 自由文本('全年无休')。无法解析或全天则不约束。容错优先,宁可不约束也不误约束。
"""
import re

_BASE_MIN = 540  # 09:00 行程起点基准(分钟)
_RANGE_RE = re.compile(r"(\d{1,2}):(\d{2})\s*[-~]\s*(\d{1,2}):(\d{2})")


def parse_opentime(opentime: str, day_budget: int) -> tuple[int, int]:
    """-> (最早到达分钟, 最晚到达分钟),以 09:00 为 0。无法解析/全天 -> (0, day_budget)。"""
    full = (0, day_budget)
    if not opentime:
        return full
    m = _RANGE_RE.search(opentime)  # 取第一段
    if not m:
        return full
    oh, om, ch, cm = (int(g) for g in m.groups())
    open_min = oh * 60 + om
    close_min = ch * 60 + cm
    # 全天(00:00-24:00 或 00:00-00:00)视为不约束
    if open_min <= 0 and close_min >= 24 * 60:
        return full
    # 关门早于/等于开门(异常或跨夜)-> 不约束
    if close_min <= open_min:
        return full
    lo = max(0, open_min - _BASE_MIN)
    hi = close_min - _BASE_MIN
    # 关门已在行程起点之前 -> 不约束(交给求解器/降级)
    if hi <= 0:
        return full
    # 只返回地点的物理时间窗(关门时刻),不在此合并 day_budget——
    # day_budget 是独立的行程预算约束,由 VRPTW 的 time dimension 上界单独处理。
    return (lo, hi)
