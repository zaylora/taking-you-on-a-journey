# Deterministic Itinerary Fill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `assemble_itinerary` produce complete, usable `day_plans` deterministically, with LLM limited to optional safe text enrichment.

**Architecture:** Keep OR-Tools as the source of truth for attraction grouping and order. Add a pure deterministic fill module that inserts meals, transport, times, weather, centers, and basic costs without calling an LLM. Change the existing LLM soft-fill into an optional note-enhancement path that cannot alter POIs, coordinates, ordering, or required structure.

**Tech Stack:** Python 3.12, LangChain tools, Pydantic schemas in `backend/app/agent/itinerary/schemas.py`, pytest + pytest-asyncio, existing OR-Tools routing pipeline.

## Global Constraints

- Do not add new dependencies.
- Keep `assemble_itinerary` tool input/output shape compatible: return at least `{"day_plans": list, "daily_centers": list}`.
- Do not let LLM modify attraction order, attraction coordinates, attraction POI ids, day assignment, or weather facts.
- If LLM fails, times out, or returns invalid data, deterministic output must still be returned.
- Use TDD: each task starts with a failing test and verifies red-green.
- Keep changes scoped to itinerary assembly and tests.

---

## File Structure

- Create `backend/app/agent/itinerary/fill.py`
  - Owns deterministic fill logic.
  - Pure functions only; no LLM, no network, no settings.
  - Produces complete `DayPlan`-shaped dictionaries from skeleton, restaurants, weather, centers, and start date.

- Modify `backend/app/agent/tools/itinerary.py`
  - Calls deterministic fill immediately after OR-Tools skeleton generation.
  - Uses LLM only for optional note enrichment.
  - Keeps timeout/fallback behavior.

- Modify `backend/tests/agent/test_tools.py`
  - Covers tool-level behavior and LLM failure behavior.

- Create `backend/tests/agent/test_itinerary_fill.py`
  - Covers deterministic fill pure functions.

---

### Task 1: Add Deterministic Fill Module

**Files:**
- Create: `backend/app/agent/itinerary/fill.py`
- Create: `backend/tests/agent/test_itinerary_fill.py`

**Interfaces:**
- Consumes: `skeleton: list[dict]`, `restaurants: list[dict]`, `weather: dict`, `daily_centers: list[dict]`, `start_date: str`, `num_people: int`
- Produces: `fill_day_plans(...) -> list[dict]`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/agent/test_itinerary_fill.py`:

```python
# -*- coding: utf-8 -*-
from app.agent.itinerary.fill import fill_day_plans


def test_fill_day_plans_adds_weather_center_times_and_meals():
    skeleton = [{
        "day": 1,
        "items": [
            {
                "type": "attraction",
                "name": "祖庙",
                "poi_id": "p1",
                "location": {"lng": 113.11351, "lat": 23.028945},
                "start": "",
                "end": "",
                "indoor": False,
                "note": "",
                "cost": 0.0,
            },
            {
                "type": "attraction",
                "name": "岭南天地",
                "poi_id": "p2",
                "location": {"lng": 113.11519, "lat": 23.028895},
                "start": "",
                "end": "",
                "indoor": False,
                "note": "",
                "cost": 0.0,
            },
        ],
    }]
    restaurants = [
        {"name": "民信老铺", "poi_id": "r1", "lng": 113.114509, "lat": 23.031653, "type": "餐饮服务;甜品店"},
        {"name": "大良毋米粥", "poi_id": "r2", "lng": 113.2, "lat": 23.2, "type": "餐饮服务;中餐厅"},
    ]
    weather = {"text": "雷阵雨", "temp": "26~32℃", "is_rainy": True}
    centers = [{"lng": 113.11435, "lat": 23.02892}]

    out = fill_day_plans(
        skeleton=skeleton,
        restaurants=restaurants,
        weather=weather,
        daily_centers=centers,
        start_date="2026-07-01",
        num_people=1,
    )

    assert out[0]["date"] == "2026-07-01"
    assert out[0]["weather"] == weather
    assert out[0]["center"] == centers[0]
    assert [item["name"] for item in out[0]["items"] if item["type"] == "attraction"] == ["祖庙", "岭南天地"]
    assert any(item["type"] == "meal" and item["name"] == "民信老铺" for item in out[0]["items"])
    assert out[0]["items"][0]["start"] == "09:30"
    assert all(item["start"] <= item["end"] for item in out[0]["items"] if item["start"] and item["end"])


