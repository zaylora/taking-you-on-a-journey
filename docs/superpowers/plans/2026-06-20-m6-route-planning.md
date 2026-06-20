# M6 路线规划（行程地理质量）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让算法主导行程的几何结构（分天、顺路、就近餐厅、交通段坐标与方式），LLM 只填软字段，从根上消除"路线乱七八糟"。

**Architecture:** 重写 `itinerary` 节点：保留已有 `cluster_by_day` 顺路分天 → 每天用高德周边检索就近餐厅 → 算法拼出"景点+就近餐饮"的停靠点序列 → 在每对相邻停靠点间插入带真实坐标/方式的交通段 → LLM 仅回填 `cost/note/indoor/start/end`，按 `poi_id` 合并、几何与顺序一律以算法为准。前端因数据修好而自动连成完整路线，仅需校验。

**Tech Stack:** Python（LangGraph 节点 + 纯函数）、pytest、httpx、pydantic；前端 Vue3 + 高德 JS SDK（仅校验）。

设计依据：`docs/superpowers/specs/2026-06-20-route-planning-m6-design.md`

## Global Constraints

- **算法权威**：任何任务里，items 的顺序、坐标、交通段的 from/to/mode 一律由算法决定；LLM 只能改 `start/end/cost/indoor/note`，几何性字段一律丢弃 LLM 输出。
- **mode 字符串契约**：交通方式只取三值且必须与前端选插件关键字一致——`"步行"`（→ Walking）/ `"公交"`（→ Transfer）/ `"驾车"`（→ Driving）。
- **距离阈值（itinerary.py 模块级常量）**：`WALK_KM = 1.0`、`TRANSIT_KM = 5.0`、`AROUND_RADIUS_M = 3000`。
- **依赖优先原则（CLAUDE.md）**：haversine 距离选择手写，原因：单一标准公式、项目已有内联 `_dist` 先例、为一个公式引依赖不划算。其余无需新依赖。
- **测试不触网/不触 LLM**：高德用 `tests/conftest.py` 的 `_patch_client`/`fake_amap` 打桩，LLM 用 `make_fake_build_llm` 打桩。
- **提交**：直接在 `main` 上提交；commit message 末尾加一行 `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`。
- 所有 `pytest`/`uv` 命令默认在 `backend/` 目录下执行。

---

### Task 1: 高德周边检索工具 `amap.search_around`

**Files:**
- Modify: `backend/app/tools/amap.py`（在 `search_poi` 后新增 `search_around`）
- Modify: `backend/tests/test_amap.py`（新增降级测试）
- Modify: `backend/tests/conftest.py`（`fake_amap` fixture 增 `search_around`）

**Interfaces:**
- Produces: `async def search_around(lng: float, lat: float, keywords: str, poi_type: str = "", radius: int = 3000, page_size: int = 20) -> list[dict]`，每项 `{name, poi_id, lng, lat, address, type}`；失败/空返回 `[]`。

- [ ] **Step 1: 写失败测试**（在 `backend/tests/test_amap.py` 末尾追加）

```python
@pytest.mark.asyncio
async def test_search_around_ok(monkeypatch):
    _patch_client(monkeypatch, payload={"status": "1", "pois": [
        {"name": "陶陶居", "id": "R1", "location": "113.2617,23.1336",
         "address": "解放北路", "type": "餐饮服务"},
    ]})
    out = await amap.search_around(113.2656, 23.1401, "美食", "餐饮")
    assert out == [{"name": "陶陶居", "poi_id": "R1", "lng": 113.2617, "lat": 23.1336,
                    "address": "解放北路", "type": "餐饮服务"}]


@pytest.mark.asyncio
async def test_search_around_degrades_on_error(monkeypatch):
    _patch_client(monkeypatch, exc=httpx.ConnectError("x"))
    assert await amap.search_around(113.26, 23.14, "美食", "餐饮") == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_amap.py::test_search_around_ok -v`
Expected: FAIL（`AttributeError: module 'app.tools.amap' has no attribute 'search_around'`）

- [ ] **Step 3: 实现 `search_around`**（在 `backend/app/tools/amap.py` 的 `search_poi` 函数之后插入）

