# -*- coding: utf-8 -*-
"""Deterministic itinerary soft-field fill.

This module deliberately avoids LLM calls. It turns an OR-Tools attraction
skeleton into complete day plans that are good enough to continue the pipeline.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
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


def _nearest_restaurant(
    restaurants: list[dict[str, Any]],
    anchor: dict[str, Any],
    used_ids: set[str],
) -> dict[str, Any] | None:
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


def _transport_item(
    prev: dict[str, Any],
    nxt: dict[str, Any],
    start: int,
    duration: int = 25,
) -> dict[str, Any]:
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


def _attraction_item(
    item: dict[str, Any],
    start: int,
    rainy: bool,
    duration: int = 90,
) -> dict[str, Any]:
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


def fill_day_plans(
    skeleton: list[dict[str, Any]],
    restaurants: list[dict[str, Any]],
    weather: dict[str, Any],
    daily_centers: list[dict[str, Any]],
    start_date: str = "",
    num_people: int = 1,
) -> list[dict[str, Any]]:
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


def _item_key(day: int, item: dict[str, Any]) -> tuple[int, str, str, str]:
    return (day, item.get("type", ""), item.get("poi_id", ""), item.get("name", ""))


def merge_safe_notes(
    base: list[dict[str, Any]],
    enriched: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Copy only matching LLM-provided note text onto deterministic day plans."""
    notes: dict[tuple[int, str, str, str], str] = {}
    for day in enriched or []:
        day_no = int(day.get("day", 0) or 0)
        for item in day.get("items", []) or []:
            note = item.get("note", "")
            if isinstance(note, str) and note.strip():
                notes[_item_key(day_no, item)] = note.strip()

    merged: list[dict[str, Any]] = []
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
