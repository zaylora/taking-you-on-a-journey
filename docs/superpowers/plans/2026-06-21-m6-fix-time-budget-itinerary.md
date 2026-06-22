# M6-fix 时间预算驱动的合理行程编排 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给行程编排装上「每日时间预算」——按评分预选装得下的景点（宁缺勿滥）、用 KMeans 把每天聚得紧凑（少走路）、按"停留+用餐+交通"耗时复校；游玩时长由 LLM+Tavily 联网查（降级静态表），高德补 `extensions=all` 拿评分。

**Architecture:** 在 `attractions` 检索（富化评分/营业时间）与 `itinerary` 之间插入新节点 `enrich_duration`（Tavily agent 估 `visit_minutes`，降级静态表）。`itinerary` 用三段纯函数替换原 `cluster_by_day`：评分预选 → KMeans 地理聚类 → 每日预算复校再平衡。原 `cluster_by_day` 保留为降级路径，现有测试不破坏。

**Tech Stack:** Python 3.11 / FastAPI / LangGraph 1.2.5 / LangChain 1.3.9 / scikit-learn（KMeans）/ langchain-tavily（联网）/ pytest + pytest-asyncio（asyncio_mode=auto）。包管理用 `uv`。

## Global Constraints

- 包管理统一用 `uv`：加依赖 `uv add <pkg>`，跑测试 `uv run pytest`（在 `backend/` 目录下）。
- 所有 API Key 用 `pydantic.SecretStr` 存储，绝不下发前端、绝不进日志/SSE（沿用 `amap_web_key` 约束）。
- 外部调用（高德 / Tavily / LLM）一律 `try/except` 降级，不抛、不阻断图执行（沿用现有 `# noqa: BLE001 —— 降级` 模式）。
- **M6 几何不变量必须守住**：每对相邻停靠点之间恰好一个 `transport` 段；LLM 严禁改名称/坐标/顺序/交通段。
- 纯函数优先、确定性优先（相同输入相同输出，不引入随机）。KMeans 固定 `random_state=42`、`n_init=10`。
- `cluster_by_day`（方位角均衡切片）**保留不动**，仅作 KMeans 降级路径；其现有测试 `test_cluster_by_day.py` 必须继续通过。
- 默认参数（spec 确认）：`DAY_BUDGET=480` 分钟；静态时长表 博物馆 150 / 主题乐园 240 / 公园 120 / 观景台·广场 60 / 寺庙 60 / 默认 90；交通速度 步行 12 / 公交 15 / 驾车 30 km/h；午餐 60、晚餐 60 分钟。
- 工作目录：仓库根 `/Users/Zhuanz/Desktop/taking-you-on-a-journey`，后端代码在 `backend/`。所有 `uv run` 命令在 `backend/` 下执行。

---

## File Structure

| 文件 | 责任 | 改动 |
|---|---|---|
| `backend/pyproject.toml` | 依赖声明 | 加 `scikit-learn`、`langchain-tavily` |
| `backend/app/core/config.py` | 配置 | 加 `tavily_api_key: SecretStr` |
| `backend/app/tools/amap.py` | 高德代理 | `search_poi`/`search_around` 加 `extensions=all`，解析 `rating/cost/opentime/typecode` |
| `backend/app/graph/nodes/time_budget.py` | **新增** 时间预算纯函数 | `STATIC_DURATION`、`attraction_minutes`、`transit_minutes`、`day_used_minutes`、`DAY_BUDGET` |
| `backend/app/graph/nodes/itinerary.py` | 编排算法 | 新增 `select_by_rating`、`cluster_kmeans`、`rebalance_by_budget`；`itinerary` 节点改用三段；产出 `dropped_attractions` |
| `backend/app/graph/state.py` | 图状态 | 加 `dropped_attractions: list` |
| `backend/app/tools/web_search.py` | **新增** Tavily 工具 | `build_tavily_tool()` 返回 LangChain 工具；未配 key 返回 None |
| `backend/app/graph/nodes/enrich_duration.py` | **新增** 时长富化节点 | `apply_durations`（纯函数）+ `enrich_duration`（agent，降级静态表） |
| `backend/app/graph/builder.py` | 图构建 | `attractions → enrich_duration → itinerary` |
| `backend/app/graph/nodes/refine.py` | 局部重排 | add/replace 补 `visit_minutes` + 预算复校；relax 用预算判定 |

---

## Task 1: 依赖与配置

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/app/core/config.py:52`（amap_web_key 之后）
- Test: `backend/tests/test_config_m6fix.py`（新建）

**Interfaces:**
- Produces: `get_settings().tavily_api_key: SecretStr`；可 `import sklearn.cluster.KMeans`、`from langchain_tavily import TavilySearch`。

- [ ] **Step 1: 加依赖**

Run（在 `backend/` 下）:
```bash
uv add scikit-learn langchain-tavily
```
Expected: `pyproject.toml` 的 `dependencies` 多出 `scikit-learn` 与 `langchain-tavily`，`uv.lock` 更新。

- [ ] **Step 2: 写失败测试**

`backend/tests/test_config_m6fix.py`:
```python
from app.core.config import Settings


def test_tavily_api_key_defaults_empty():
    s = Settings(_env_file=None)
    assert s.tavily_api_key.get_secret_value() == ""


def test_tavily_api_key_is_secret():
    s = Settings(tavily_api_key="tvly-xxx")
    # SecretStr 不应在 repr 中明文泄露
    assert "tvly-xxx" not in repr(s.tavily_api_key)
    assert s.tavily_api_key.get_secret_value() == "tvly-xxx"


def test_sklearn_and_tavily_importable():
    import sklearn.cluster  # noqa: F401
    from langchain_tavily import TavilySearch  # noqa: F401
```

- [ ] **Step 3: 跑测试确认失败**

Run: `uv run pytest tests/test_config_m6fix.py -v`
Expected: FAIL（`tavily_api_key` 属性不存在 / import 失败前两条因属性缺失报错）

- [ ] **Step 4: 加配置字段**

在 `backend/app/core/config.py` 的 `amap_web_key` 行（`:52`）之后插入:
```python
    # Tavily 联网检索（后端代理，Key 不下发前端）
    tavily_api_key: SecretStr = SecretStr("")
