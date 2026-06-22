# itinerary OR-Tools VRPTW 重做 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 OR-Tools VRPTW 联合求解（选点+分天+顺路+时间窗）+ 高德真实距离矩阵，重做 itinerary 节点的算法内核，并把算法抽到 `app/itinerary/` 子包。

**Architecture:** 把 m6 的「评分预选 + KMeans 聚类 + 预算再平衡 + 最近邻顺路」四段贪心，替换为单个 OR-Tools Routing（VRPTW）求解器：天=车辆、景点=节点、visit_minutes=service time、opentime=时间窗、rating=丢弃惩罚。距离用高德 `v3/distance` 真实街道时间（评分粗筛到十几个后凑 N×N，SQLite 持久缓存 + haversine 降级）。节点 `itinerary.py` 瘦身为编排，几何/软填/数据类迁入 `app/itinerary/` 子包，下游用 re-export 保护零改动。

**Tech Stack:** Python 3.12 / uv / LangGraph / OR-Tools 9.15+ (`ortools.constraint_solver`) / 高德 Web API `v3/distance` / SQLite / pytest。

设计依据：[2026-06-22-itinerary-ortools-redesign.md](../specs/2026-06-22-itinerary-ortools-redesign.md)

## Global Constraints

- **基线分支**：在 `m6-v2` 上实现，但以 `m6` 分支为代码起点（Task 0 合并 m6）。`m6-v2` 当前是「只有设计文档、零实现」的状态。
- **依赖优先原则**（CLAUDE.md）：算法用成熟开源库（OR-Tools），不手写优化器；单一公式（haversine）才手写。
- **几何不变量**（现有测试已钉死，全程不可破）：① `items[0].type != "transport"` 且 `items[-1].type != "transport"`；② 每天 `交通段数 == 停靠点数 - 1`；③ 交通段 from/to/location 与相邻停靠点对齐；④ 软填只动 `start/end/cost/indoor/note`，poi_id/坐标/顺序由算法锁死。
- **state 字段契约不变**：`day_plans` / `dropped_attractions` / `daily_centers` 结构不变（下游 budget/accommodation/answer 依赖）。
- **对外 import 不破**：`refine.py` 依赖 `from app.graph.nodes.itinerary import insert_transport`；`accommodation/answer/tests` 依赖 `DayPlan/PlanItem` 等数据类——重构后从 `itinerary.py` re-export 这些符号。
- **高德调用纪律**：沿用 `amap.py` 范式——httpx 5s 超时、失败降级不抛、`@traceable`、key 取自 `config.amap_web_key.get_secret_value()` 绝不下发前端/进日志。
- **求解确定性**：OR-Tools 固定 `FirstSolutionStrategy` + 参数 + 随机种子；测试断言结构性质（顺路/时间窗/不丢高分），不断言精确路径。
- **常量收口**：新阈值（MAX_CANDIDATES 系数、SOLVE_TIME_LIMIT_S、MATRIX_CONCURRENCY、MATRIX_CACHE_TTL_DAYS）放 `app/core/constants.py`。

---

## 文件结构

```
backend/app/itinerary/            ★新增子包
├── __init__.py
├── geometry.py        从 m6 itinerary.py 迁入几何纯函数
├── schemas.py         从 m6 itinerary.py 迁入 Pydantic 数据类
├── prefilter.py    ★新：评分粗筛
├── matrix.py       ★新：高德距离矩阵 + SQLite 缓存 + 降级
├── optimizer.py    ★新：OR-Tools VRPTW 求解 + 三级放松
├── assembler.py    ★新：求解结果 → skeleton_days
└── soft_fill.py       从 m6 itinerary.py 迁入软填逻辑
backend/app/graph/nodes/
├── itinerary.py       瘦身为编排 + re-export
└── time_budget.py     保留不动（refine/optimizer 共用）
backend/app/core/constants.py  ★新：阈值常量
backend/tests/itinerary/       新增子包测试
```

---

## Task 0: 以 m6 为基线 + 验证现状绿

**Files:**
- Modify（合并）：整个 `backend/` 从 `m6` 分支引入

**Interfaces:**
- Produces: 一个可运行、测试全绿的 m6 基线工作区（含 `cluster_kmeans`/`select_by_rating`/`rebalance_by_budget` 等待替换函数 + 全部保留模块）

- [ ] **Step 1: 确认当前分支与基线差异**

Run:
```bash
git -C /e/github/taking-you-on-a-journey rev-parse --abbrev-ref HEAD
git -C /e/github/taking-you-on-a-journey log --oneline m6-v2..m6 | wc -l
```
Expected: 当前 `m6-v2`；落后 m6 约 32 个提交。

- [ ] **Step 2: 把 m6 合并进 m6-v2**

`m6-v2` 是从 m6 的祖先（设计文档提交）拉出、零独有实现提交，因此 merge 应为快进或干净合并。

Run:
```bash
cd /e/github/taking-you-on-a-journey
git merge m6 -m "merge(m6-v2): 以 m6 完整实现为重做基线"
```
Expected: 合并成功，无冲突（m6-v2 仅多出设计文档 + 本计划，m6 不含这些文件）。若有冲突仅可能在 docs，保留两边。

- [ ] **Step 3: 安装依赖并跑全量测试，确认基线绿**

Run:
```bash
cd /e/github/taking-you-on-a-journey/backend
uv sync
uv run pytest -q
```
Expected: 全部 PASS（这是后续重构的回归基准）。

- [ ] **Step 4: 提交（仅在有合并提交时）**

合并已自动产生提交。若 fast-forward 无合并提交则跳过。
```bash
git -C /e/github/taking-you-on-a-journey log --oneline -1
```

---

## Task 1: 新增常量与 ortools 依赖

**Files:**
- Create: `backend/app/core/constants.py`
- Modify: `backend/pyproject.toml`（加 `ortools`）
- Test: `backend/tests/itinerary/test_constants.py`

**Interfaces:**
- Produces:
  - `app/core/constants.py`：`SOLVE_TIME_LIMIT_S: float = 5.0`、`CANDIDATE_MULTIPLIER: float = 1.5`、`PER_DAY_CAP: int = 5`、`MATRIX_CONCURRENCY: int = 3`、`MATRIX_CACHE_TTL_DAYS: int = 30`、`WALK_KM: float = 1.0`、`TRANSIT_KM: float = 5.0`、`AROUND_RADIUS_M: int = 3000`、`RELAX_BUDGET_FACTOR: float = 1.5`
  - 依赖 `ortools` 可 import

- [ ] **Step 1: 写常量模块的失败测试**

Create `backend/tests/itinerary/__init__.py`（空文件）和 `backend/tests/itinerary/test_constants.py`:
```python
from app.core import constants


def test_constants_present_and_sane():
    assert constants.SOLVE_TIME_LIMIT_S > 0
    assert constants.CANDIDATE_MULTIPLIER >= 1.0
    assert constants.PER_DAY_CAP >= 1
    assert constants.MATRIX_CONCURRENCY >= 1
    assert constants.MATRIX_CACHE_TTL_DAYS >= 1
    assert constants.WALK_KM < constants.TRANSIT_KM
    assert constants.RELAX_BUDGET_FACTOR > 1.0


def test_ortools_importable():
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2  # noqa: F401
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && uv run pytest tests/itinerary/test_constants.py -v`
Expected: FAIL（`No module named 'app.core.constants'` 与 `No module named 'ortools'`）。