```python
@traceable(run_type="tool", name="amap_search_around")
async def search_around(lng: float, lat: float, keywords: str, poi_type: str = "",
                        radius: int = 3000, page_size: int = 20) -> list[dict]:
    """围绕坐标的周边检索（高德 place/around，按距离排序）。结构同 search_poi。失败/空 []。"""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(f"{_BASE}/place/around", params={
                "key": _key(), "location": f"{lng},{lat}", "keywords": keywords,
                "types": poi_type, "radius": radius, "offset": page_size,
                "sortrule": "distance",
            })
            r.raise_for_status()
            data = r.json()
        out = []
        for p in data.get("pois", []) or []:
            loc = (p.get("location") or "").split(",")
            if len(loc) != 2:
                continue
            out.append({
                "name": p.get("name", ""), "poi_id": p.get("id", ""),
                "lng": float(loc[0]), "lat": float(loc[1]),
                "address": p.get("address", ""), "type": p.get("type", ""),
            })
        return out
    except Exception:  # noqa: BLE001
        return []
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_amap.py -v`
Expected: PASS（含新增两条）

- [ ] **Step 5: `fake_amap` fixture 增 `search_around`**（修改 `backend/tests/conftest.py`）

在 `cfg` 字典加一项：

```python
        "search_poi": [],
        "search_around": [],
```

新增异步桩并注册（在 `_search_poi` 定义后、`monkeypatch.setattr` 段内）：

```python
    async def _search_around(lng, lat, keywords, poi_type="", radius=3000, page_size=20):
        return cfg["search_around"]
```
```python
    monkeypatch.setattr(amap, "search_poi", _search_poi)
    monkeypatch.setattr(amap, "search_around", _search_around)
```

- [ ] **Step 6: 跑全量确认无回归**

Run: `uv run pytest -q`
Expected: PASS（全绿）

- [ ] **Step 7: 提交**

```bash
git add backend/app/tools/amap.py backend/tests/test_amap.py backend/tests/conftest.py
git commit -m "$(printf 'feat(m6): 新增 amap.search_around 周边检索 + 测试桩\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

### Task 2: 距离与交通方式纯函数 + 阈值常量

**Files:**
- Modify: `backend/app/graph/nodes/itinerary.py`（顶部加常量；`_dist` 附近加两个纯函数）
- Modify: `backend/tests/test_itinerary.py`（新增纯函数测试）

**Interfaces:**
- Consumes: 无。
- Produces:
  - `WALK_KM = 1.0`、`TRANSIT_KM = 5.0`、`AROUND_RADIUS_M = 3000`（模块级常量）
  - `def haversine_km(a: dict, b: dict) -> float`（a/b 含顶层 `lng`/`lat`）
  - `def mode_by_distance(km: float) -> str`（返回 `"步行"`/`"公交"`/`"驾车"`）

- [ ] **Step 1: 写失败测试**（追加到 `backend/tests/test_itinerary.py`）

```python
def test_haversine_km_known_distance():
    from app.graph.nodes.itinerary import haversine_km
    # 越秀公园 → 广州塔 直线约 7km
    d = haversine_km({"lng": 113.2656, "lat": 23.1401}, {"lng": 113.3245, "lat": 23.1064})
    assert 6.0 < d < 8.0
    assert haversine_km({"lng": 113.0, "lat": 23.0}, {"lng": 113.0, "lat": 23.0}) == 0.0


def test_mode_by_distance_boundaries():
    from app.graph.nodes.itinerary import mode_by_distance
    assert mode_by_distance(0.9) == "步行"
    assert mode_by_distance(1.0) == "公交"
    assert mode_by_distance(4.9) == "公交"
    assert mode_by_distance(5.0) == "驾车"
    assert mode_by_distance(7.1) == "驾车"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_itinerary.py::test_mode_by_distance_boundaries -v`
Expected: FAIL（`ImportError: cannot import name 'mode_by_distance'`）

- [ ] **Step 3: 实现常量与纯函数**（在 `backend/app/graph/nodes/itinerary.py` 中 `import math` 之后加常量；在 `_dist` 函数下方加两函数）

模块顶部（`import math` 之后）：

```python
# —— 路线规划阈值（M6）——
WALK_KM = 1.0          # <1km 步行
TRANSIT_KM = 5.0       # 1~5km 公交（含地铁）；>5km 驾车
AROUND_RADIUS_M = 3000 # 周边餐厅搜索半径(米)
```

在 `_dist(...)` 之后：

```python
def haversine_km(a: dict, b: dict) -> float:
    """两点直线距离(km)。手写标准公式（依赖优先原则：单一公式不引依赖）。"""
    R = 6371.0
    lat1, lat2 = math.radians(a.get("lat", 0.0)), math.radians(b.get("lat", 0.0))
    dlat = lat2 - lat1
    dlng = math.radians(b.get("lng", 0.0) - a.get("lng", 0.0))
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def mode_by_distance(km: float) -> str:
    """按直线距离定交通方式。返回值必须与前端选插件关键字一致。"""
    if km < WALK_KM:
        return "步行"
    if km < TRANSIT_KM:
        return "公交"
    return "驾车"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_itinerary.py::test_haversine_km_known_distance tests/test_itinerary.py::test_mode_by_distance_boundaries -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/graph/nodes/itinerary.py backend/tests/test_itinerary.py