```

- [ ] **Step 5: 跑测试确认通过**

Run: `uv run pytest tests/test_config_m6fix.py -v`
Expected: PASS（3 passed）

- [ ] **Step 6: 提交**

```bash
git add backend/pyproject.toml backend/uv.lock backend/app/core/config.py backend/tests/test_config_m6fix.py
git commit -m "feat(m6-fix): 加 scikit-learn/langchain-tavily 依赖与 tavily_api_key 配置"
```

---

## Task 2: 高德富化字段（评分/人均/营业时间）

**Files:**
- Modify: `backend/app/tools/amap.py`（`search_poi` 与 `search_around` 两处的 params 与解析）
- Test: `backend/tests/test_amap_enrich.py`（新建）

**Interfaces:**
- Produces: `search_poi(...)` / `search_around(...)` 返回的每个 dict 在原有 `name/poi_id/lng/lat/address/type` 基础上新增 `rating: float`、`cost: float`、`opentime: str`、`typecode: str`。缺失给默认 `0.0 / 0.0 / "" / ""`。

- [ ] **Step 1: 写失败测试**

`backend/tests/test_amap_enrich.py`:
```python
import pytest

from app.tools import amap


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, payload):
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, params=None):
        # 断言开启了详情扩展
        assert params.get("extensions") == "all"
        return _FakeResp(self._payload)


_PAYLOAD = {
    "pois": [{
        "name": "广州塔", "id": "B001", "location": "113.32,23.10",
        "address": "海珠区", "type": "风景名胜", "typecode": "110000",
        "biz_ext": {"rating": "4.6", "cost": "150", "opentime": "09:00-22:00"},
    }]
}


@pytest.fixture
def patch_client(monkeypatch):
    monkeypatch.setattr(amap, "_key", lambda: "k")
    monkeypatch.setattr(amap.httpx, "AsyncClient",
                        lambda *a, **k: _FakeClient(_PAYLOAD))


async def test_search_poi_parses_biz_ext(patch_client):
    out = await amap.search_poi("广州", "塔")
    assert out[0]["rating"] == 4.6
    assert out[0]["cost"] == 150.0
    assert out[0]["opentime"] == "09:00-22:00"
    assert out[0]["typecode"] == "110000"


async def test_search_poi_defaults_when_biz_ext_missing(monkeypatch):
    monkeypatch.setattr(amap, "_key", lambda: "k")
    payload = {"pois": [{"name": "X", "id": "B002", "location": "113.0,23.0"}]}
    monkeypatch.setattr(amap.httpx, "AsyncClient",
                        lambda *a, **k: _FakeClient(payload))
    out = await amap.search_poi("广州", "x")
    assert out[0]["rating"] == 0.0
    assert out[0]["cost"] == 0.0
    assert out[0]["opentime"] == ""
    assert out[0]["typecode"] == ""
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_amap_enrich.py -v`
Expected: FAIL（params 无 `extensions`；返回 dict 无 `rating` 等键 → KeyError/断言失败）

- [ ] **Step 3: 加解析辅助函数**

在 `backend/app/tools/amap.py` 顶部 `_TIMEOUT = 5.0` 之后加:
```python
def _to_float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _enrich(p: dict) -> dict:
    """从高德 POI 提取 biz_ext 详情字段（extensions=all 时可用）。缺失给安全默认。"""
    biz = p.get("biz_ext") or {}
    return {
        "rating": _to_float(biz.get("rating")),
        "cost": _to_float(biz.get("cost")),
        "opentime": biz.get("opentime") or "",
        "typecode": p.get("typecode") or "",
    }
```

- [ ] **Step 4: 改 search_poi**

在 `search_poi` 的 `client.get(...)` params 里把 `"citylimit": "true",` 那一行所在 dict 加上 `"extensions": "all",`（与现有键并列）。然后把组装 `out.append({...})` 的字典改为合并富化字段:
```python
            item = {
                "name": p.get("name", ""), "poi_id": p.get("id", ""),
                "lng": float(loc[0]), "lat": float(loc[1]),
                "address": p.get("address", ""), "type": p.get("type", ""),
            }
            item.update(_enrich(p))
            out.append(item)
```

- [ ] **Step 5: 改 search_around**

同样在 `search_around` 的 params 里加 `"extensions": "all",`，并把它的 `out.append({...})` 改成与 Step 4 相同的 `item = {...}; item.update(_enrich(p)); out.append(item)` 形式。

- [ ] **Step 6: 跑测试确认通过 + 回归**

Run: `uv run pytest tests/test_amap_enrich.py tests/test_amap.py -v`
Expected: PASS（新测试 2 passed；原 test_amap.py 不回归）

- [ ] **Step 7: 提交**

```bash
git add backend/app/tools/amap.py backend/tests/test_amap_enrich.py
git commit -m "feat(m6-fix): 高德检索加 extensions=all，解析评分/人均/营业时间/typecode"
```

---

## Task 3: 时间预算纯函数模块

**Files:**
- Create: `backend/app/graph/nodes/time_budget.py`
- Test: `backend/tests/test_time_budget.py`（新建）

**Interfaces:**
- Produces:
  - `DAY_BUDGET: int = 480`、`LUNCH_MIN = 60`、`DINNER_MIN = 60`
  - `STATIC_DURATION: dict[str, int]`（typecode 前缀/类型名 → 分钟）
  - `attraction_minutes(p: dict) -> int`：取 `p["visit_minutes"]`，缺失/<=0 时按 `type`/`typecode` 查 `STATIC_DURATION`，再缺省 90
  - `transit_minutes(km: float, mode: str) -> int`：按 mode 速度估分钟，向上取整
  - `day_used_minutes(items: list[dict]) -> int`：累加景点停留 + 餐饮占用 + 相邻 transport 段交通耗时
- Consumes: `haversine_km` 从 `app.graph.nodes.itinerary` 导入（已存在）。

- [ ] **Step 1: 写失败测试**

`backend/tests/test_time_budget.py`:
```python
from app.graph.nodes.time_budget import (
    DAY_BUDGET, attraction_minutes, transit_minutes, day_used_minutes,
)