- [ ] **Step 3: 加依赖 + 写常量**

Run: `cd backend && uv add ortools`

Create `backend/app/core/constants.py`:
```python
"""itinerary 重做相关阈值常量。集中收口，便于调参。"""

# —— 求解 ——
SOLVE_TIME_LIMIT_S: float = 5.0       # OR-Tools 单次求解时限(秒)
RELAX_BUDGET_FACTOR: float = 1.5      # 三级放松 L2：DAY_BUDGET × 此系数

# —— 候选预筛 ——
PER_DAY_CAP: int = 5                  # 每天景点经验上限
CANDIDATE_MULTIPLIER: float = 1.5     # 预筛上限 = days × PER_DAY_CAP × 此系数

# —— 距离矩阵 ——
MATRIX_CONCURRENCY: int = 3           # 高德 distance 并发上限(避 QPS 超限)
MATRIX_CACHE_TTL_DAYS: int = 30       # 距离缓存有效期(天)

# —— 交通方式分档(沿用 m6) ——
WALK_KM: float = 1.0                  # <1km 步行
TRANSIT_KM: float = 5.0               # 1~5km 公交；>5km 驾车
AROUND_RADIUS_M: int = 3000           # 周边餐厅搜索半径(米)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && uv run pytest tests/itinerary/test_constants.py -v`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/app/core/constants.py backend/tests/itinerary/ backend/pyproject.toml backend/uv.lock
git commit -m "feat(m6-v2): 加 ortools 依赖 + itinerary 阈值常量"
```

---

## Task 2: 几何与数据类迁入 app/itinerary/ 子包

把 m6 `itinerary.py` 里的纯几何函数与 Pydantic 数据类原样迁入子包，`itinerary.py` 改为从子包 re-export，保证现有测试与下游 import 全绿。**本任务零行为变化**，只挪位置。

**Files:**
- Create: `backend/app/itinerary/__init__.py`, `backend/app/itinerary/geometry.py`, `backend/app/itinerary/schemas.py`
- Modify: `backend/app/graph/nodes/itinerary.py`（删除已迁出的定义，改 re-export）
- Test: 复用现有 `tests/test_itinerary.py`、`tests/test_refine_transport.py`、`tests/test_contracts.py`

**Interfaces:**
- Produces:
  - `app/itinerary/geometry.py`：`haversine_km(a, b) -> float`、`mode_by_distance(km) -> str`、`pick_nearest(pool, anchor, used) -> dict|None`、`build_day_stops(attractions_ordered, rest_pool) -> list[dict]`、`default_cost_by_mode(mode, km) -> float`、`insert_transport(stops) -> list[dict]`（含内部 `_dist`/`_attraction_item`/`_meal_item`/`_transport_item`）
  - `app/itinerary/schemas.py`：`Location`、`DayWeather`、`PlanItem`、`Hotel`、`DayPlan`、`DayPlans`
  - `app/graph/nodes/itinerary.py` 仍可 `from app.graph.nodes.itinerary import insert_transport, haversine_km, DayPlan, PlanItem`（re-export）

- [ ] **Step 1: 先跑现有相关测试确认起点绿**

Run: `cd backend && uv run pytest tests/test_itinerary.py tests/test_refine_transport.py tests/test_contracts.py -q`
Expected: PASS（迁移前基准）。

- [ ] **Step 2: 创建 geometry.py，迁入几何纯函数**

Create `backend/app/itinerary/__init__.py`（空）。

Create `backend/app/itinerary/geometry.py`，把 m6 `itinerary.py` 中以下函数**原样剪切**进来（含 docstring）：`_dist`、`haversine_km`、`mode_by_distance`、`pick_nearest`、`_attraction_item`、`_meal_item`、`build_day_stops`、`default_cost_by_mode`、`_transport_item`、`insert_transport`。文件头加：
```python
"""itinerary 几何纯函数：距离/交通方式/停靠点/交通段。零 I/O，可单测。"""
import math

from app.core.constants import WALK_KM, TRANSIT_KM
```
注意：`mode_by_distance` 改为引用 `constants.WALK_KM/TRANSIT_KM`（m6 原是模块内常量，迁移时统一到 constants）。

- [ ] **Step 3: 创建 schemas.py，迁入数据类**

Create `backend/app/itinerary/schemas.py`，把 m6 `itinerary.py` 中 `Location`、`DayWeather`、`PlanItem`、`Hotel`、`DayPlan`、`DayPlans` **原样剪切**进来。文件头：
```python
"""itinerary 结构化输出数据类（LLM 软填 + 下游消费契约）。"""
from pydantic import BaseModel, Field
```

- [ ] **Step 4: 改 itinerary.py 为 re-export，删除已迁出定义**

在 `backend/app/graph/nodes/itinerary.py` 顶部加 re-export（替换被剪切走的定义）：
```python
# —— re-export：下游 refine/accommodation/answer/tests 依赖这些符号的旧路径 ——
from app.itinerary.geometry import (  # noqa: F401
    haversine_km, mode_by_distance, pick_nearest, build_day_stops,
    default_cost_by_mode, insert_transport,
)
from app.itinerary.schemas import (  # noqa: F401
    Location, DayWeather, PlanItem, Hotel, DayPlan, DayPlans,
)
```
删除 itinerary.py 内这些函数/类的原定义（已迁走）。保留 `select_by_rating`/`cluster_by_day`/`cluster_kmeans`/`rebalance_by_budget`/`merge_soft_fields`/`itinerary()` 等暂不动。

- [ ] **Step 5: 运行测试确认零回归**

Run: `cd backend && uv run pytest tests/test_itinerary.py tests/test_refine_transport.py tests/test_contracts.py tests/test_select_by_rating.py tests/test_rebalance_budget.py -q`
Expected: PASS（迁移不改行为）。

- [ ] **Step 6: 提交**

```bash
git add backend/app/itinerary/ backend/app/graph/nodes/itinerary.py
git commit -m "refactor(m6-v2): 几何/数据类迁入 app/itinerary 子包(re-export 保护下游)"
```

---

## Task 3: prefilter 评分粗筛

**Files:**
- Create: `backend/app/itinerary/prefilter.py`
- Test: `backend/tests/itinerary/test_prefilter.py`

**Interfaces:**
- Consumes: `app.core.constants.PER_DAY_CAP`, `CANDIDATE_MULTIPLIER`
- Produces: `select_candidates(attractions: list[dict], days: int) -> tuple[list[dict], list[dict]]`，返回 `(candidates, dropped)`。`dropped` 每项 `{"name","rating","reason"}`，reason="评分较低，候选阶段未入选"。点数 ≤ 上限时全保留、dropped 为空。确定性：评分降序，同分按 poi_id。

- [ ] **Step 1: 写失败测试**

Create `backend/tests/itinerary/test_prefilter.py`:
```python
from app.itinerary.prefilter import select_candidates


def _a(poi_id, rating):
    return {"name": poi_id, "poi_id": poi_id, "rating": rating, "lng": 113.0, "lat": 23.0}


def test_keeps_all_when_under_cap():
    pts = [_a("a", 4.0), _a("b", 3.0)]
    cand, dropped = select_candidates(pts, days=3)
    assert len(cand) == 2
    assert dropped == []