git commit -m "$(printf 'feat(m6): haversine_km + mode_by_distance + 阈值常量\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

### Task 3: 就近挑选 `pick_nearest`

**Files:**
- Modify: `backend/app/graph/nodes/itinerary.py`
- Modify: `backend/tests/test_itinerary.py`

**Interfaces:**
- Consumes: `haversine_km`（Task 2）
- Produces: `def pick_nearest(pool: list[dict], anchor: dict, used: set[str]) -> dict | None`。pool 项含顶层 `lng/lat/poi_id`；anchor 含顶层 `lng/lat`；返回离 anchor 最近且 `poi_id` 不在 `used` 的项，无可选返回 `None`。

- [ ] **Step 1: 写失败测试**（追加到 `backend/tests/test_itinerary.py`）

```python
def test_pick_nearest_selects_closest_and_respects_used():
    from app.graph.nodes.itinerary import pick_nearest
    pool = [
        {"name": "近", "poi_id": "A", "lng": 113.27, "lat": 23.14},
        {"name": "远", "poi_id": "B", "lng": 113.40, "lat": 23.30},
    ]
    anchor = {"lng": 113.27, "lat": 23.14}
    assert pick_nearest(pool, anchor, set())["poi_id"] == "A"
    assert pick_nearest(pool, anchor, {"A"})["poi_id"] == "B"
    assert pick_nearest(pool, anchor, {"A", "B"}) is None
    assert pick_nearest([], anchor, set()) is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_itinerary.py::test_pick_nearest_selects_closest_and_respects_used -v`
Expected: FAIL（`ImportError: cannot import name 'pick_nearest'`）

- [ ] **Step 3: 实现 `pick_nearest`**（加到 `mode_by_distance` 之后）

```python
def pick_nearest(pool: list[dict], anchor: dict, used: set[str]) -> dict | None:
    """从 pool 里挑离 anchor 最近、poi_id 未用过的一项；无则 None。"""
    cands = [p for p in pool if p.get("poi_id") and p["poi_id"] not in used]
    if not cands:
        return None
    return min(cands, key=lambda p: haversine_km(p, anchor))
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_itinerary.py::test_pick_nearest_selects_closest_and_respects_used -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/graph/nodes/itinerary.py backend/tests/test_itinerary.py
git commit -m "$(printf 'feat(m6): pick_nearest 就近去重挑选\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

### Task 4: 停靠点序列 `build_day_stops`

**Files:**
- Modify: `backend/app/graph/nodes/itinerary.py`
- Modify: `backend/tests/test_itinerary.py`

**Interfaces:**
- Consumes: `pick_nearest`（Task 3）
- Produces:
  - `def build_day_stops(attractions_ordered: list[dict], rest_pool: list[dict]) -> list[dict]`
  - 返回顺路停靠点（无交通、无软字段），每项形如 `{"type": "attraction"|"meal", "name", "poi_id", "location": {"lng","lat"}}`。
  - 规则：遍历有序景点，过半处（`(n+1)//2`，仅当 n≥2）插就近午餐，末尾景点附近插就近晚餐；午晚餐 poi 去重。

- [ ] **Step 1: 写失败测试**（追加到 `backend/tests/test_itinerary.py`）

```python
def test_build_day_stops_inserts_nearby_lunch_and_dinner():
    from app.graph.nodes.itinerary import build_day_stops
    attractions = [
        {"name": "A1", "poi_id": "A1", "lng": 113.27, "lat": 23.14},
        {"name": "A2", "poi_id": "A2", "lng": 113.33, "lat": 23.11},
    ]
    pool = [
        {"name": "饭A", "poi_id": "RA", "lng": 113.271, "lat": 23.141},  # 贴 A1
        {"name": "饭B", "poi_id": "RB", "lng": 113.331, "lat": 23.111},  # 贴 A2
    ]
    stops = build_day_stops(attractions, pool)
    assert [s["type"] for s in stops] == ["attraction", "meal", "attraction", "meal"]
    assert stops[0]["poi_id"] == "A1" and stops[2]["poi_id"] == "A2"
    assert stops[1]["poi_id"] == "RA"   # 午餐贴 A1
    assert stops[3]["poi_id"] == "RB"   # 晚餐贴 A2，且与午餐去重
    assert stops[1]["location"] == {"lng": 113.271, "lat": 23.141}


def test_build_day_stops_single_attraction_only_dinner():
    from app.graph.nodes.itinerary import build_day_stops
    stops = build_day_stops(
        [{"name": "A1", "poi_id": "A1", "lng": 113.27, "lat": 23.14}],
        [{"name": "饭A", "poi_id": "RA", "lng": 113.271, "lat": 23.141}],
    )
    assert [s["type"] for s in stops] == ["attraction", "meal"]


def test_build_day_stops_empty_attractions():
    from app.graph.nodes.itinerary import build_day_stops
    assert build_day_stops([], [{"name": "饭", "poi_id": "R", "lng": 1, "lat": 1}]) == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_itinerary.py::test_build_day_stops_inserts_nearby_lunch_and_dinner -v`