def test_day_budget_default():
    assert DAY_BUDGET == 480


def test_attraction_minutes_uses_visit_minutes():
    assert attraction_minutes({"visit_minutes": 200}) == 200


def test_attraction_minutes_falls_back_to_type():
    assert attraction_minutes({"type": "博物馆"}) == 150
    assert attraction_minutes({"type": "公园"}) == 120


def test_attraction_minutes_default_90():
    assert attraction_minutes({"name": "某不知名地"}) == 90


def test_transit_minutes_walk():
    # 1.2km 步行 @12km/h = 6 分钟
    assert transit_minutes(1.2, "步行") == 6


def test_transit_minutes_drive():
    # 15km 驾车 @30km/h = 30 分钟
    assert transit_minutes(15.0, "驾车") == 30


def test_day_used_minutes_sums_all():
    items = [
        {"type": "attraction", "visit_minutes": 120,
         "location": {"lng": 113.0, "lat": 23.0}},
        {"type": "transport", "mode": "步行",
         "location": {"lng": 113.0, "lat": 23.0}},
        {"type": "meal", "location": {"lng": 113.01, "lat": 23.0}},
        {"type": "transport", "mode": "公交",
         "location": {"lng": 113.01, "lat": 23.0}},
        {"type": "attraction", "visit_minutes": 90,
         "location": {"lng": 113.05, "lat": 23.0}},
    ]
    used = day_used_minutes(items)
    # 景点 120 + 90，午餐 60，两段交通 > 0
    assert used >= 120 + 90 + 60
    assert used < 600
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_time_budget.py -v`
Expected: FAIL（模块不存在 / 函数未定义）

- [ ] **Step 3: 写实现**

`backend/app/graph/nodes/time_budget.py`:
```python
"""时间预算纯函数：景点停留 / 交通耗时 / 当天总用时。零外部依赖，可单测。

游玩时长优先用 enrich_duration 写入的 visit_minutes（硬数据）；缺失时按景点
类型查静态表兜底。交通耗时按 mode 速度由直线距离粗估。
"""
import math

from app.graph.nodes.itinerary import haversine_km

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
```

注：`transport` 段的 `location` 是其起点坐标（见 `itinerary._transport_item`），耗时用「上一停靠点 → 该段起点」近似；小尺度下足够。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_time_budget.py -v`
Expected: PASS（7 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/graph/nodes/time_budget.py backend/tests/test_time_budget.py
git commit -m "feat(m6-fix): 时间预算纯函数（停留/交通耗时/当天总用时 + 静态时长表）"
```

---

## Task 4: 评分预选（select_by_rating）

**Files:**
- Modify: `backend/app/graph/nodes/itinerary.py`（新增纯函数，置于 `cluster_by_day` 之前）
- Test: `backend/tests/test_select_by_rating.py`（新建）

**Interfaces:**
- Produces: `select_by_rating(attractions: list[dict], days: int, day_budget: int = DAY_BUDGET) -> tuple[list[dict], list[dict]]`
  返回 `(selected, dropped)`。`selected` 按 rating 降序装到总预算 `days * day_budget`（每个景点占 `attraction_minutes + 每景点固定开销 OVERHEAD_PER_STOP=40` 分钟，含分摊餐饮/交通）；装满即停。`dropped` 每项加 `reason` 字段。
- Consumes: `attraction_minutes` from `app.graph.nodes.time_budget`。

- [ ] **Step 1: 写失败测试**

`backend/tests/test_select_by_rating.py`:
```python
from app.graph.nodes.itinerary import select_by_rating


def _a(name, rating, vm, lng=113.0, lat=23.0):
    return {"name": name, "poi_id": name, "rating": rating,
            "visit_minutes": vm, "lng": lng, "lat": lat}


def test_keeps_high_rating_first():
    pts = [_a("low", 3.0, 120), _a("high", 4.8, 120), _a("mid", 4.0, 120)]
    selected, _ = select_by_rating(pts, days=1, day_budget=400)
    names = [p["name"] for p in selected]
    assert names[0] == "high"  # 最高分排最前


def test_drops_overflow_by_budget():
    # 每景点 120+40=160 分钟；1 天 400 分钟 → 最多 2 个
    pts = [_a(f"p{i}", 4.0 + i * 0.1, 120) for i in range(5)]
    selected, dropped = select_by_rating(pts, days=1, day_budget=400)
    assert len(selected) == 2
    assert len(dropped) == 3
    assert all("reason" in d for d in dropped)


def test_all_fit_when_budget_large():
    pts = [_a(f"p{i}", 4.0, 60) for i in range(3)]
    selected, dropped = select_by_rating(pts, days=2, day_budget=480)
    assert len(selected) == 3
    assert dropped == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_select_by_rating.py -v`
Expected: FAIL（`select_by_rating` 未定义）

- [ ] **Step 3: 写实现**

在 `backend/app/graph/nodes/itinerary.py` 顶部 import 区加:
```python
from app.graph.nodes.time_budget import DAY_BUDGET, attraction_minutes
```
在 `cluster_by_day` 函数定义之前插入:
```python
OVERHEAD_PER_STOP = 40  # 每景点分摊的餐饮/交通/缓冲开销(分钟)