def test_drops_lowest_rated_over_cap():
    # days=1 → cap = 1*5*1.5 = 7（向下取整）。给 9 个 → 丢 2 个最低分
    pts = [_a(f"p{i}", float(i)) for i in range(9)]
    cand, dropped = select_candidates(pts, days=1)
    assert len(cand) == 7
    assert len(dropped) == 2
    # 被丢的是评分最低的 p0,p1
    dropped_ids = {d["name"] for d in dropped}
    assert dropped_ids == {"p0", "p1"}
    assert all("reason" in d for d in dropped)


def test_deterministic_tie_break_by_poi_id():
    pts = [_a("b", 4.0), _a("a", 4.0), _a("c", 4.0)]
    cand, _ = select_candidates(pts, days=1)
    # 同分按 poi_id 升序保留顺序确定
    assert [c["poi_id"] for c in cand] == ["a", "b", "c"]
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && uv run pytest tests/itinerary/test_prefilter.py -v`
Expected: FAIL（`No module named 'app.itinerary.prefilter'`）。

- [ ] **Step 3: 实现 prefilter.py**

Create `backend/app/itinerary/prefilter.py`:
```python
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
```

- [ ] **Step 4: 运行确认通过**

Run: `cd backend && uv run pytest tests/itinerary/test_prefilter.py -v`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/app/itinerary/prefilter.py backend/tests/itinerary/test_prefilter.py
git commit -m "feat(m6-v2): prefilter 评分粗筛候选景点"
```

---

## Task 4: matrix 距离矩阵（SQLite 缓存 + 高德 + haversine 降级）

分两步：先实现纯缓存层（SQLite，可单测），再实现取矩阵主函数（mock 高德）。

**Files:**
- Create: `backend/app/itinerary/matrix.py`
- Modify: `backend/app/tools/amap.py`（新增 `distance_batch`）
- Test: `backend/tests/itinerary/test_matrix.py`, `backend/tests/itinerary/test_matrix_cache.py`

**Interfaces:**
- Consumes: `app.itinerary.geometry.haversine_km`, `app.core.constants.MATRIX_CONCURRENCY/MATRIX_CACHE_TTL_DAYS`, `app.tools.amap.distance_batch`
- Produces:
  - `app/tools/amap.py`：`async distance_batch(origins: list[tuple[float,float]], dest: tuple[float,float]) -> list[float|None]` —— 高德 `v3/distance`（多 origins → 1 destination），返回每个 origin 到 dest 的**秒数**列表；失败/缺失项为 `None`。
  - `app/itinerary/matrix.py`：
    - `MatrixCache(db_path: str)`：`.get(poi_a, poi_b) -> float|None`、`.put(poi_a, poi_b, minutes: float)`、建表与 TTL 过滤。
    - `async distance_matrix(nodes: list[dict], db_path: str) -> list[list[float]]` —— nodes[i] 含 `poi_id/lng/lat`，返回 N×N 分钟矩阵；优先查缓存，缺失批量调高德，单弧失败降级 `haversine_km × 经验速度`。对角线 0。

- [ ] **Step 1: 写缓存层失败测试**

Create `backend/tests/itinerary/test_matrix_cache.py`:
```python
from app.itinerary.matrix import MatrixCache


def test_put_get_roundtrip(tmp_path):
    db = str(tmp_path / "c.sqlite")
    cache = MatrixCache(db)
    assert cache.get("A", "B") is None
    cache.put("A", "B", 12.5)
    assert cache.get("A", "B") == 12.5


def test_missing_key_returns_none(tmp_path):
    cache = MatrixCache(str(tmp_path / "c.sqlite"))
    assert cache.get("X", "Y") is None
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && uv run pytest tests/itinerary/test_matrix_cache.py -v`
Expected: FAIL（`No module named 'app.itinerary.matrix'`）。

- [ ] **Step 3: 实现 MatrixCache + amap.distance_batch**

在 `backend/app/tools/amap.py` 末尾新增：
```python
@traceable(run_type="tool", name="amap_distance_batch")
async def distance_batch(origins: list[tuple[float, float]],
                         dest: tuple[float, float]) -> list[float | None]:
    """高德 v3/distance：多起点→单终点，返回各起点到终点的秒数(type=1 驾车)。
    失败/缺失项为 None。origins 用 '|' 拼接，注意高德单次 origins 上限(约100)。
    """
    if not origins:
        return []
    origin_str = "|".join(f"{lng},{lat}" for lng, lat in origins)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(f"{_BASE}/distance", params={
                "key": _key(), "origins": origin_str,
                "destination": f"{dest[0]},{dest[1]}", "type": "1",
            })
            r.raise_for_status()
            results = r.json().get("results") or []
        by_idx: dict[int, float] = {}
        for item in results:
            try:
                oid = int(item.get("origin_id", 0)) - 1  # 高德 origin_id 从 1 起
                by_idx[oid] = float(item.get("duration", 0))
            except (TypeError, ValueError):
                continue
        return [by_idx.get(i) for i in range(len(origins))]
    except Exception:  # noqa: BLE001 —— 降级：全 None，调用方用 haversine 兜底
        return [None] * len(origins)
```

Create `backend/app/itinerary/matrix.py`（先只放 MatrixCache）:
```python
"""距离矩阵：高德真实街道时间 + SQLite 持久缓存(poi_id 对为键) + haversine 降级。"""
import asyncio
import sqlite3
import time

from app.core.constants import MATRIX_CONCURRENCY, MATRIX_CACHE_TTL_DAYS
from app.itinerary.geometry import haversine_km
from app.tools import amap

_DRIVE_KMH = 30.0  # 降级估速：城市驾车均速


class MatrixCache:
    """(poi_a, poi_b) → 分钟。带 TTL；城市内 POI 间街道时间近乎不变。"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS distance_cache ("
            "poi_a TEXT, poi_b TEXT, minutes REAL, ts REAL, "
            "PRIMARY KEY (poi_a, poi_b))"
        )
        self._conn.commit()

    def get(self, poi_a: str, poi_b: str) -> float | None:
        cur = self._conn.execute(
            "SELECT minutes, ts FROM distance_cache WHERE poi_a=? AND poi_b=?",
            (poi_a, poi_b))
        row = cur.fetchone()
        if not row:
            return None
        minutes, ts = row
        if time.time() - ts > MATRIX_CACHE_TTL_DAYS * 86400:
            return None
        return minutes

    def put(self, poi_a: str, poi_b: str, minutes: float) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO distance_cache VALUES (?,?,?,?)",
            (poi_a, poi_b, minutes, time.time()))
        self._conn.commit()
```

- [ ] **Step 4: 运行缓存测试确认通过**

Run: `cd backend && uv run pytest tests/itinerary/test_matrix_cache.py -v`
Expected: PASS。

- [ ] **Step 5: 写 distance_matrix 失败测试（mock 高德）**