Expected: FAIL（`ImportError: cannot import name 'build_day_stops'`）

- [ ] **Step 3: 实现 `build_day_stops` 与两个构造助手**（加到 `pick_nearest` 之后）

```python
def _attraction_item(p: dict) -> dict:
    return {"type": "attraction", "name": p.get("name", ""), "poi_id": p.get("poi_id", ""),
            "location": {"lng": p.get("lng", 0.0), "lat": p.get("lat", 0.0)}}


def _meal_item(p: dict) -> dict:
    return {"type": "meal", "name": p.get("name", ""), "poi_id": p.get("poi_id", ""),
            "location": {"lng": p.get("lng", 0.0), "lat": p.get("lat", 0.0)}}


def build_day_stops(attractions_ordered: list[dict], rest_pool: list[dict]) -> list[dict]:
    """顺路停靠点：景点顺序不变，过半插就近午餐、末尾插就近晚餐（poi 去重）。"""
    stops: list[dict] = []
    n = len(attractions_ordered)
    if n == 0:
        return stops
    used: set[str] = set()
    lunch_after = (n + 1) // 2
    for i, a in enumerate(attractions_ordered, start=1):
        stops.append(_attraction_item(a))
        if n >= 2 and i == lunch_after:
            r = pick_nearest(rest_pool, {"lng": a.get("lng", 0.0), "lat": a.get("lat", 0.0)}, used)
            if r:
                used.add(r["poi_id"])
                stops.append(_meal_item(r))
    last = attractions_ordered[-1]
    dinner = pick_nearest(rest_pool, {"lng": last.get("lng", 0.0), "lat": last.get("lat", 0.0)}, used)
    if dinner:
        used.add(dinner["poi_id"])
        stops.append(_meal_item(dinner))
    return stops
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_itinerary.py -k build_day_stops -v`
Expected: PASS（3 条）

- [ ] **Step 5: 提交**

```bash
git add backend/app/graph/nodes/itinerary.py backend/tests/test_itinerary.py
git commit -m "$(printf 'feat(m6): build_day_stops 顺路景点+就近餐饮停靠序列\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

### Task 5: 交通段插入 `insert_transport` + `default_cost_by_mode`

**Files:**
- Modify: `backend/app/graph/nodes/itinerary.py`
- Modify: `backend/tests/test_itinerary.py`

**Interfaces:**
- Consumes: `haversine_km`、`mode_by_distance`（Task 2）
- Produces:
  - `def default_cost_by_mode(mode: str, km: float) -> float`（步行 0 / 公交 3 / 驾车 `round(2+2*km,1)`）
  - `def insert_transport(stops: list[dict]) -> list[dict]`：N 个停靠点 → 交错出 N-1 个交通段；每段 `{"type":"transport","name":"","from":<前点名>,"to":<后点名>,"location":<前点坐标>,"mode":<按距离>,"cost":<按mode>}`。

- [ ] **Step 1: 写失败测试**（追加到 `backend/tests/test_itinerary.py`）

```python
def test_default_cost_by_mode():
    from app.graph.nodes.itinerary import default_cost_by_mode
    assert default_cost_by_mode("步行", 0.5) == 0.0
    assert default_cost_by_mode("公交", 3.0) == 3.0
    assert default_cost_by_mode("驾车", 10.0) > default_cost_by_mode("驾车", 1.0)