def select_by_rating(attractions: list[dict], days: int,
                     day_budget: int = DAY_BUDGET) -> tuple[list[dict], list[dict]]:
    """按评分降序装到总时间预算，宁缺勿滥。返回 (selected, dropped)。
    评分相同按 poi_id 字典序保证确定性。dropped 每项带 reason。
    """
    total_budget = max(1, days) * day_budget
    ranked = sorted(attractions,
                    key=lambda p: (-p.get("rating", 0.0), p.get("poi_id", "")))
    selected, dropped = [], []
    used = 0
    for p in ranked:
        cost = attraction_minutes(p) + OVERHEAD_PER_STOP
        if used + cost <= total_budget:
            selected.append(p)
            used += cost
        else:
            dropped.append({**p, "reason": "超出总时间预算（按评分取舍）"})
    return selected, dropped
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_select_by_rating.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/graph/nodes/itinerary.py backend/tests/test_select_by_rating.py
git commit -m "feat(m6-fix): 评分预选 select_by_rating（按总时间预算宁缺勿滥）"
```

---

## Task 5: KMeans 地理聚类（cluster_kmeans，含降级）

**Files:**
- Modify: `backend/app/graph/nodes/itinerary.py`（新增 `cluster_kmeans`，置于 `cluster_by_day` 之后）
- Test: `backend/tests/test_cluster_kmeans.py`（新建）

**Interfaces:**
- Produces: `cluster_kmeans(points: list[dict], days: int) -> list[list[dict]]`
  返回长度恰为 `days` 的桶列表（与 `cluster_by_day` 接口一致）。按经纬度（纬度等距投影）聚成 `days` 群，每群内部用 `_nearest_neighbor_order` 排序。点数 < days 或 sklearn 不可用时回退 `cluster_by_day`。
- Consumes: `_nearest_neighbor_order`、`cluster_by_day`（同模块，已存在）。

- [ ] **Step 1: 写失败测试**

`backend/tests/test_cluster_kmeans.py`:
```python
from app.graph.nodes.itinerary import cluster_kmeans


def _pt(name, lng, lat):
    return {"name": name, "poi_id": name, "lng": lng, "lat": lat}


def test_returns_exactly_days_buckets():
    pts = [_pt(f"p{i}", 113.0 + i * 0.01, 23.0) for i in range(9)]
    res = cluster_kmeans(pts, 3)
    assert len(res) == 3
    assert sum(len(b) for b in res) == 9


def test_geographic_compactness():
    # 两簇明显分离：东边一团、西边一团 → 同簇应聚在一起
    west = [_pt(f"w{i}", 113.0 + i * 0.001, 23.0) for i in range(4)]
    east = [_pt(f"e{i}", 114.0 + i * 0.001, 23.0) for i in range(4)]
    res = cluster_kmeans(west + east, 2)
    # 每个桶应是纯西或纯东（不混）
    for bucket in res:
        prefixes = {p["name"][0] for p in bucket}
        assert len(prefixes) == 1


def test_fewer_points_than_days_falls_back():
    res = cluster_kmeans([_pt("a", 113.0, 23.0)], 3)
    assert len(res) == 3
    assert sum(len(b) for b in res) == 1


def test_empty_points():
    assert cluster_kmeans([], 3) == [[], [], []]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_cluster_kmeans.py -v`
Expected: FAIL（`cluster_kmeans` 未定义）

- [ ] **Step 3: 写实现**

在 `backend/app/graph/nodes/itinerary.py` 的 `cluster_by_day` 之后插入:
```python
def cluster_kmeans(points: list[dict], days: int) -> list[list[dict]]:
    """按经纬度 KMeans 聚成 days 群，每群内部最近邻排序。
    目标：同一天的景点地理紧凑。点数<days 或 sklearn 不可用时回退 cluster_by_day。
    """
    days = max(1, days)
    if not points:
        return [[] for _ in range(days)]
    if len(points) < days:
        return cluster_by_day(points, days)
    try:
        from sklearn.cluster import KMeans
    except ImportError:
        return cluster_by_day(points, days)

    # 纬度等距投影：经度按 cos(lat) 缩放，避免高纬度经度被高估
    lat0 = sum(p.get("lat", 0.0) for p in points) / len(points)
    scale = math.cos(math.radians(lat0)) or 1.0
    feats = [[p.get("lng", 0.0) * scale, p.get("lat", 0.0)] for p in points]
    labels = KMeans(n_clusters=days, random_state=42, n_init=10).fit_predict(feats)

    buckets: list[list[dict]] = [[] for _ in range(days)]
    for p, lbl in zip(points, labels):
        buckets[int(lbl)].append(p)
    return [_nearest_neighbor_order(b) for b in buckets]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_cluster_kmeans.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/graph/nodes/itinerary.py backend/tests/test_cluster_kmeans.py
git commit -m "feat(m6-fix): KMeans 地理聚类 cluster_kmeans（含 sklearn 缺失降级）"
```

---

## Task 6: 每日预算复校再平衡（rebalance_by_budget）

**Files:**
- Modify: `backend/app/graph/nodes/itinerary.py`（新增 `rebalance_by_budget`，置于 `cluster_kmeans` 之后）
- Test: `backend/tests/test_rebalance_budget.py`（新建）

**Interfaces:**
- Produces: `rebalance_by_budget(buckets: list[list[dict]], day_budget: int = DAY_BUDGET) -> tuple[list[list[dict]], list[dict]]`
  对每个桶估纯景点用时（`Σ attraction_minutes + len*OVERHEAD_PER_STOP`），超预算的桶弹出评分最低景点，尝试塞入「仍有余量且地理最近」的其它桶；无处可塞则进 `dropped`（带 reason）。返回 `(balanced_buckets, dropped)`。
- Consumes: `attraction_minutes`、`haversine_km`、`OVERHEAD_PER_STOP`、`DAY_BUDGET`（同模块/已导入）。

- [ ] **Step 1: 写失败测试**

`backend/tests/test_rebalance_budget.py`:
```python
from app.graph.nodes.itinerary import rebalance_by_budget


def _a(name, rating, vm, lng=113.0, lat=23.0):
    return {"name": name, "poi_id": name, "rating": rating,
            "visit_minutes": vm, "lng": lng, "lat": lat}


def _bucket_minutes(bucket):
    return sum(a["visit_minutes"] + 40 for a in bucket)


def test_overloaded_day_sheds_lowest_rating():
    # 一天塞 4 个 *160min=640 > 480；另一天空 → 应迁移而非全丢
    day1 = [_a(f"p{i}", 4.0 + i * 0.1, 120) for i in range(4)]
    day2 = []
    balanced, dropped = rebalance_by_budget([day1, day2], day_budget=480)
    assert all(_bucket_minutes(b) <= 480 for b in balanced)
    # 4 个 160min 总 640，可分布到两天（每天≤3个=480），不应丢弃
    kept = sum(len(b) for b in balanced)
    assert kept + len(dropped) == 4