def test_fill_day_plans_does_not_invent_restaurants_when_candidates_empty():
    skeleton = [{
        "day": 1,
        "items": [{
            "type": "attraction",
            "name": "清晖园",
            "poi_id": "p1",
            "location": {"lng": 113.255086, "lat": 22.835613},
            "start": "",
            "end": "",
            "indoor": False,
            "note": "",
            "cost": 0.0,
        }],
    }]

    out = fill_day_plans(
        skeleton=skeleton,
        restaurants=[],
        weather={},
        daily_centers=[{"lng": 113.255086, "lat": 22.835613}],
        start_date="",
        num_people=1,
    )

    assert [item["type"] for item in out[0]["items"]] == ["attraction"]
    assert out[0]["items"][0]["name"] == "清晖园"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd backend && uv run pytest tests/agent/test_itinerary_fill.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.agent.itinerary.fill'`.

- [ ] **Step 3: Implement deterministic fill**

Create `backend/app/agent/itinerary/fill.py`:

```python
# -*- coding: utf-8 -*-
"""Deterministic itinerary soft-field fill.

This module deliberately avoids LLM calls. It turns an OR-Tools attraction
skeleton into complete day plans that are good enough to continue the pipeline.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
import math
from typing import Any

from app.agent.itinerary.schemas import DayPlans


def _parse_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _fmt(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _distance2(a: dict[str, Any], b: dict[str, Any]) -> float:
    alng = float(a.get("lng", a.get("location", {}).get("lng", 0.0)) or 0.0)
    alat = float(a.get("lat", a.get("location", {}).get("lat", 0.0)) or 0.0)
    blng = float(b.get("lng", b.get("location", {}).get("lng", 0.0)) or 0.0)
    blat = float(b.get("lat", b.get("location", {}).get("lat", 0.0)) or 0.0)
    return (alng - blng) ** 2 + (alat - blat) ** 2


def _nearest_restaurant(restaurants: list[dict[str, Any]], anchor: dict[str, Any],
                        used_ids: set[str]) -> dict[str, Any] | None:
    available = [r for r in restaurants if r.get("poi_id", r.get("name", "")) not in used_ids]
    if not available:
        return None
    return min(available, key=lambda r: _distance2(r, anchor))


def _meal_item(restaurant: dict[str, Any], start: int, duration: int = 60) -> dict[str, Any]:
    return {
        "type": "meal",
        "name": restaurant.get("name", ""),
        "poi_id": restaurant.get("poi_id", ""),
        "location": {"lng": restaurant.get("lng", 0.0), "lat": restaurant.get("lat", 0.0)},
        "start": _fmt(start),
        "end": _fmt(start + duration),
        "indoor": True,
        "note": "就近安排用餐，减少绕路。",
        "mode": "",
        "from": "",
        "to": "",
        "cost": 80.0,
    }


def _transport_item(prev: dict[str, Any], nxt: dict[str, Any], start: int,
                    duration: int = 25) -> dict[str, Any]:
    return {
        "type": "transport",
        "name": "",
        "poi_id": "",
        "location": {"lng": 0.0, "lat": 0.0},
        "start": _fmt(start),
        "end": _fmt(start + duration),
        "indoor": False,
        "note": "按相邻点位预留市内交通时间。",
        "mode": "市内交通",
        "from": prev.get("name", ""),
        "to": nxt.get("name", ""),
        "cost": 15.0,
    }


def _attraction_item(item: dict[str, Any], start: int, rainy: bool,
                     duration: int = 90) -> dict[str, Any]:
    name = item.get("name", "")
    poi_type = item.get("type", "")
    indoor = rainy and any(key in f"{name}{poi_type}" for key in ("寺", "庙", "馆", "商场", "天地"))
    return {
        **item,
        "start": _fmt(start),
        "end": _fmt(start + duration),
        "indoor": bool(indoor),
        "note": "雨天适当放慢节奏。" if rainy else "按顺路顺序安排游览。",
        "cost": float(item.get("cost", 0.0) or 0.0),
    }


def _date_for_day(start_date: str, day_index: int) -> str:
    parsed = _parse_date(start_date)
    if parsed is None:
        return ""
    return (parsed + timedelta(days=day_index)).isoformat()


def fill_day_plans(skeleton: list[dict[str, Any]], restaurants: list[dict[str, Any]],
                   weather: dict[str, Any], daily_centers: list[dict[str, Any]],
                   start_date: str = "", num_people: int = 1) -> list[dict[str, Any]]:
    """Return complete day plans without relying on an LLM."""
    del num_people
    rainy = bool(weather.get("is_rainy", False))
    used_restaurant_ids: set[str] = set()
    plans: list[dict[str, Any]] = []

    for day_index, day_plan in enumerate(skeleton):
        current = 9 * 60 + 30
        filled_items: list[dict[str, Any]] = []
        attractions = [item for item in day_plan.get("items", []) if item.get("type") == "attraction"]

        for idx, attraction in enumerate(attractions):
            if idx > 0:
                filled_items.append(_transport_item(filled_items[-1], attraction, current))
                current += 25

            filled_items.append(_attraction_item(attraction, current, rainy))
            current += 90

            should_insert_lunch = idx == 0 and len(attractions) > 1
            should_insert_dinner = idx == len(attractions) - 1 and current >= 17 * 60
            if should_insert_lunch or should_insert_dinner:
                restaurant = _nearest_restaurant(restaurants, attraction.get("location", {}), used_restaurant_ids)
                if restaurant:
                    used_restaurant_ids.add(restaurant.get("poi_id", restaurant.get("name", "")))
                    meal_start = max(current, 12 * 60) if should_insert_lunch else max(current, 18 * 60)
                    filled_items.append(_meal_item(restaurant, meal_start))
                    current = meal_start + 60

        center = daily_centers[day_index] if day_index < len(daily_centers) else {"lng": 0.0, "lat": 0.0}
        plans.append({
            "day": day_plan.get("day", day_index + 1),
            "date": _date_for_day(start_date, day_index),
            "weather": {
                "text": weather.get("text", ""),
                "temp": weather.get("temp", ""),
                "is_rainy": rainy,
            },
            "center": center,
            "items": filled_items,
            "hotel": None,
        })

    return [d.model_dump(by_alias=True) for d in DayPlans(days=plans).days]
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
cd backend && uv run pytest tests/agent/test_itinerary_fill.py -q
```

Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/itinerary/fill.py backend/tests/agent/test_itinerary_fill.py
git commit -m "feat(itinerary): add deterministic day plan fill"
```

---

### Task 2: Use Deterministic Fill in `assemble_itinerary`

**Files:**
- Modify: `backend/app/agent/tools/itinerary.py`
- Modify: `backend/tests/agent/test_tools.py`

**Interfaces:**
- Consumes: `fill_day_plans(...)` from Task 1
- Produces: `assemble_itinerary(...)` returns deterministic complete `day_plans` even when LLM is unavailable

- [ ] **Step 1: Update failing tool test**

Modify the existing `test_assemble_itinerary_degrades_to_skeleton_when_soft_fill_fails` in `backend/tests/agent/test_tools.py` so it expects deterministic meal insertion and no raw skeleton blanks:

```python
    names = {item["name"] for item in out["day_plans"][0]["items"]}
    assert {"祖庙", "岭南天地", "民信老铺"} <= names
    assert out["day_plans"][0]["weather"]["text"] == "雷阵雨"
    assert out["day_plans"][0]["center"] == out["daily_centers"][0]
    assert all(item["start"] and item["end"] for item in out["day_plans"][0]["items"])
    assert out["warnings"] == ["itinerary_note_enrichment_failed"]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd backend && uv run pytest tests/agent/test_tools.py::test_assemble_itinerary_degrades_to_skeleton_when_soft_fill_fails -q