def test_insert_transport_links_every_adjacent_pair():
    from app.graph.nodes.itinerary import insert_transport
    stops = [
        {"type": "attraction", "name": "越秀公园", "poi_id": "A1",
         "location": {"lng": 113.2656, "lat": 23.1401}},
        {"type": "attraction", "name": "广州塔", "poi_id": "A2",
         "location": {"lng": 113.3245, "lat": 23.1064}},
        {"type": "meal", "name": "饭", "poi_id": "R1",
         "location": {"lng": 113.325, "lat": 23.107}},
    ]
    out = insert_transport(stops)
    assert [it["type"] for it in out] == ["attraction", "transport", "attraction", "transport", "meal"]
    seg = out[1]
    assert seg["from"] == "越秀公园" and seg["to"] == "广州塔"
    assert seg["location"] == {"lng": 113.2656, "lat": 23.1401}  # 起点坐标=前点
    assert seg["mode"] == "驾车"   # ~7km
    assert out[3]["mode"] == "步行"  # 广州塔→饭 很近
    assert insert_transport(stops[:1]) == stops[:1]  # 单点不插段
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_itinerary.py::test_insert_transport_links_every_adjacent_pair -v`
Expected: FAIL（`ImportError: cannot import name 'insert_transport'`）

- [ ] **Step 3: 实现两函数**（加到 `build_day_stops` 之后）

```python
def default_cost_by_mode(mode: str, km: float) -> float:
    """交通段人均粗估(元)：步行 0 / 公交 3 / 驾车 起步+里程。不进 LLM，保证 budget 汇总稳定。"""
    if mode == "步行":
        return 0.0
    if mode == "公交":
        return 3.0
    return round(2.0 + 2.0 * km, 1)


def _transport_item(p: dict, q: dict) -> dict:
    lp, lq = p["location"], q["location"]
    km = haversine_km(lp, lq)
    mode = mode_by_distance(km)
    return {"type": "transport", "name": "",
            "from": p.get("name", ""), "to": q.get("name", ""),
            "location": {"lng": lp["lng"], "lat": lp["lat"]},
            "mode": mode, "cost": default_cost_by_mode(mode, km)}


def insert_transport(stops: list[dict]) -> list[dict]:
    """在每对相邻停靠点间插一个交通段（起讫坐标沿用相邻点，mode 按直线距离）。"""
    if len(stops) < 2:
        return list(stops)
    out = [stops[0]]
    for prev, cur in zip(stops, stops[1:]):
        out.append(_transport_item(prev, cur))
        out.append(cur)
    return out
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_itinerary.py -k "insert_transport or default_cost" -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/graph/nodes/itinerary.py backend/tests/test_itinerary.py
git commit -m "$(printf 'feat(m6): insert_transport 每跳插交通段 + default_cost_by_mode\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

### Task 6: 软字段合并 `merge_soft_fields`

**Files:**
- Modify: `backend/app/graph/nodes/itinerary.py`
- Modify: `backend/tests/test_itinerary.py`

**Interfaces:**
- Consumes: 无（纯函数）
- Produces: `def merge_soft_fields(skeleton_days: list[dict], llm_days: list[dict]) -> list[dict]`。按 `day` 对齐、按 `poi_id` 对齐非交通停靠点，仅把 LLM 的 `start/end/cost/indoor/note`（非空才覆盖）合并到骨架；交通段与所有几何字段（顺序/坐标/from/to/mode）原样保留。

- [ ] **Step 1: 写失败测试**（追加到 `backend/tests/test_itinerary.py`）

```python
def test_merge_soft_fields_only_copies_soft_keeps_geometry():
    from app.graph.nodes.itinerary import merge_soft_fields
    skeleton = [{
        "day": 1, "center": {"lng": 0, "lat": 0},
        "items": [
            {"type": "attraction", "name": "越秀公园", "poi_id": "A1",
             "location": {"lng": 113.27, "lat": 23.14}},
            {"type": "transport", "name": "", "from": "越秀公园", "to": "广州塔",
             "location": {"lng": 113.27, "lat": 23.14}, "mode": "驾车", "cost": 16.0},
            {"type": "attraction", "name": "广州塔", "poi_id": "A2",
             "location": {"lng": 113.32, "lat": 23.11}},
        ],
    }]
    # LLM 故意打乱顺序、改坐标、改 mode —— 都必须被丢弃
    llm = [{
        "day": 1,
        "items": [
            {"type": "attraction", "poi_id": "A2", "location": {"lng": 0, "lat": 0},
             "start": "14:00", "end": "16:00", "cost": 150.0, "indoor": True, "note": "登塔"},
            {"type": "attraction", "poi_id": "A1", "location": {"lng": 9, "lat": 9},
             "start": "09:00", "end": "11:00", "cost": 0.0, "note": "免费公园"},
            {"type": "transport", "mode": "步行", "cost": 0.0},
        ],
    }]
    out = merge_soft_fields(skeleton, llm)
    items = out[0]["items"]
    # 顺序与坐标来自骨架
    assert [it.get("poi_id", it["type"]) for it in items] == ["A1", "transport", "A2"]
    assert items[0]["location"] == {"lng": 113.27, "lat": 23.14}
    assert items[2]["location"] == {"lng": 113.32, "lat": 23.11}
    # 软字段来自 LLM
    assert items[0]["note"] == "免费公园" and items[0]["start"] == "09:00"
    assert items[2]["cost"] == 150.0 and items[2]["indoor"] is True
    # 交通段几何不动
    assert items[1]["mode"] == "驾车" and items[1]["cost"] == 16.0


def test_merge_soft_fields_tolerates_missing_llm_day():
    from app.graph.nodes.itinerary import merge_soft_fields
    skeleton = [{"day": 1, "center": {}, "items": [
        {"type": "attraction", "name": "X", "poi_id": "A1", "location": {"lng": 1, "lat": 1}}]}]
    out = merge_soft_fields(skeleton, [])   # LLM 全空 → 原样返回骨架
    assert out[0]["items"][0]["poi_id"] == "A1"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_itinerary.py::test_merge_soft_fields_only_copies_soft_keeps_geometry -v`