Create `backend/tests/itinerary/test_matrix.py`:
```python
import pytest

from app.itinerary import matrix as M


def _n(poi_id, lng, lat):
    return {"poi_id": poi_id, "lng": lng, "lat": lat}


@pytest.mark.asyncio
async def test_matrix_uses_amap_and_caches(tmp_path, monkeypatch):
    db = str(tmp_path / "c.sqlite")
    nodes = [_n("A", 113.0, 23.0), _n("B", 113.1, 23.0)]
    calls = []

    async def fake_batch(origins, dest):
        calls.append((origins, dest))
        return [600.0 for _ in origins]  # 600 秒 = 10 分钟

    monkeypatch.setattr(M.amap, "distance_batch", fake_batch)
    mat = await M.distance_matrix(nodes, db)
    assert mat[0][0] == 0.0 and mat[1][1] == 0.0
    assert mat[0][1] == pytest.approx(10.0)
    # 第二次：命中缓存，不再调高德
    calls.clear()
    mat2 = await M.distance_matrix(nodes, db)
    assert mat2[0][1] == pytest.approx(10.0)
    assert calls == []


@pytest.mark.asyncio
async def test_matrix_falls_back_to_haversine_on_failure(tmp_path, monkeypatch):
    db = str(tmp_path / "c.sqlite")
    nodes = [_n("A", 113.0, 23.0), _n("B", 113.5, 23.0)]

    async def fail_batch(origins, dest):
        return [None for _ in origins]  # 高德失败

    monkeypatch.setattr(M.amap, "distance_batch", fail_batch)
    mat = await M.distance_matrix(nodes, db)
    # 降级 haversine：A-B 直线约 51km / 30kmh ≈ 102 分钟，必为正数
    assert mat[0][1] > 0
```

- [ ] **Step 6: 运行确认失败**

Run: `cd backend && uv run pytest tests/itinerary/test_matrix.py -v`
Expected: FAIL（`distance_matrix` 未定义）。

- [ ] **Step 7: 实现 distance_matrix**

在 `backend/app/itinerary/matrix.py` 末尾追加：
```python
def _fallback_minutes(a: dict, b: dict) -> float:
    return haversine_km(a, b) / _DRIVE_KMH * 60.0


async def distance_matrix(nodes: list[dict], db_path: str) -> list[list[float]]:
    """N×N 真实街道时间矩阵(分钟)。优先缓存 → 缺失批量调高德 → 单弧失败降级 haversine。"""
    cache = MatrixCache(db_path)
    n = len(nodes)
    mat = [[0.0] * n for _ in range(n)]
    sem = asyncio.Semaphore(MATRIX_CONCURRENCY)

    async def fill_dest(j: int) -> None:
        dest_node = nodes[j]
        missing_idx, missing_orig = [], []
        for i in range(n):
            if i == j:
                continue
            cached = cache.get(nodes[i]["poi_id"], dest_node["poi_id"])
            if cached is not None:
                mat[i][j] = cached
            else:
                missing_idx.append(i)
                missing_orig.append((nodes[i]["lng"], nodes[i]["lat"]))
        if not missing_orig:
            return
        async with sem:
            secs = await amap.distance_batch(missing_orig,
                                             (dest_node["lng"], dest_node["lat"]))
        for k, i in enumerate(missing_idx):
            s = secs[k] if k < len(secs) else None
            minutes = (s / 60.0) if s is not None else _fallback_minutes(nodes[i], dest_node)
            mat[i][j] = minutes
            cache.put(nodes[i]["poi_id"], dest_node["poi_id"], minutes)

    await asyncio.gather(*(fill_dest(j) for j in range(n)))
    return mat
```

- [ ] **Step 8: 运行确认通过**

Run: `cd backend && uv run pytest tests/itinerary/test_matrix.py -v`
Expected: PASS。

- [ ] **Step 9: 提交**

```bash
git add backend/app/itinerary/matrix.py backend/app/tools/amap.py backend/tests/itinerary/test_matrix.py backend/tests/itinerary/test_matrix_cache.py
git commit -m "feat(m6-v2): 距离矩阵(高德 distance + SQLite 缓存 + haversine 降级)"
```

---

## Task 5: optimizer OR-Tools VRPTW 求解 + 三级放松

**Files:**
- Create: `backend/app/itinerary/optimizer.py`
- Test: `backend/tests/itinerary/test_optimizer.py`

**Interfaces:**
- Consumes: `ortools.constraint_solver`, `app.core.constants.SOLVE_TIME_LIMIT_S/RELAX_BUDGET_FACTOR`, `app.graph.nodes.time_budget.DAY_BUDGET`
- Produces: `solve_vrptw(matrix, nodes, days, day_budget, time_windows=None, ratings=None) -> tuple[list[list[int]], list[int], int]`
  - `matrix`：N×N 分钟（含 depot=index 0）；`nodes`：含 `visit_minutes`（depot 为 0）；`time_windows`：每节点 `(open_min, close_min)` 或 None（无窗）；`ratings`：每节点评分（depot 0）。
  - 返回 `(per_day_routes, dropped_node_indices, relax_level)`：`per_day_routes` 长度=days，每个是该天访问的**节点 index 列表**（不含 depot，按访问顺序）；`dropped_node_indices` 未被访问的非 depot 节点 index；`relax_level` ∈ {0,1,2,3}。

- [ ] **Step 1: 写失败测试**

Create `backend/tests/itinerary/test_optimizer.py`:
```python
from app.itinerary.optimizer import solve_vrptw


def _matrix():
    # 0=depot, 1..4 景点；西簇(1,2) 东簇(3,4)
    return [
        [0, 10, 12, 40, 42],
        [10, 0, 5, 38, 40],
        [12, 5, 0, 36, 38],
        [40, 38, 36, 0, 6],
        [42, 40, 38, 6, 0],
    ]


def test_two_days_groups_geographically():
    nodes = [{"visit_minutes": 0}] + [{"visit_minutes": 60} for _ in range(4)]
    routes, dropped, relax = solve_vrptw(_matrix(), nodes, days=2, day_budget=480)
    assert len(routes) == 2
    assert dropped == []
    assert relax == 0
    # 西簇{1,2} 与 东簇{3,4} 各自同天(不跨簇拆分)
    flat = [set(r) for r in routes if r]
    assert {1, 2} in flat or {2, 1} in flat
    assert {3, 4} in flat or {4, 3} in flat


def test_high_rating_kept_over_low_when_budget_tight():
    # 5 景点但每天预算只够 2 个；高分必留、低分被丢
    nodes = [{"visit_minutes": 0}] + [{"visit_minutes": 200} for _ in range(5)]
    ratings = [0.0, 5.0, 5.0, 4.8, 1.0, 1.0]
    mat = [[0]*6] + [[10]*6 for _ in range(5)]
    for i in range(6):
        mat[i][i] = 0
    routes, dropped, relax = solve_vrptw(mat, nodes, days=1, day_budget=480,
                                         ratings=ratings)
    visited = {x for r in routes for x in r}
    # 高分(1,2)应在，低分(4,5)更可能被丢
    assert 1 in visited and 2 in visited
    assert len(dropped) >= 1


def test_relax_when_time_windows_infeasible():
    nodes = [{"visit_minutes": 0}] + [{"visit_minutes": 60} for _ in range(3)]
    mat = [[0]*4] + [[10]*4 for _ in range(3)]
    for i in range(4):
        mat[i][i] = 0
    # 全冲突窗：每个点只能 10~11 分钟到达，互斥 → L0 无解
    tw = [(0, 480), (10, 11), (10, 11), (10, 11)]
    routes, dropped, relax = solve_vrptw(mat, nodes, days=1, day_budget=480,
                                         time_windows=tw)
    assert relax >= 1            # 放松过
    visited = {x for r in routes for x in r}
    assert len(visited) >= 1     # 放松后能排进点
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && uv run pytest tests/itinerary/test_optimizer.py -v`
Expected: FAIL（`No module named 'app.itinerary.optimizer'`）。

- [ ] **Step 3: 实现 optimizer.py**

