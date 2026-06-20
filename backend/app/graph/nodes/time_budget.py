"""时间预算纯函数：景点停留 / 交通耗时 / 当天总用时。零外部依赖，可单测。

游玩时长优先用 enrich_duration 写入的 visit_minutes（硬数据）；缺失时按景点
类型查静态表兜底。交通耗时按 mode 速度由直线距离粗估。
"""
import math

DAY_BUDGET = 480     # 每天可游玩分钟数（约 8h，09:00-18:00 扣午餐占用）
LUNCH_MIN = 60
DINNER_MIN = 60
DEFAULT_DURATION = 90

# 类型关键词 → 停留分钟。匹配 type 文本或 typecode 前缀。
STATIC_DURATION: dict[str, int] = {
    "博物": 150, "纪念馆": 150, "展览": 150,
    "乐园": 240, "游乐": 240, "主题": 240,
    "公园": 120, "动物园": 150, "植物园": 120,
    "观景": 60, "广场": 60, "塔": 90,
    "寺": 60, "庙": 60, "教堂": 60,
    "景区": 150, "风景": 150, "古镇": 180,
}

# mode → 平均速度 km/h（含等待，市内粗估）
_SPEED = {"步行": 12.0, "公交": 15.0, "驾车": 30.0}


def attraction_minutes(p: dict) -> int:
    """景点停留分钟：优先 visit_minutes，其次按 type 查静态表，再缺省 90。"""
    vm = p.get("visit_minutes")
    if isinstance(vm, (int, float)) and vm > 0:
        return int(vm)
    text = f"{p.get('type', '')}{p.get('name', '')}"
    for kw, mins in STATIC_DURATION.items():
        if kw in text:
            return mins
    return DEFAULT_DURATION


def transit_minutes(km: float, mode: str) -> int:
    """直线距离 → 交通耗时分钟，按 mode 速度，向上取整，至少 1。"""
    speed = _SPEED.get(mode, 15.0)
    if km <= 0:
        return 0
    return max(1, math.ceil(km / speed * 60))


def day_used_minutes(items: list[dict]) -> int:
    """当天总用时：景点停留 + 餐饮占用 + 相邻 transport 段交通耗时。"""
    # 惰性导入断开与 itinerary 的循环依赖（geometry 比 budget 更底层）
    from app.graph.nodes.itinerary import haversine_km
    total = 0
    meal_seen = 0
    prev_loc = None
    for it in items:
        t = it.get("type")
        if t == "attraction":
            total += attraction_minutes(it)
        elif t == "meal":
            total += LUNCH_MIN if meal_seen == 0 else DINNER_MIN
            meal_seen += 1
        elif t == "transport":
            cur = it.get("location") or {}
            if prev_loc is not None:
                total += transit_minutes(haversine_km(prev_loc, cur), it.get("mode", ""))
        loc = it.get("location")
        if loc:
            prev_loc = loc
    return total