```

Expected: FAIL because current fallback does not insert meals and still uses `itinerary_soft_fill_failed`.

- [ ] **Step 3: Modify `assemble_itinerary`**

In `backend/app/agent/tools/itinerary.py`:

```python
from app.agent.itinerary.fill import fill_day_plans
```

Replace the current fallback helper usage with deterministic fill:

```python
deterministic_day_plans = fill_day_plans(
    skeleton=skeleton,
    restaurants=_compact_restaurants(restaurants or []),
    weather=weather or {},
    daily_centers=daily_centers,
    start_date=start_date,
    num_people=max(1, num_people),
)
```

Then change the LLM block so failure returns deterministic output:

```python
try:
    result = await asyncio.wait_for(
        llm.ainvoke([
            SystemMessage(content=ITINERARY_SYS),
            HumanMessage(content=json.dumps({
                "day_plans": deterministic_day_plans,
                "weather": weather or {},
                "instruction": "只润色 note 字段，不要改 POI、坐标、顺序、时间或费用。",
            }, ensure_ascii=False)),
        ]),
        timeout=_SOFT_FILL_TIMEOUT_SECONDS,
    )
except Exception:
    return {
        "day_plans": deterministic_day_plans,
        "daily_centers": daily_centers,
        "warnings": ["itinerary_note_enrichment_failed"],
    }