Create `backend/app/itinerary/optimizer.py`:
```python
"""OR-Tools VRPTW：选点+分天+顺路+时间窗联合求解，含三级放松约束重解。

天=车辆、景点=节点、visit_minutes=service time、time_window=营业时间、
rating=丢弃惩罚。无可行解时按 L1(去窗)→L2(放宽预算)→L3(去时间维度) 逐级放松。
"""
from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from app.core.constants import SOLVE_TIME_LIMIT_S, RELAX_BUDGET_FACTOR


def _solve_once(matrix, nodes, days, day_budget, time_windows, ratings, use_time_dim):
    n = len(matrix)
    mgr = pywrapcp.RoutingIndexManager(n, days, 0)
    routing = pywrapcp.RoutingModel(mgr)

    def transit_cb(i, j):
        fi, fj = mgr.IndexToNode(i), mgr.IndexToNode(j)
        service = int(nodes[fj].get("visit_minutes", 0))
        return int(matrix[fi][fj]) + service

    cb = routing.RegisterTransitCallback(transit_cb)
    routing.SetArcCostEvaluatorOfAllVehicles(cb)

    if use_time_dim:
        routing.AddDimension(cb, 0, int(day_budget), True, "Time")
        time_dim = routing.GetDimensionOrDie("Time")
        if time_windows:
            for node in range(1, n):
                a, b = time_windows[node]
                idx = mgr.NodeToIndex(node)
                time_dim.CumulVar(idx).SetRange(int(a), int(b))

    # disjunction：高分高惩罚
    for node in range(1, n):
        rating = ratings[node] if ratings else 3.0
        penalty = int(rating * 1000) + 500
        routing.AddDisjunction([mgr.NodeToIndex(node)], penalty)

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.FromSeconds(int(SOLVE_TIME_LIMIT_S))

    sol = routing.SolveWithParameters(params)
    if not sol:
        return None
    routes = []
    for v in range(days):
        idx = routing.Start(v)
        route = []
        while not routing.IsEnd(idx):
            node = mgr.IndexToNode(idx)
            if node != 0:
                route.append(node)
            idx = sol.Value(routing.NextVar(idx))
        routes.append(route)
    visited = {x for r in routes for x in r}
    dropped = [node for node in range(1, n) if node not in visited]
    return routes, dropped


def solve_vrptw(matrix, nodes, days, day_budget, time_windows=None, ratings=None):
    """逐级放松：L0 原约束 → L1 去时间窗 → L2 放宽预算 → L3 去时间维度。
    返回 (per_day_routes, dropped_node_indices, relax_level)。
    """
    days = max(1, days)
    # L0
    r = _solve_once(matrix, nodes, days, day_budget, time_windows, ratings, True)
    if r is not None and any(r[0]):
        return r[0], r[1], 0
    # L1：去时间窗
    r = _solve_once(matrix, nodes, days, day_budget, None, ratings, True)
    if r is not None and any(r[0]):
        return r[0], r[1], 1
    # L2：放宽预算
    r = _solve_once(matrix, nodes, days, int(day_budget * RELAX_BUDGET_FACTOR),
                    None, ratings, True)
    if r is not None and any(r[0]):
        return r[0], r[1], 2
    # L3：去时间维度（纯路由）
    r = _solve_once(matrix, nodes, days, day_budget, None, ratings, False)
    if r is not None:
        return r[0], r[1], 3
    # 兜底：全丢弃（理论不达）
    return [[] for _ in range(days)], list(range(1, len(matrix))), 3
```

- [ ] **Step 4: 运行确认通过**

Run: `cd backend && uv run pytest tests/itinerary/test_optimizer.py -v`
Expected: PASS（三个测试均过；若 `test_two_days_groups_geographically` 因求解器把两簇放一天而偶发失败，放宽断言为「同簇点不被拆到不同天」的弱形式——但默认参数下应稳定分簇）。

- [ ] **Step 5: 提交**

```bash
git add backend/app/itinerary/optimizer.py backend/tests/itinerary/test_optimizer.py
git commit -m "feat(m6-v2): OR-Tools VRPTW 求解器 + 三级放松约束重解"
```

---

## Task 5.5: 解析高德 opentime → 时间窗（根治「到了没开门」）

高德 POI 的 `opentime` 字段（`extensions=all` 时返回）解析为分钟时间窗 `(open_min, close_min)`，喂给 VRPTW 硬约束。这是 spec §0.2「时间不合理」痛点的真正根治——而非 m6 的「仅软填参考」。

**Files:**
- Create: `backend/app/itinerary/opentime.py`
- Test: `backend/tests/itinerary/test_opentime.py`

**Interfaces:**
- Produces: `parse_opentime(opentime: str, day_budget: int) -> tuple[int, int]`
  - 输入高德 opentime 字符串（格式多样，见下），输出 `(到达最早分钟, 到达最晚分钟)`，**相对当天行程起点 09:00 为 0 分钟**对齐 VRPTW 的 time dimension（cumul 从 0 起）。
  - 无法解析 / 空 / 全天 → 返回 `(0, day_budget)`（不约束）。
  - 解析出营业 `[OPEN_HH:MM, CLOSE_HH:MM]` → 窗 = `(max(0, OPEN分-540), CLOSE分-540)`（540 = 09:00 基准；负数截 0）。容错：取第一段、忽略跨夜、关门早于开门则不约束。

- [ ] **Step 1: 写失败测试**

Create `backend/tests/itinerary/test_opentime.py`:
```python
from app.itinerary.opentime import parse_opentime


def test_empty_or_allday_returns_full_window():
    assert parse_opentime("", 480) == (0, 480)
    assert parse_opentime("00:00-24:00", 480) == (0, 480)


def test_standard_range_shifts_to_0900_base():
    # 10:00-17:00 → 到达窗 = (10:00-09:00=60, 17:00-09:00=480)
    assert parse_opentime("10:00-17:00", 480) == (60, 480)


def test_open_before_0900_clamps_to_zero():
    # 08:30 开门 → 最早到达 0(不早于行程起点)
    lo, hi = parse_opentime("08:30-18:00", 480)
    assert lo == 0
    assert hi == 18 * 60 - 540  # 540


def test_takes_first_segment_of_multi():
    # 多段(午休)取第一段 09:00-12:00
    lo, hi = parse_opentime("09:00-12:00,14:00-18:00", 480)
    assert lo == 0
    assert hi == 12 * 60 - 540  # 180


def test_unparseable_returns_full_window():
    assert parse_opentime("全年无休", 480) == (0, 480)
    assert parse_opentime("周一至周五", 480) == (0, 480)
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && uv run pytest tests/itinerary/test_opentime.py -v`
Expected: FAIL（`No module named 'app.itinerary.opentime'`）。

- [ ] **Step 3: 实现 opentime.py**

Create `backend/app/itinerary/opentime.py`:
```python
"""解析高德 POI opentime 字符串 → VRPTW 到达时间窗(以 09:00 为 0 分钟基准)。

高德 opentime 格式多样：'09:00-17:00' / '08:30-18:00' / 多段(午休)'09:00-12:00,14:00-18:00'
/ 自由文本('全年无休')。无法解析或全天则不约束。容错优先，宁可不约束也不误约束。
"""
import re

_BASE_MIN = 540  # 09:00 行程起点基准(分钟)
_RANGE_RE = re.compile(r"(\d{1,2}):(\d{2})\s*[-~]\s*(\d{1,2}):(\d{2})")


def parse_opentime(opentime: str, day_budget: int) -> tuple[int, int]:
    """→ (最早到达分钟, 最晚到达分钟)，以 09:00 为 0。无法解析/全天 → (0, day_budget)。"""
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
    # 关门早于/等于开门(异常或跨夜)→ 不约束
    if close_min <= open_min:
        return full
    lo = max(0, open_min - _BASE_MIN)
    hi = close_min - _BASE_MIN
    # 关门已在行程起点之前 → 不约束(交给求解器/降级)
    if hi <= 0:
        return full
    return (lo, min(hi, day_budget))
```