def test_drops_when_no_room_anywhere():
    # 单天，5 个 160min，预算 480 → 最多 3 个，丢 2 个
    day1 = [_a(f"p{i}", 4.0 + i * 0.05, 120) for i in range(5)]
    balanced, dropped = rebalance_by_budget([day1], day_budget=480)
    assert _bucket_minutes(balanced[0]) <= 480
    assert len(dropped) == 2
    assert all("reason" in d for d in dropped)


def test_within_budget_unchanged():
    day1 = [_a("a", 4.0, 120), _a("b", 4.0, 120)]
    balanced, dropped = rebalance_by_budget([day1], day_budget=480)
    assert len(balanced[0]) == 2
    assert dropped == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_rebalance_budget.py -v`
Expected: FAIL（`rebalance_by_budget` 未定义）

- [ ] **Step 3: 写实现**

在 `backend/app/graph/nodes/itinerary.py` 的 `cluster_kmeans` 之后插入:
```python
def _bucket_load(bucket: list[dict]) -> int:
    """桶内纯景点用时估计（停留 + 每景点固定开销）。"""
    return sum(attraction_minutes(a) + OVERHEAD_PER_STOP for a in bucket)


def _bucket_center(bucket: list[dict]) -> dict:
    if not bucket:
        return {"lng": 0.0, "lat": 0.0}
    return {"lng": sum(a.get("lng", 0.0) for a in bucket) / len(bucket),
            "lat": sum(a.get("lat", 0.0) for a in bucket) / len(bucket)}


def rebalance_by_budget(buckets: list[list[dict]],
                        day_budget: int = DAY_BUDGET) -> tuple[list[list[dict]], list[dict]]:
    """超预算的天弹出最低分景点 → 塞入地理最近且有余量的天；无处可塞则丢弃。
    返回 (balanced_buckets, dropped)。确定性：迁移目标按 (距离, 桶序) 排序。
    """
    buckets = [list(b) for b in buckets]
    dropped: list[dict] = []
    for i, bucket in enumerate(buckets):
        # 反复弹出最低分，直到该桶不超预算
        while _bucket_load(bucket) > day_budget and bucket:
            victim = min(bucket, key=lambda a: (a.get("rating", 0.0), a.get("poi_id", "")))
            bucket.remove(victim)
            need = attraction_minutes(victim) + OVERHEAD_PER_STOP
            # 候选目标天：有余量者，按到该天中心的距离升序
            targets = sorted(
                (j for j in range(len(buckets))
                 if j != i and _bucket_load(buckets[j]) + need <= day_budget),
                key=lambda j: (haversine_km(victim, _bucket_center(buckets[j])), j),
            )
            if targets:
                buckets[targets[0]].append(victim)
            else:
                dropped.append({**victim, "reason": "各天时间预算已满，无法安排"})
        buckets[i] = bucket
    # 迁移后各桶内部重新最近邻排序
    return [_nearest_neighbor_order(b) for b in buckets], dropped
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_rebalance_budget.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/graph/nodes/itinerary.py backend/tests/test_rebalance_budget.py
git commit -m "feat(m6-fix): 每日预算复校再平衡 rebalance_by_budget"
```

---

## Task 7: itinerary 节点接线 + state 字段

**Files:**
- Modify: `backend/app/graph/nodes/itinerary.py`（`itinerary` 节点函数体 `:280-326`）
- Modify: `backend/app/graph/state.py:52`（加 `dropped_attractions`）
- Test: `backend/tests/test_itinerary_m6fix.py`（新建）

**Interfaces:**
- Consumes: `select_by_rating`、`cluster_kmeans`、`rebalance_by_budget`（Task 4-6）。
- Produces: `itinerary` 节点返回 dict 新增 `"dropped_attractions": list`；`day_plans` 每天满足 `day_used_minutes(items) <= DAY_BUDGET`（含交通/餐饮）。state 新增 `dropped_attractions` 字段。

- [ ] **Step 1: 写失败测试**

`backend/tests/test_itinerary_m6fix.py`:
```python
import pytest

from app.graph.nodes.itinerary import itinerary
from app.graph.nodes.time_budget import day_used_minutes, DAY_BUDGET


def _a(name, lng, lat, rating=4.0, vm=120):
    return {"name": name, "poi_id": name, "lng": lng, "lat": lat,
            "rating": rating, "visit_minutes": vm}


@pytest.fixture
def no_llm_no_amap(monkeypatch):
    # 断网：LLM 软填抛错走骨架默认；周边餐饮搜索返回空
    import app.graph.nodes.itinerary as it

    def _boom(*a, **k):
        raise RuntimeError("offline")

    monkeypatch.setattr(it, "build_llm", _boom)

    async def _empty(*a, **k):
        return []

    monkeypatch.setattr(it.amap, "search_around", _empty)


async def test_each_day_within_budget(no_llm_no_amap):
    # 10 个景点、2 天 → 预选+复校后每天不超预算
    attractions = [_a(f"p{i}", 113.0 + i * 0.01, 23.0) for i in range(10)]
    out = await itinerary({"days": 2, "attractions": attractions}, config={})
    for day in out["day_plans"]:
        assert day_used_minutes(day["items"]) <= DAY_BUDGET


async def test_reports_dropped(no_llm_no_amap):
    attractions = [_a(f"p{i}", 113.0 + i * 0.01, 23.0, vm=120) for i in range(10)]
    out = await itinerary({"days": 1, "attractions": attractions}, config={})
    # 1 天 480min，每个 160min → 最多 3 个，其余进 dropped
    assert len(out["dropped_attractions"]) > 0
    assert all("reason" in d for d in out["dropped_attractions"])


async def test_transport_invariant_kept(no_llm_no_amap):
    # M6 不变量：相邻停靠点之间恰好一个 transport
    attractions = [_a(f"p{i}", 113.0 + i * 0.01, 23.0) for i in range(6)]
    out = await itinerary({"days": 2, "attractions": attractions}, config={})
    for day in out["day_plans"]:
        items = day["items"]
        stops = [i for i in items if i.get("type") != "transport"]
        transports = [i for i in items if i.get("type") == "transport"]
        if len(stops) >= 2:
            assert len(transports) == len(stops) - 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_itinerary_m6fix.py -v`
Expected: FAIL（`itinerary` 还用 `cluster_by_day`，返回无 `dropped_attractions` 键 → KeyError）

- [ ] **Step 3: 改 itinerary 节点**

把 `backend/app/graph/nodes/itinerary.py` 中 `async def itinerary` 函数体开头的聚类部分:
```python
    days = state.get("days", 3) or 3
    attractions = state.get("attractions", []) or []
    clusters = cluster_by_day(attractions, days)