```

For this task, do not merge LLM output yet. Keep normal success behavior unchanged until Task 3 adds safe merge.

- [ ] **Step 4: Run tests to verify pass**

Run:

```bash
cd backend && uv run pytest tests/agent/test_tools.py::test_assemble_itinerary_degrades_to_skeleton_when_soft_fill_fails tests/agent/test_itinerary_fill.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/tools/itinerary.py backend/tests/agent/test_tools.py
git commit -m "feat(itinerary): return deterministic plans when llm enrichment fails"
```

---

### Task 3: Add Safe LLM Note Merge

**Files:**
- Modify: `backend/app/agent/itinerary/fill.py`
- Modify: `backend/app/agent/tools/itinerary.py`
- Modify: `backend/tests/agent/test_itinerary_fill.py`
- Modify: `backend/tests/agent/test_tools.py`

**Interfaces:**
- Produces: `merge_safe_notes(base: list[dict], enriched: list[dict]) -> list[dict]`
- Rule: only `note` may be copied from LLM output, matched by `(day, type, poi_id, name)`.

- [ ] **Step 1: Write failing pure-function test**

Append to `backend/tests/agent/test_itinerary_fill.py`:

```python
from app.agent.itinerary.fill import merge_safe_notes


def test_merge_safe_notes_only_updates_matching_notes():
    base = [{
        "day": 1,
        "items": [
            {"type": "attraction", "name": "祖庙", "poi_id": "p1", "location": {"lng": 1, "lat": 2}, "note": "old"},
            {"type": "meal", "name": "民信老铺", "poi_id": "r1", "location": {"lng": 3, "lat": 4}, "note": "meal old"},
        ],
    }]
    enriched = [{
        "day": 1,
        "items": [
            {"type": "attraction", "name": "祖庙", "poi_id": "p1", "location": {"lng": 999, "lat": 999}, "note": "适合雨天慢逛。"},
            {"type": "meal", "name": "不存在餐厅", "poi_id": "fake", "location": {"lng": 0, "lat": 0}, "note": "must ignore"},
        ],
    }]

    out = merge_safe_notes(base, enriched)

    assert out[0]["items"][0]["note"] == "适合雨天慢逛。"
    assert out[0]["items"][0]["location"] == {"lng": 1, "lat": 2}
    assert out[0]["items"][1]["note"] == "meal old"
    assert len(out[0]["items"]) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd backend && uv run pytest tests/agent/test_itinerary_fill.py::test_merge_safe_notes_only_updates_matching_notes -q
```

Expected: FAIL with `ImportError` or function missing.

- [ ] **Step 3: Implement safe merge**

Add to `backend/app/agent/itinerary/fill.py`:

```python
def _item_key(day: int, item: dict[str, Any]) -> tuple[int, str, str, str]:
    return (day, item.get("type", ""), item.get("poi_id", ""), item.get("name", ""))


def merge_safe_notes(base: list[dict[str, Any]], enriched: list[dict[str, Any]]) -> list[dict[str, Any]]:
    notes: dict[tuple[int, str, str, str], str] = {}
    for day in enriched or []:
        day_no = int(day.get("day", 0) or 0)
        for item in day.get("items", []) or []:
            note = item.get("note", "")
            if isinstance(note, str) and note.strip():
                notes[_item_key(day_no, item)] = note.strip()

    merged = []
    for day in base:
        copied_day = {**day, "items": []}
        day_no = int(day.get("day", 0) or 0)
        for item in day.get("items", []) or []:
            copied_item = dict(item)
            note = notes.get(_item_key(day_no, item))
            if note:
                copied_item["note"] = note
            copied_day["items"].append(copied_item)
        merged.append(copied_day)
    return merged