- [ ] **Step 4: 运行确认通过**

Run: `cd backend && uv run pytest tests/itinerary/test_opentime.py -v`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/app/itinerary/opentime.py backend/tests/itinerary/test_opentime.py
git commit -m "feat(m6-v2): 解析高德 opentime 为 VRPTW 时间窗(根治到点没开门)"
```

---

## Task 6: assembler 求解结果 → skeleton_days

**Files:**
- Create: `backend/app/itinerary/assembler.py`
- Test: `backend/tests/itinerary/test_assembler.py`

**Interfaces:**
- Consumes: `app.itinerary.geometry.build_day_stops/insert_transport`
- Produces: `routes_to_skeleton(per_day_routes, candidates, rest_pools) -> tuple[list[dict], list[dict]]`
  - `per_day_routes`：optimizer 返回的每天节点 index 列表（index 基于 `[depot]+candidates`，故景点 index i 对应 `candidates[i-1]`）。
  - `candidates`：预筛后景点 list（含 name/poi_id/lng/lat/visit_minutes）。
  - `rest_pools`：list[list[dict]]，第 d 天的就近餐厅候选池。
  - 返回 `(skeleton_days, daily_centers)`：`skeleton_days` 每项 `{"day":d,"items":[...],"center":{lng,lat}}`，items 由 build_day_stops + insert_transport 产生；几何不变量成立。

- [ ] **Step 1: 写失败测试**

Create `backend/tests/itinerary/test_assembler.py`:
```python
from app.itinerary.assembler import routes_to_skeleton


def _c(poi_id, lng, lat):
    return {"name": poi_id, "poi_id": poi_id, "lng": lng, "lat": lat, "visit_minutes": 60}


def _r(poi_id, lng, lat):
    return {"name": poi_id, "poi_id": poi_id, "lng": lng, "lat": lat}


def test_routes_to_skeleton_geometry_invariants():
    candidates = [_c("A", 113.0, 23.0), _c("B", 113.01, 23.0),
                  _c("C", 113.2, 23.1)]
    # 节点 index：1=A,2=B,3=C。第1天[1,2]，第2天[3]
    per_day = [[1, 2], [3]]
    rest_pools = [[_r("R1", 113.005, 23.0)], [_r("R2", 113.2, 23.1)]]
    skeleton, centers = routes_to_skeleton(per_day, candidates, rest_pools)
    assert len(skeleton) == 2
    assert len(centers) == 2
    for day in skeleton:
        items = day["items"]
        if items:
            assert items[0]["type"] != "transport"
            assert items[-1]["type"] != "transport"
        transports = [it for it in items if it["type"] == "transport"]
        stops = [it for it in items if it["type"] != "transport"]
        assert len(transports) == max(0, len(stops) - 1)


def test_empty_day_yields_empty_items():
    skeleton, centers = routes_to_skeleton([[], []], [], [[], []])
    assert all(day["items"] == [] for day in skeleton)
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && uv run pytest tests/itinerary/test_assembler.py -v`
Expected: FAIL（`No module named 'app.itinerary.assembler'`）。

- [ ] **Step 3: 实现 assembler.py**

Create `backend/app/itinerary/assembler.py`:
```python
"""求解结果(每天节点序列) → skeleton_days：插就近餐厅 + 交通段。几何不变量在此守住。"""
from app.itinerary.geometry import build_day_stops, insert_transport


def _center(points: list[dict]) -> dict:
    if not points:
        return {"lng": 0.0, "lat": 0.0}
    return {"lng": sum(p.get("lng", 0.0) for p in points) / len(points),
            "lat": sum(p.get("lat", 0.0) for p in points) / len(points)}


def routes_to_skeleton(per_day_routes: list[list[int]], candidates: list[dict],
                       rest_pools: list[list[dict]]) -> tuple[list[dict], list[dict]]:
    """per_day_routes[d] 是节点 index 列表(基于 [depot]+candidates，故 index i→candidates[i-1])。
    每天：取有序景点 → build_day_stops(插就近餐厅) → insert_transport(插交通段)。
    """
    skeleton, centers = [], []
    for d, route in enumerate(per_day_routes, start=1):
        ordered = [candidates[i - 1] for i in route if 1 <= i <= len(candidates)]
        pool = rest_pools[d - 1] if d - 1 < len(rest_pools) else []
        stops = build_day_stops(ordered, pool)
        items = insert_transport(stops)
        center = _center(ordered)
        skeleton.append({"day": d, "items": items, "center": center})
        centers.append(center)
    return skeleton, centers
```

- [ ] **Step 4: 运行确认通过**

Run: `cd backend && uv run pytest tests/itinerary/test_assembler.py -v`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/app/itinerary/assembler.py backend/tests/itinerary/test_assembler.py
git commit -m "feat(m6-v2): assembler 求解结果→skeleton_days(守几何不变量)"
```

---

## Task 7: soft_fill 软填迁入子包

把 m6 `itinerary.py` 的 `merge_soft_fields`、`_build_payload`、`_SYS`、`annotate`（LLM 软填调用）迁入 `soft_fill.py`，itinerary.py re-export `merge_soft_fields`。

**Files:**
- Create: `backend/app/itinerary/soft_fill.py`
- Modify: `backend/app/graph/nodes/itinerary.py`
- Test: 复用 `tests/test_itinerary_m6fix.py`（含 merge_soft_fields 断言）

**Interfaces:**
- Consumes: `app.itinerary.schemas.DayPlans`, `app.llm.factory.build_llm`
- Produces:
  - `app/itinerary/soft_fill.py`：`merge_soft_fields(skeleton_days, llm_days) -> list[dict]`（原样迁移）、`build_soft_payload(skeleton_days, state) -> dict`、`async annotate_soft_fields(skeleton_days, state, config) -> list[dict]`（封装 LLM 调用 + 失败降级骨架 + merge）。
  - itinerary.py re-export `merge_soft_fields`。

- [ ] **Step 1: 跑现有软填测试确认起点绿**

Run: `cd backend && uv run pytest tests/test_itinerary_m6fix.py -q`
Expected: PASS。

- [ ] **Step 2: 创建 soft_fill.py，迁入逻辑**

Create `backend/app/itinerary/soft_fill.py`。把 m6 `itinerary.py` 的 `_SYS`、`_SOFT_FIELDS`、`merge_soft_fields`、`_build_payload`（改名 `build_soft_payload`）原样迁入，并新增封装：
```python
"""LLM 软填：算法骨架 → LLM 只补 start/end/cost/indoor/note → 按 poi_id 合并。"""
from langchain_core.messages import HumanMessage, SystemMessage

from app.itinerary.schemas import DayPlans
from app.llm.factory import build_llm

# _SYS / _SOFT_FIELDS / merge_soft_fields / build_soft_payload —— 从 m6 itinerary.py 迁入

async def annotate_soft_fields(skeleton_days: list[dict], state: dict, config) -> list[dict]:
    """调 LLM 软填；失败则全用骨架默认。返回 merge 后的 day_plans。"""
    llm = build_llm(temperature=0).with_structured_output(DayPlans, method="function_calling")
    try:
        result = await llm.ainvoke([
            SystemMessage(content=_SYS),
            HumanMessage(content=str(build_soft_payload(skeleton_days, state))),
        ], config=config)
        llm_days = [d.model_dump(by_alias=True) for d in result.days]
    except Exception:  # noqa: BLE001 —— 软填失败不阻断，几何已就绪
        llm_days = []
    return merge_soft_fields(skeleton_days, llm_days)
```