Expected: FAIL（`ImportError: cannot import name 'merge_soft_fields'`）

- [ ] **Step 3: 实现 `merge_soft_fields`**（加到 `insert_transport` 之后）

```python
_SOFT_FIELDS = ("start", "end", "cost", "indoor", "note")


def merge_soft_fields(skeleton_days: list[dict], llm_days: list[dict]) -> list[dict]:
    """把 LLM 的软字段合并进算法骨架：按 day + poi_id 对齐非交通项，仅覆盖非空软字段；
    顺序、坐标、交通段一律以骨架为准。纯函数，不改输入。"""
    llm_by_day = {d.get("day"): d for d in llm_days}
    out = []
    for sd in skeleton_days:
        ld = llm_by_day.get(sd.get("day"), {}) or {}
        soft_by_poi = {it.get("poi_id"): it for it in ld.get("items", [])
                       if it.get("type") != "transport" and it.get("poi_id")}
        new_items = []
        for it in sd.get("items", []):
            merged = dict(it)
            if it.get("type") != "transport":
                src = soft_by_poi.get(it.get("poi_id"))
                if src:
                    for k in _SOFT_FIELDS:
                        v = src.get(k)
                        if v not in (None, ""):
                            merged[k] = v
            new_items.append(merged)
        nd = dict(sd)
        nd["items"] = new_items
        out.append(nd)
    return out
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_itinerary.py -k merge_soft_fields -v`
Expected: PASS（2 条）

- [ ] **Step 5: 提交**

```bash
git add backend/app/graph/nodes/itinerary.py backend/tests/test_itinerary.py
git commit -m "$(printf 'feat(m6): merge_soft_fields 仅并软字段、几何以算法为准\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

### Task 7: 重写 `itinerary` 节点（拼装 + LLM 软填）

**Files:**
- Modify: `backend/app/graph/nodes/itinerary.py`（改 `_SYS`→软填提示、替 `_build_payload`、重写 `async def itinerary`、加 `import`）
- Modify: `backend/tests/test_itinerary.py`（更新既有节点测试 + 新增就近/分段集成断言）

**Interfaces:**
- Consumes: `cluster_by_day`、`build_day_stops`（Task 4）、`insert_transport`（Task 5）、`merge_soft_fields`（Task 6）、`amap.search_around`（Task 1）、`build_llm`、`DayPlans`
- Produces: `async def itinerary(state, config) -> dict`，返回 `{daily_centers, day_plans, plan_version, changed_days}`；`day_plans[*].items` 由算法定结构、LLM 填软字段。

- [ ] **Step 1: 更新既有节点测试为新契约 + 新增集成测试**

在 `backend/tests/test_itinerary.py` 中**替换** `test_itinerary_produces_day_plans` 为下面版本（既有版没 patch `search_around`，新节点会调用它）：

```python
@pytest.mark.asyncio
async def test_itinerary_algorithm_owns_geometry(monkeypatch, fake_amap):
    """算法定结构：景点在前、每跳有交通段、餐厅取自周边池；LLM 只补软字段。"""
    from tests.conftest import make_fake_build_llm
    from app.graph.nodes import itinerary as it_mod
    # 周边餐厅池（贴近景点）
    fake_amap["search_around"] = [
        {"name": "塔下饭", "poi_id": "R1", "lng": 113.325, "lat": 23.107,
         "address": "", "type": "餐饮服务"},
    ]
    # LLM 软填：给景点 A1 一个 cost/note
    fake = DayPlans(days=[DayPlan(
        day=1, center=Location(lng=113.30, lat=23.12),
        items=[PlanItem(type="attraction", name="广州塔", poi_id="A1",
                        location=Location(lng=113.3245, lat=23.1064),
                        cost=150.0, note="登塔看夜景")],
    )])
    monkeypatch.setattr(it_mod, "build_llm", make_fake_build_llm(structured=fake))
    state = {"days": 1, "preferences": {"food": "粤菜"},
             "attractions": [{"name": "广州塔", "poi_id": "A1", "lng": 113.3245, "lat": 23.1064}],
             "restaurants": [], "weather": {"is_rainy": False}}
    out = await it_mod.itinerary(state, None)
    items = out["day_plans"][0]["items"]
    types = [it["type"] for it in items]
    assert types[0] == "attraction" and items[0]["poi_id"] == "A1"
    assert "transport" in types                      # 至少一段交通（景点→晚餐）
    assert any(it["type"] == "meal" and it["poi_id"] == "R1" for it in items)  # 餐厅取自周边
    assert items[0]["cost"] == 150.0 and items[0]["note"] == "登塔看夜景"      # 软字段合并
    assert len(out["daily_centers"]) == 1
    assert out["plan_version"] == 1