```
替换为:
```python
    days = state.get("days", 3) or 3
    attractions = state.get("attractions", []) or []
    selected, dropped = select_by_rating(attractions, days)
    clusters = cluster_kmeans(selected, days)
    clusters, dropped_balance = rebalance_by_budget(clusters)
    dropped = dropped + dropped_balance
```
然后在函数结尾 `return {...}` 的返回 dict 中加一项:
```python
        "dropped_attractions": dropped,
```
（与 `daily_centers`、`day_plans` 等并列）

- [ ] **Step 4: 加 state 字段**

在 `backend/app/graph/state.py` 的 `day_plans: list`（`:46`）之后加:
```python
    dropped_attractions: list   # 因评分/预算未排入的景点 [{name,rating,reason}]
```

- [ ] **Step 5: 跑测试确认通过 + 回归**

Run: `uv run pytest tests/test_itinerary_m6fix.py tests/test_itinerary.py tests/test_cluster_by_day.py -v`
Expected: PASS（新测试 3 passed；原 itinerary/cluster_by_day 测试不回归——`cluster_by_day` 未改）

- [ ] **Step 6: 提交**

```bash
git add backend/app/graph/nodes/itinerary.py backend/app/graph/state.py backend/tests/test_itinerary_m6fix.py
git commit -m "feat(m6-fix): itinerary 接入预选+KMeans+预算复校，产出 dropped_attractions"
```

---

## Task 8: Tavily 联网工具

**Files:**
- Create: `backend/app/tools/web_search.py`
- Test: `backend/tests/test_web_search.py`（新建）

**Interfaces:**
- Produces: `build_tavily_tool()`：配了 `tavily_api_key` 时返回一个 LangChain 工具（`TavilySearch` 实例，可被 `bind_tools` / agent 使用）；未配则返回 `None`。
- Consumes: `get_settings().tavily_api_key`。

- [ ] **Step 1: 写失败测试**

`backend/tests/test_web_search.py`:
```python
from app.tools import web_search
from app.core import config


def _settings(key):
    return config.Settings(tavily_api_key=key, _env_file=None)


def test_returns_none_when_no_key(monkeypatch):
    monkeypatch.setattr(web_search, "get_settings", lambda: _settings(""))
    assert web_search.build_tavily_tool() is None


def test_returns_tool_when_key_present(monkeypatch):
    monkeypatch.setattr(web_search, "get_settings", lambda: _settings("tvly-x"))
    tool = web_search.build_tavily_tool()
    assert tool is not None
    assert hasattr(tool, "name")  # LangChain 工具具备 name 属性
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_web_search.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 写实现**

`backend/app/tools/web_search.py`:
```python
"""Tavily 联网检索工具：封装为 LangChain 工具，供编排 agent 按需调用。

Key 取自 config.tavily_api_key（SecretStr），绝不下发前端/进日志。未配 key
时返回 None，调用方据此降级（不联网）。
"""
import os

from app.core.config import get_settings


def build_tavily_tool(max_results: int = 3):
    """返回一个可被 agent / bind_tools 使用的 Tavily 检索工具；未配 key 返回 None。"""
    key = get_settings().tavily_api_key.get_secret_value()
    if not key:
        return None
    # langchain_tavily 通过环境变量读取 key
    os.environ.setdefault("TAVILY_API_KEY", key)
    from langchain_tavily import TavilySearch
    return TavilySearch(max_results=max_results)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_web_search.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/tools/web_search.py backend/tests/test_web_search.py
git commit -m "feat(m6-fix): Tavily 联网检索工具（未配 key 降级 None）"
```

---

## Task 9: enrich_duration 节点 + 接入图

**Files:**
- Create: `backend/app/graph/nodes/enrich_duration.py`
- Modify: `backend/app/graph/builder.py`（节点注册 + 边）
- Test: `backend/tests/test_enrich_duration.py`（新建）

**Interfaces:**
- Produces:
  - `apply_durations(attractions: list[dict], duration_map: dict[str, int]) -> list[dict]`（纯函数）：按 `poi_id` 把分钟写入每个景点的 `visit_minutes`；map 里没有的用 `attraction_minutes` 静态兜底。
  - `enrich_duration(state, config) -> dict`：返回 `{"attractions": [...]}`，每个景点带 `visit_minutes`。配了 Tavily 时用 agent 联网估，失败/未配则全静态表兜底。
- Consumes: `build_tavily_tool`（Task 8）、`attraction_minutes`（Task 3）、`build_llm`（已有）。

- [ ] **Step 1: 写失败测试**

`backend/tests/test_enrich_duration.py`:
```python
import pytest

from app.graph.nodes.enrich_duration import apply_durations, enrich_duration


def _a(name, **kw):
    return {"name": name, "poi_id": name, "type": kw.get("type", ""), **kw}


def test_apply_durations_maps_by_poi_id():
    atts = [_a("故宫"), _a("公园", type="公园")]
    out = apply_durations(atts, {"故宫": 300})
    assert out[0]["visit_minutes"] == 300       # 来自 map
    assert out[1]["visit_minutes"] == 120        # 静态兜底（公园）


def test_apply_durations_static_fallback_for_unmapped():
    out = apply_durations([_a("某地")], {})
    assert out[0]["visit_minutes"] == 90         # 默认


async def test_enrich_duration_without_tavily(monkeypatch):
    import app.graph.nodes.enrich_duration as ed
    monkeypatch.setattr(ed, "build_tavily_tool", lambda: None)
    atts = [_a("博物馆", type="博物馆"), _a("广场", type="广场")]
    out = await enrich_duration({"attractions": atts}, config={})
    vms = {a["name"]: a["visit_minutes"] for a in out["attractions"]}
    assert vms["博物馆"] == 150
    assert vms["广场"] == 60
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_enrich_duration.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 写实现**

`backend/app/graph/nodes/enrich_duration.py`:
```python
"""enrich_duration 节点：分天前给候选景点估「建议游玩时长」visit_minutes。

配了 Tavily key 时，用绑定 Tavily 工具的 agent 联网研究知名景点该玩多久，
返回结构化 {poi_id: minutes}；未配或失败时全部用静态类型表兜底（attraction_minutes）。
visit_minutes 是供 itinerary 算法消费的硬数据，不进 LLM 软填。
"""
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.graph.nodes.time_budget import attraction_minutes
from app.llm.factory import build_llm
from app.tools.web_search import build_tavily_tool