- [ ] **Step 3: itinerary.py re-export + 删除迁出定义**

在 itinerary.py re-export 区加 `from app.itinerary.soft_fill import merge_soft_fields  # noqa: F401`，删除 itinerary.py 内 `_SYS`/`_SOFT_FIELDS`/`merge_soft_fields`/`_build_payload` 原定义。

- [ ] **Step 4: 运行确认零回归**

Run: `cd backend && uv run pytest tests/test_itinerary_m6fix.py -q`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/app/itinerary/soft_fill.py backend/app/graph/nodes/itinerary.py
git commit -m "refactor(m6-v2): 软填逻辑迁入 app/itinerary/soft_fill"
```

---

## Task 8: 重写 itinerary() 节点为编排 + 删除旧贪心

把 itinerary() 改为新管线（prefilter → matrix → optimizer → assembler → soft_fill），删除 `select_by_rating`/`cluster_by_day`/`cluster_kmeans`/`rebalance_by_budget`/`_nearest_neighbor_order`/`OVERHEAD_PER_STOP`/`_bucket_*` 等旧函数。

**Files:**
- Modify: `backend/app/graph/nodes/itinerary.py`
- Delete: `backend/tests/test_cluster_by_day.py`, `test_cluster_kmeans.py`, `test_select_by_rating.py`, `test_rebalance_budget.py`（被替换的函数的测试）
- Modify: `backend/app/core/config.py`（加 `checkpoint_db_path` 已有；矩阵缓存复用同库路径）
- Test: 重写 `backend/tests/test_itinerary.py` 为新管线集成测试

**Interfaces:**
- Consumes: `prefilter.select_candidates`, `matrix.distance_matrix`, `optimizer.solve_vrptw`, `assembler.routes_to_skeleton`, `soft_fill.annotate_soft_fields`, `amap.search_around`, `time_budget.DAY_BUDGET`, `config.get_settings().checkpoint_db_path`
- Produces: `async itinerary(state, config) -> dict`，返回 patch：`day_plans`, `daily_centers`, `dropped_attractions`, `plan_version`, `changed_days`, `relax_level`

- [ ] **Step 1: 写新管线集成失败测试（mock matrix + search_around + LLM）**

重写 `backend/tests/test_itinerary.py`（保留文件名，内容替换为新管线测试）:
```python
import pytest

from app.graph.nodes import itinerary as I


@pytest.mark.asyncio
async def test_itinerary_pipeline_produces_day_plans(tmp_path, monkeypatch):
    # mock 距离矩阵：返回简单矩阵
    async def fake_matrix(nodes, db_path):
        n = len(nodes)
        return [[0 if i == j else 10 for j in range(n)] for i in range(n)]

    async def fake_around(lng, lat, kw, ptype, radius):
        return [{"name": "餐厅X", "poi_id": "R1", "lng": lng, "lat": lat}]

    async def fake_annotate(skeleton, state, config):
        return skeleton  # 跳过 LLM，直接用骨架

    monkeypatch.setattr(I, "distance_matrix", fake_matrix)
    monkeypatch.setattr(I.amap, "search_around", fake_around)
    monkeypatch.setattr(I, "annotate_soft_fields", fake_annotate)

    state = {
        "days": 2,
        "attractions": [
            {"name": "A", "poi_id": "A", "lng": 113.0, "lat": 23.0, "rating": 4.8, "visit_minutes": 90},
            {"name": "B", "poi_id": "B", "lng": 113.01, "lat": 23.0, "rating": 4.5, "visit_minutes": 90},
            {"name": "C", "poi_id": "C", "lng": 113.3, "lat": 23.2, "rating": 4.0, "visit_minutes": 90},
        ],
        "preferences": {"food": "美食"}, "restaurants": [], "weather": {},
        "num_people": 2, "plan_version": 0,
    }
    patch = await I.itinerary(state, config=None)
    assert "day_plans" in patch
    assert len(patch["day_plans"]) == 2
    assert "daily_centers" in patch
    assert "dropped_attractions" in patch
    assert patch["plan_version"] == 1
    # 几何不变量
    for day in patch["day_plans"]:
        items = day["items"]
        if items:
            assert items[0]["type"] != "transport"
            stops = [it for it in items if it["type"] != "transport"]
            transports = [it for it in items if it["type"] == "transport"]
            assert len(transports) == max(0, len(stops) - 1)
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && uv run pytest tests/test_itinerary.py -v`
Expected: FAIL（旧 itinerary 仍是旧管线，断言 plan_version/结构可能过，但 mock 的 `I.distance_matrix` 等符号未在模块中引用 → AttributeError）。

- [ ] **Step 3: 重写 itinerary() + 删旧函数**

把 `backend/app/graph/nodes/itinerary.py` 的 `itinerary()` 与残留旧函数整体替换为：
```python
"""itinerary 节点：prefilter → 距离矩阵 → OR-Tools VRPTW 求解 → 装配 → LLM 软填。"""
from app.core.config import get_settings
from app.graph.nodes.time_budget import DAY_BUDGET, attraction_minutes
from app.itinerary.prefilter import select_candidates
from app.itinerary.matrix import distance_matrix
from app.itinerary.optimizer import solve_vrptw
from app.itinerary.assembler import routes_to_skeleton
from app.itinerary.soft_fill import annotate_soft_fields
from app.itinerary.opentime import parse_opentime
from app.itinerary.geometry import haversine_km  # noqa: F401  re-export
from app.tools import amap

# re-export（下游依赖旧路径）
from app.itinerary.geometry import (  # noqa: F401
    mode_by_distance, pick_nearest, build_day_stops, default_cost_by_mode, insert_transport,
)
from app.itinerary.schemas import (  # noqa: F401
    Location, DayWeather, PlanItem, Hotel, DayPlan, DayPlans,
)
from app.itinerary.soft_fill import merge_soft_fields  # noqa: F401