```

**替换** `test_build_payload_injects_budget_advice` 为（对齐新 `_build_payload(skeleton_days, state)` 签名）：

```python
def test_build_payload_injects_budget_advice():
    from app.graph.nodes.itinerary import _build_payload
    skeleton = [{"day": 1, "items": [], "center": {"lng": 0, "lat": 0}}]
    base = {"days": 1, "num_people": 2, "weather": {"is_rainy": False}}
    assert "budget_advice" not in _build_payload(skeleton, base)
    p = _build_payload(skeleton, {**base, "budget_advice": {"over_amount": 500.0}})
    assert p["budget_advice"]["over_amount"] == 500.0
    assert p["num_people"] == 2
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_itinerary.py::test_itinerary_algorithm_owns_geometry -v`
Expected: FAIL（断言失败或属性错误——旧节点未调 `search_around`、未做就近/分段）

- [ ] **Step 3: 重写节点**。在 `backend/app/graph/nodes/itinerary.py`：

(a) 文件顶部 import 段加：

```python
from app.tools import amap
```

(b) 把原 `_SYS` 字符串替换为软填提示：

```python
_SYS = (
    "你是行程编排助手。下面给你的是已经排好顺序、坐标固定的逐日骨架（景点/餐饮/交通段都已确定）。"
    "你的唯一任务：为每个『景点』和『餐饮』项补充 start/end（HH:MM）、cost（人均元）、indoor（是否室内）、note（一句话）。"
    "严禁修改名称、坐标、顺序，严禁增删项，严禁改交通段。雨天优先把户外项标注合理。"
    "若输入含 budget_advice（上轮超支额），据此压低 cost 估计。"
    "按给定结构原样返回（含未改动的 location/poi_id/type）。"
)
```

(c) 把原 `_build_payload(state, clusters, days=None)` 整个替换为：

```python
def _build_payload(skeleton_days: list, state: dict) -> dict:
    """构造软填 LLM 的输入：骨架（仅供补软字段）+ 天气 + 可选 budget_advice。纯函数，便于单测。"""
    payload = {
        "skeleton": [{"day": d["day"],
                      "items": [{"type": it["type"], "name": it.get("name", ""),
                                 "poi_id": it.get("poi_id", "")} for it in d["items"]]}
                     for d in skeleton_days],
        "weather": state.get("weather", {}),
        "num_people": state.get("num_people", 1) or 1,
    }
    advice = state.get("budget_advice")
    if advice:
        payload["budget_advice"] = advice
    return payload
```

(d) 把原 `async def itinerary(...)` 整个替换为：

```python
async def itinerary(state, config) -> dict:
    days = state.get("days", 3) or 3
    attractions = state.get("attractions", []) or []
    clusters = cluster_by_day(attractions, days)

    daily_centers = []
    for c in clusters:
        if c:
            cx = sum(p.get("lng", 0.0) for p in c) / len(c)
            cy = sum(p.get("lat", 0.0) for p in c) / len(c)
        else:
            cx = cy = 0.0
        daily_centers.append({"lng": cx, "lat": cy})

    food_kw = (state.get("preferences") or {}).get("food") or "美食"
    city_pool = state.get("restaurants", []) or []  # 周边搜索为空时兜底

    skeleton_days = []
    for d, (cluster, center) in enumerate(zip(clusters, daily_centers), start=1):
        pool = []
        if center["lng"] or center["lat"]:
            pool = await amap.search_around(center["lng"], center["lat"],
                                            food_kw, "餐饮", AROUND_RADIUS_M)
        if not pool:
            pool = city_pool
        stops = build_day_stops(cluster, pool)
        items = insert_transport(stops)
        skeleton_days.append({"day": d, "items": items, "center": center})

    # LLM 仅填软字段；失败则全用骨架默认
    llm = build_llm(temperature=0).with_structured_output(DayPlans, method="function_calling")
    try:
        result = await llm.ainvoke([
            SystemMessage(content=_SYS),
            HumanMessage(content=str(_build_payload(skeleton_days, state))),
        ], config=config)
        llm_days = [d.model_dump(by_alias=True) for d in result.days]
    except Exception:  # noqa: BLE001 —— 软填失败不阻断，几何已就绪
        llm_days = []

    merged = merge_soft_fields(skeleton_days, llm_days)
    return {
        "daily_centers": daily_centers,
        "day_plans": merged,
        "plan_version": (state.get("plan_version", 0) or 0) + 1,
        "changed_days": [d["day"] for d in merged],
    }