class _Duration(BaseModel):
    poi_id: str = Field(description="景点 poi_id，原样回填")
    minutes: int = Field(description="建议游玩时长（分钟，整数）")


class _Durations(BaseModel):
    items: list[_Duration] = Field(default_factory=list)


_SYS = (
    "你是行程时长估算助手。给定景点列表（name + poi_id），估每个景点的建议游玩时长（分钟）。"
    "可用联网工具查证知名景点（如故宫约一天、小观景台约半小时）。"
    "只返回 poi_id 与整数分钟，不要编造 poi_id。"
)


def apply_durations(attractions: list[dict], duration_map: dict[str, int]) -> list[dict]:
    """把 duration_map（poi_id→分钟）写入每个景点的 visit_minutes；缺失用静态表兜底。纯函数。"""
    out = []
    for a in attractions:
        m = duration_map.get(a.get("poi_id"))
        merged = dict(a)
        merged["visit_minutes"] = int(m) if isinstance(m, (int, float)) and m > 0 else attraction_minutes(a)
        out.append(merged)
    return out


async def enrich_duration(state, config) -> dict:
    attractions = state.get("attractions", []) or []
    if not attractions:
        return {"attractions": attractions}

    tool = build_tavily_tool()
    duration_map: dict[str, int] = {}
    if tool is not None:
        try:
            llm = build_llm(temperature=0).bind_tools([tool])
            payload = [{"name": a.get("name", ""), "poi_id": a.get("poi_id", "")}
                       for a in attractions]
            # 先让模型（可调用 Tavily）研究，再用结构化输出收口
            research = await llm.ainvoke([
                SystemMessage(content=_SYS),
                HumanMessage(content=str(payload)),
            ], config=config)
            extractor = build_llm(temperature=0).with_structured_output(
                _Durations, method="function_calling")
            result = await extractor.ainvoke([
                SystemMessage(content="把下面内容整理成 poi_id→minutes 列表。"),
                HumanMessage(content=str(getattr(research, "content", "")) or str(payload)),
            ], config=config)
            duration_map = {d.poi_id: d.minutes for d in result.items if d.minutes > 0}
        except Exception:  # noqa: BLE001 —— 联网/解析失败，全静态表兜底
            duration_map = {}

    return {"attractions": apply_durations(attractions, duration_map)}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_enrich_duration.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 接入图**

在 `backend/app/graph/builder.py` import 区（`:15` 附近）加:
```python
from app.graph.nodes.enrich_duration import enrich_duration
```
在节点注册列表（`:30-38` 的 `for name, fn in [...]`）里加一项 `("enrich_duration", enrich_duration),`。
然后把并行检索接线（`:48-50`）:
```python
    for n in ("weather", "attractions", "restaurants", "transport"):
        g.add_edge("retrieve", n)
        g.add_edge(n, "itinerary")
```
改为（attractions 经 enrich_duration 再汇入 itinerary，其余不变）:
```python
    for n in ("weather", "restaurants", "transport"):
        g.add_edge("retrieve", n)
        g.add_edge(n, "itinerary")
    g.add_edge("retrieve", "attractions")
    g.add_edge("attractions", "enrich_duration")
    g.add_edge("enrich_duration", "itinerary")
```

- [ ] **Step 6: 跑测试确认图可构建 + 回归**

Run: `uv run pytest tests/test_builder.py tests/test_parallel_retrieval.py -v`
Expected: PASS（图编译成功，并行检索拓扑不回归）

- [ ] **Step 7: 提交**

```bash
git add backend/app/graph/nodes/enrich_duration.py backend/app/graph/builder.py backend/tests/test_enrich_duration.py
git commit -m "feat(m6-fix): enrich_duration 节点（Tavily agent 估时长，降级静态表）+ 接入图"
```

---

## Task 10: refine 联动（补时长 + 预算守护）

**Files:**
- Modify: `backend/app/graph/nodes/refine.py`（`_poi_to_item`、`_apply_search_op`、relax 路径）
- Test: `backend/tests/test_refine_budget.py`（新建）

**Interfaces:**
- Consumes: `attraction_minutes`、`day_used_minutes`、`DAY_BUDGET`（Task 3）。
- Produces: refine 的 `add`/`replace` 新景点带 `visit_minutes`；relax 用 `day_used_minutes` 判断是否仍超预算。不破坏 M6 transport 不变量（仍走 `_rebuild_transport`）。

- [ ] **Step 1: 写失败测试**

`backend/tests/test_refine_budget.py`:
```python
from app.graph.nodes.refine import _poi_to_item, _relax_until_budget


def test_poi_to_item_has_visit_minutes():
    poi = {"name": "博物馆", "poi_id": "B1", "lng": 113.0, "lat": 23.0,
           "type": "博物馆"}
    item = _poi_to_item(poi, "attraction")
    assert item["visit_minutes"] == 150  # 静态兜底


def test_relax_until_budget_removes_until_fit():
    # 当天 4 个景点各 160min = 640+ > 480 → relax 应删到不超预算
    items = [{"type": "attraction", "name": f"p{i}", "poi_id": f"p{i}",
              "visit_minutes": 120, "location": {"lng": 113.0 + i * 0.01, "lat": 23.0}}
             for i in range(4)]
    day = {"day": 1, "items": items}
    out = _relax_until_budget(day)
    from app.graph.nodes.time_budget import day_used_minutes, DAY_BUDGET
    assert day_used_minutes(out["items"]) <= DAY_BUDGET
    assert len(out["items"]) < 4
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_refine_budget.py -v`
Expected: FAIL（`_relax_until_budget` 未定义；`_poi_to_item` 无 visit_minutes）