```

- [ ] **Step 4: Use safe merge in `assemble_itinerary`**

In `backend/app/agent/tools/itinerary.py`, import:

```python
from app.agent.itinerary.fill import fill_day_plans, merge_safe_notes
```

Change success return:

```python
return {
    "day_plans": merge_safe_notes(
        deterministic_day_plans,
        [d.model_dump(by_alias=True) for d in result.days],
    ),
    "daily_centers": daily_centers,
}
```

- [ ] **Step 5: Run tests**

Run:

```bash
cd backend && uv run pytest tests/agent/test_itinerary_fill.py tests/agent/test_tools.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/agent/itinerary/fill.py backend/app/agent/tools/itinerary.py backend/tests/agent/test_itinerary_fill.py backend/tests/agent/test_tools.py
git commit -m "feat(itinerary): safely merge llm note enrichment"
```

---

### Task 4: Update Prompt and Regression Coverage for LLM Boundaries

**Files:**
- Modify: `backend/app/agent/itinerary/schemas.py`
- Modify: `backend/tests/agent/test_itinerary_schemas.py`
- Modify: `backend/tests/agent/test_tools.py`

**Interfaces:**
- Consumes: `ITINERARY_SYS`
- Produces: prompt text that explicitly says LLM may only enrich notes.

- [ ] **Step 1: Write failing prompt test**

Modify `backend/tests/agent/test_itinerary_schemas.py`:

```python
def test_itinerary_prompt_limits_llm_to_note_enrichment():
    assert "只润色 note" in ITINERARY_SYS
    assert "不要改 POI" in ITINERARY_SYS
    assert "不要改坐标" in ITINERARY_SYS
    assert "不要改顺序" in ITINERARY_SYS
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd backend && uv run pytest tests/agent/test_itinerary_schemas.py::test_itinerary_prompt_limits_llm_to_note_enrichment -q
```

Expected: FAIL because current prompt allows broader soft-fill behavior.

- [ ] **Step 3: Update prompt**

In `backend/app/agent/itinerary/schemas.py`, replace `ITINERARY_SYS` with:

```python
ITINERARY_SYS = (
    "你是行程文案润色助手。输入已经包含确定的逐日行程、POI、坐标、时间、费用、天气和顺序。"
    "你只润色 note 字段，让说明更自然、更贴合天气和节奏。"
    "不要改 POI，不要改坐标，不要改顺序，不要删除或新增行程项，不要改 start/end，不要改 cost。"
    "如果不确定，就保留原 note。输出严格符合给定结构。"
)
```

- [ ] **Step 4: Run prompt and tool tests**

Run:

```bash
cd backend && uv run pytest tests/agent/test_itinerary_schemas.py tests/agent/test_tools.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/itinerary/schemas.py backend/tests/agent/test_itinerary_schemas.py
git commit -m "docs(itinerary): constrain llm to note enrichment"
```

---

### Task 5: Final Verification

**Files:**
- No production changes expected.

**Interfaces:**
- Verifies the full scoped change set.

- [ ] **Step 1: Run focused backend tests**

Run:

```bash
cd backend && uv run pytest tests/agent/test_itinerary_fill.py tests/agent/test_tools.py tests/agent/test_itinerary_schemas.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run relevant routing tests**

Run:

```bash
cd backend && uv run pytest tests/agent/test_optimizer.py tests/agent/test_matrix.py -q
```

Expected: `test_optimizer.py` passes. If `test_matrix.py::test_duration_matrix_uses_cache_second_call` fails with `No module named 'app.tools'`, record it as an existing unrelated test-path issue unless this plan also fixes that path.

- [ ] **Step 3: Inspect diff**

Run:

```bash
git diff --stat
git diff -- backend/app/agent/itinerary/fill.py backend/app/agent/tools/itinerary.py backend/app/agent/itinerary/schemas.py backend/tests/agent/test_itinerary_fill.py backend/tests/agent/test_tools.py backend/tests/agent/test_itinerary_schemas.py
```

Expected: changes are limited to deterministic fill, safe LLM note enrichment, prompt boundary, and tests.

- [ ] **Step 4: Commit final verification note if needed**

If Task 5 required any small test-path fix or documentation note:

```bash
git add <changed-files>
git commit -m "test(itinerary): verify deterministic fill pipeline"
```

Otherwise no commit is needed.

---

## Self-Review

- Spec coverage: The plan moves complete itinerary generation to deterministic code, keeps LLM optional, adds safe merge, updates prompt boundaries, and tests fallback behavior.
- Placeholder scan: No TODO/TBD placeholders remain.
- Type consistency: `fill_day_plans(...)` and `merge_safe_notes(...)` signatures are defined before use and match later tasks.
- Scope check: The plan only changes itinerary assembly; it does not refactor lodging, budget, session history, or frontend behavior.