```

- [ ] **Step 4: 运行 itinerary 测试确认通过**

Run: `uv run pytest tests/test_itinerary.py -v`
Expected: PASS（含更新后的节点测试与 `_build_payload` 测试）

- [ ] **Step 5: 跑全量回归**

Run: `uv run pytest -q`
Expected: PASS（全绿；如 `test_builder`/`test_chat_stream*`/`test_budget` 等依赖 itinerary 输出的用例有红，按"几何来自算法、软字段来自 LLM"语义修正断言，不得放宽几何约束）

- [ ] **Step 6: 提交**

```bash
git add backend/app/graph/nodes/itinerary.py backend/tests/test_itinerary.py
git commit -m "$(printf 'feat(m6): 重写 itinerary——算法主导几何、LLM 只填软字段\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

### Task 8: 前端校验与按需微调

**Files:**
- 校验（一般无需改）：`frontend/src/composables/useAMap.ts`、`frontend/src/components/MapView.vue`

**Interfaces:**
- Consumes: 后端新 `day_plans`（每跳都有交通段、mode∈{步行,公交,驾车}、交通段不接酒店）

- [ ] **Step 1: 启动前后端，重跑截图同款用例**

用 `run` 技能或手动：后端 `uv run uvicorn app.main:app --reload`，前端 `bun run dev`。发起"广州 玩 3 天"，等行程生成。

- [ ] **Step 2: 按验收清单肉眼核对**

- 总览：每天路线连续（不再只连一段），按天配色；
- 餐厅点贴着当天景点簇，无"折返市中心吃饭"的长腿；
- 选中某交通段：只显示起讫两点 + 该段路线，mode 与卡片一致（7km 不再标步行）；
- 切到"按天"：单天路线正确。

- [ ] **Step 3:（条件）仅当发现分段间有缝隙/孤儿线时微调**

仅在 [useAMap.ts](frontend/src/composables/useAMap.ts) 的 `drawOverviewRoute` 内做最小修正（如某 mode 未命中插件分支）。**不重写**该函数。若 Step 2 全部通过，跳过本步，无代码改动。

- [ ] **Step 4:（条件）提交前端微调**

仅当 Step 3 有改动：

```bash
git add frontend/src/composables/useAMap.ts frontend/src/components/MapView.vue
git commit -m "$(printf 'fix(m6): 前端分段总览路线微调对齐后端干净分段\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

- [ ] **Step 5: 更新 README 验收清单（若有 M 验收惯例）**

若 `backend/README` 有逐 M 验收清单，追加 M6 一节（餐厅就近、每跳有段、总览连续）。提交：

```bash
git add backend/README*.md
git commit -m "$(printf 'docs(m6): README 增 M6 路线规划验收清单\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

## Self-Review

**Spec coverage：**
- 决策"算法主导/LLM 软填" → Task 4-7（结构纯函数 + 节点 + merge）。✅
- "按簇周边搜索" → Task 1（`search_around`）+ Task 7（节点按簇中心调用）。✅
- "后端出干净分段、前端画线" → Task 5（`insert_transport`，坐标/from/to/mode）+ Task 8（前端校验）。✅
- mode 字符串契约（步行/公交/驾车） → Task 2 `mode_by_distance` + 测试边界。✅
- 阈值 1km/5km/3000m → Task 2 常量。✅
- 交通段 cost 不进 LLM → Task 5 `default_cost_by_mode` + Task 6 仅并停靠点软字段。✅
- 周边为空兜底全城池 → Task 7 `city_pool` 回退。✅
- 里程碑重排 → 已在 spec 提交时落 `项目策划书.md`（本计划不再重复）。✅

**Placeholder scan：** 无 TBD/TODO；每个代码步给出完整代码。Task 8 的"条件步"是显式的 if-then，非占位。✅

**Type consistency：** `haversine_km`/`pick_nearest` 入参用顶层 `lng/lat`；`build_day_stops` 产出 `location:{lng,lat}`；`insert_transport`/`merge_soft_fields` 一致用 `it["location"]["lng"]`。节点 `_build_payload(skeleton_days, state)` 与测试调用一致。`mode_by_distance` 返回值与前端关键字一致。✅