- [ ] **Step 3: 改 refine**

在 `backend/app/graph/nodes/refine.py` import 区加:
```python
from app.graph.nodes.itinerary import insert_transport
from app.graph.nodes.time_budget import attraction_minutes, day_used_minutes, DAY_BUDGET
```
（`insert_transport` 已 import，勿重复；只加 time_budget 一行）

把 `_poi_to_item` 的返回 dict 加一项 `"visit_minutes"`:
```python
def _poi_to_item(poi: dict, type_: str) -> dict:
    """高德 POI → PlanItem dict（与 itinerary.PlanItem 字段对齐）。"""
    item = {
        "type": type_,
        "name": poi.get("name", ""),
        "poi_id": poi.get("poi_id", ""),
        "location": {"lng": poi.get("lng", 0.0), "lat": poi.get("lat", 0.0)},
        "start": "", "end": "", "indoor": False, "note": "", "cost": 0.0,
    }
    if type_ == "attraction":
        item["visit_minutes"] = attraction_minutes({**poi, "type": poi.get("type", "")})
    return item
```

在 `_relax_day` 之后新增按预算删项的函数:
```python
def _relax_until_budget(day_plan: dict) -> dict:
    """反复删当天最后一个景点/餐饮，直到 day_used_minutes <= DAY_BUDGET（至少删 1 个）。"""
    updated = dict(day_plan)
    items = [it for it in (updated.get("items") or []) if it.get("type") != "transport"]
    removed = False
    while items and (day_used_minutes(insert_transport(items)) > DAY_BUDGET or not removed):
        removable = [i for i, it in enumerate(items)
                     if it.get("type") in ("attraction", "meal") and it.get("name")]
        if not removable:
            break
        items.pop(removable[-1])
        removed = True
        if day_used_minutes(insert_transport(items)) <= DAY_BUDGET:
            break
    updated["items"] = insert_transport(items)
    return updated
```

把 `refine` 函数里 relax 分支:
```python
    if op in ("relax", "remove", "tighten") and idx is not None:
        day_plans[idx] = _rebuild_transport(_relax_day(day_plans[idx]))
        changed_days = [target_day]
```
改为（relax 用预算判定，remove/tighten 保持原逐项删）:
```python
    if op == "relax" and idx is not None:
        day_plans[idx] = _relax_until_budget(day_plans[idx])
        changed_days = [target_day]
    elif op in ("remove", "tighten") and idx is not None:
        day_plans[idx] = _rebuild_transport(_relax_day(day_plans[idx]))
        changed_days = [target_day]
```

- [ ] **Step 4: 跑测试确认通过 + 回归**

Run: `uv run pytest tests/test_refine_budget.py tests/test_refine_node.py tests/test_refine_search.py tests/test_refine_transport.py -v`
Expected: PASS（新测试 2 passed；原 refine 测试不回归——注意 `_relax_until_budget` 至少删 1 个，与原 relax「删最后一个」行为对单景点一致）

- [ ] **Step 5: 提交**

```bash
git add backend/app/graph/nodes/refine.py backend/tests/test_refine_budget.py
git commit -m "feat(m6-fix): refine 补 visit_minutes + relax 按每日预算删项"
```

---

## Task 11: 全量回归 + dropped 说明（收尾）

**Files:**
- Test: 全套 `backend/tests/`
- Modify（可选）: `backend/app/graph/nodes/answer.py`（若 answer 已汇总方案说明，则附上未排入景点）

**Interfaces:**
- Consumes: `state["dropped_attractions"]`（Task 7 产出）。

- [ ] **Step 1: 跑全量测试**

Run: `uv run pytest -q`
Expected: 全绿。若有 M6/Task7 历史断言因每日数量变化失败，逐一核对：失败原因应仅来自「每天景点数不再均衡」——这是预期变更，更新该断言为「每天 `day_used_minutes <= DAY_BUDGET`」而非固定数量；几何不变量（transport 配对）断言必须仍通过，不得放宽。

- [ ] **Step 2: 查看 answer 是否需附 dropped 说明**

Run: `sed -n '1,60p' backend/app/graph/nodes/answer.py`
判断：若 answer 节点生成对用户的方案说明文本，则把 `state.get("dropped_attractions")` 的名称/原因拼一句"因时间有限，未安排：X、Y（评分较低）"。若 answer 仅做 QA 透传则跳过本步（不强加）。

- [ ] **Step 3: 若改了 answer，补一条测试**

仅当 Step 2 改了 answer 时，在 `backend/tests/test_answer_dropped.py` 加断言：传入带 `dropped_attractions` 的 state，输出文本含被丢弃景点名。（answer 为纯透传则跳过）

- [ ] **Step 4: 最终回归 + 提交**

Run: `uv run pytest -q`
Expected: 全绿。
```bash
git add -A backend/
git commit -m "test(m6-fix): 全量回归绿，dropped 景点说明收尾"
```

---

## Self-Review（已核对）

- **Spec 覆盖**：设计1富化(Task2)+时长(Task3/8/9)；设计2预算模型(Task3)；设计3预选(Task4)+KMeans(Task5)+复校(Task6)+接线(Task7)；设计4串联(Task9)+refine联动(Task10)+验证(Task7/11)+安全(Task1/8 SecretStr)。dropped_attractions 说明(Task11)。全部有对应任务。
- **占位符**：无 TBD/TODO；每个改代码的步骤都给了完整代码与确切命令。
- **类型一致**：`select_by_rating→(selected,dropped)`、`cluster_kmeans→list[list]`、`rebalance_by_budget→(buckets,dropped)`、`attraction_minutes/transit_minutes/day_used_minutes`、`apply_durations`、`build_tavily_tool`、`_relax_until_budget` 在定义任务与消费任务间签名一致；`OVERHEAD_PER_STOP=40`、`DAY_BUDGET=480` 全程一致。
- **降级路径**：sklearn 缺失→`cluster_by_day`(Task5)；Tavily 缺失→静态表(Task8/9)；LLM/amap 失败→骨架默认(Task7 测试覆盖)。
- **不变量**：transport 配对在 Task7、Task11 显式断言，不放宽。