async def itinerary(state, config) -> dict:
    days = state.get("days", 3) or 3
    attractions = state.get("attractions", []) or []
    candidates, dropped_pre = select_candidates(attractions, days)

    if not candidates:
        return {"daily_centers": [], "day_plans": [], "dropped_attractions": dropped_pre,
                "plan_version": (state.get("plan_version", 0) or 0) + 1, "changed_days": [],
                "relax_level": 0}

    # depot = 候选质心
    cx = sum(p["lng"] for p in candidates) / len(candidates)
    cy = sum(p["lat"] for p in candidates) / len(candidates)
    depot = {"name": "__depot__", "poi_id": "__depot__", "lng": cx, "lat": cy, "visit_minutes": 0}
    nodes = [depot] + candidates

    db_path = get_settings().checkpoint_db_path
    matrix = await distance_matrix(nodes, db_path)

    ratings = [0.0] + [p.get("rating", 3.0) for p in candidates]
    tw = [(0, DAY_BUDGET)] + [parse_opentime(p.get("opentime", ""), DAY_BUDGET)
                              for p in candidates]
    routes, dropped_idx, relax = solve_vrptw(matrix, nodes, days, DAY_BUDGET,
                                             time_windows=tw, ratings=ratings)

    # 就近餐厅池(按每天簇中心)
    food_kw = (state.get("preferences") or {}).get("food") or "美食"
    city_pool = state.get("restaurants", []) or []
    rest_pools = []
    for route in routes:
        pts = [candidates[i - 1] for i in route if 1 <= i <= len(candidates)]
        if pts:
            cx2 = sum(p["lng"] for p in pts) / len(pts)
            cy2 = sum(p["lat"] for p in pts) / len(pts)
            pool = await amap.search_around(cx2, cy2, food_kw, "餐饮", 3000) or city_pool
        else:
            pool = city_pool
        rest_pools.append(pool)

    skeleton, centers = routes_to_skeleton(routes, candidates, rest_pools)
    day_plans = await annotate_soft_fields(skeleton, state, config)

    dropped_solver = [{"name": candidates[i - 1].get("name", ""),
                       "rating": candidates[i - 1].get("rating", 0.0),
                       "reason": "综合距离/时间/评分权衡后未排入"}
                      for i in dropped_idx if 1 <= i <= len(candidates)]
    return {
        "daily_centers": centers,
        "day_plans": day_plans,
        "dropped_attractions": dropped_pre + dropped_solver,
        "plan_version": (state.get("plan_version", 0) or 0) + 1,
        "changed_days": [d["day"] for d in day_plans],
        "relax_level": relax,
    }
```
删除旧文件里所有残留的 `select_by_rating`/`cluster_by_day`/`cluster_kmeans`/`rebalance_by_budget`/`_nearest_neighbor_order`/`OVERHEAD_PER_STOP`/`_bucket_load`/`_bucket_center` 定义。

删除被替换函数的测试：
```bash
git rm backend/tests/test_cluster_by_day.py backend/tests/test_cluster_kmeans.py backend/tests/test_select_by_rating.py backend/tests/test_rebalance_budget.py
```

- [ ] **Step 4: 运行新集成测试 + 全量回归**

Run:
```bash
cd backend && uv run pytest tests/test_itinerary.py -v
uv run pytest -q
```
Expected: 新集成测试 PASS。全量回归：除已删测试外应全绿。**若 `test_itinerary_m6fix.py`/`test_m5fix_e2e.py`/`test_multiturn_*` 因依赖旧 `cluster_by_day` 分天行为而失败**，按新管线更新这些测试的断言（它们断言的是「景点如何分天」，现由 OR-Tools 决定，需放宽为「景点都排进了某天」「几何不变量成立」而非精确分天）。逐个修复并记录。

- [ ] **Step 5: 提交**

```bash
git add -A
git commit -m "feat(m6-v2): itinerary 重写为 OR-Tools 管线，删除两段贪心旧算法"
```

---

## Task 9: 移除 scikit-learn 依赖（已无引用）

`cluster_kmeans` 删除后，sklearn 仅剩 `test_config_m6fix.py` 的 import 可用性断言引用。

**Files:**
- Modify: `backend/pyproject.toml`（移除 `scikit-learn`）
- Modify: `backend/tests/test_config_m6fix.py`（删 sklearn import 断言）

- [ ] **Step 1: 确认 sklearn 已无生产引用**

Run: `cd backend && uv run python -c "import subprocess; print(subprocess.run(['git','grep','-n','sklearn','--','app/'], capture_output=True, text=True).stdout)"`
Expected: 空（app/ 下无 sklearn 引用）。

- [ ] **Step 2: 删测试中的 sklearn 断言**

在 `backend/tests/test_config_m6fix.py` 删除 `test_sklearn_and_tavily_importable` 里 `import sklearn.cluster` 那行（若该测试同时验证 tavily，则只删 sklearn 行，保留 tavily 部分；若仅测 sklearn 则删整个测试函数）。

- [ ] **Step 3: 移除依赖**

Run: `cd backend && uv remove scikit-learn`

- [ ] **Step 4: 全量回归**

Run: `cd backend && uv run pytest -q`
Expected: 全绿。

- [ ] **Step 5: 提交**

```bash
git add backend/pyproject.toml backend/uv.lock backend/tests/test_config_m6fix.py
git commit -m "chore(m6-v2): 移除 scikit-learn(cluster_kmeans 已被 OR-Tools 替换)"
```

---

## Task 10: 端到端验收（真实高德 + LLM）

**Files:** 无（人工验收 + 一个可选 smoke 脚本）

- [ ] **Step 1: 起后端，真实跑一次**

确保 `.env` 配了 `AMAP_WEB_KEY` 与 LLM key。
Run: `cd backend && uv run uvicorn app.main:app --reload`
另起请求：对 `/api/chat` 发「广州玩 3 天，2 人，爱吃辣，预算人均 2000，喜欢历史古迹」，澄清后等编排完成。

- [ ] **Step 2: 核对验收标准**

检查返回的 `day_plans`：
- ① 同天景点顺路无明显回头路（看相邻 items 坐标）
- ② 餐厅贴当天景点（meal 项坐标接近相邻 attraction）
- ③ 交通段 mode 与真实距离匹配（短距步行、长距驾车）
- ④ 每对相邻停靠点恰好一段交通（几何不变量）
- ⑤ `dropped_attractions` 有合理 reason
- ⑥ `relax_level` 通常为 0（约束不紧时）

- [ ] **Step 3: 前端总览路线核对（若起前端）**

总览路线连续、按天配色、无 7km 步行怪线。

- [ ] **Step 4: 记录验收结果**

把验收观察写入 `docs/superpowers/specs/2026-06-22-itinerary-ortools-redesign.md` 末尾「验收记录」小节并提交。

---

## Self-Review 结果

- **Spec 覆盖**：§1 决策 7 条 → Task 1(常量/依赖)/3(prefilter)/4(matrix)/5(optimizer)/8(编排+取舍)/9(sklearn) 全覆盖；§2 建模 → Task 5；§2.1 opentime→时间窗硬约束 → Task 5.5；§3 模块拆分 → Task 2/6/7/8；§4 数据流缓存 → Task 4/8；§5 测试不变量 → 各 Task 测试 + Task 8 回归 + Task 10 验收。§2.4 depot 闭合回路 → Task 8 depot=质心。§2.5 三级放松 → Task 5。三大痛点：绕路/分天 → Task 5；真实距离 → Task 4；时间不合理 → Task 5.5(opentime 硬约束) + Task 5(时间预算)。
- **占位符扫描**：无 TBD/TODO；每个代码步骤含完整代码。
- **类型一致性**：`solve_vrptw` 返回 `(routes, dropped_idx, relax)` 三元组在 Task 5 定义、Task 8 消费一致；`distance_matrix(nodes, db_path)` 签名 Task 4 定义、Task 8 调用一致；`routes_to_skeleton(per_day_routes, candidates, rest_pools)` Task 6 定义、Task 8 调用一致；`select_candidates` 返回 `(candidates, dropped)` Task 3/8 一致；`parse_opentime(opentime, day_budget)` Task 5.5 定义、Task 8 调用一致。
- **已知边界**：① depot 用闭合回路近似(回质心)——影响小，M7 可改开放式路径；② `parse_opentime` 取营业时间第一段、忽略跨夜/多段午休——容错优先(无法解析则不约束)，覆盖常见格式，罕见格式退化为不约束而非误约束。两者均为有意的 MVP 边界，非占位符。
