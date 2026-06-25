# -*- coding: utf-8 -*-
"""行驶时间矩阵：高德 /v3/distance 真实街道时间 + SQLite 缓存 + haversine 降级。

供 OR-Tools VRPTW 求解器消费。缓存用独立 SQLite 文件（与 checkpointer 分离，避免写锁冲突）。
"""
import math
import sqlite3

from app.tools import amap

_EARTH_KM = 6371.0


def haversine_km(a: dict, b: dict) -> float:
    lat1, lng1 = math.radians(a.get("lat", 0.0)), math.radians(a.get("lng", 0.0))
    lat2, lng2 = math.radians(b.get("lat", 0.0)), math.radians(b.get("lng", 0.0))
    dlat, dlng = lat2 - lat1, lng2 - lng1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * _EARTH_KM * math.asin(math.sqrt(h))


def haversine_seconds(a: dict, b: dict, kmh: float = 30.0) -> float:
    """直线距离估行驶秒数（降级用）。同点 0。"""
    km = haversine_km(a, b)
    return round(km / max(1e-6, kmh) * 3600, 1)


def _ensure_cache(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("CREATE TABLE IF NOT EXISTS dist (o TEXT, d TEXT, t TEXT, dur REAL, PRIMARY KEY(o,d,t))")
    conn.commit()
    return conn


async def duration_matrix(nodes: list[dict], db_path: str, use_amap: bool = True,
                          type_: str = "1") -> list[list[float]]:
    """N x N 行驶秒矩阵。优先缓存->amap->haversine 降级。对角线 0。nodes 每项含 poi_id/lng/lat。"""
    n = len(nodes)
    m = [[0.0] * n for _ in range(n)]
    if n <= 1:
        return m
    conn = _ensure_cache(db_path)
    try:
        for j, dest in enumerate(nodes):
            missing_idx = []
            for i, orig in enumerate(nodes):
                if i == j:
                    continue
                row = conn.execute("SELECT dur FROM dist WHERE o=? AND d=? AND t=?",
                                   (orig["poi_id"], dest["poi_id"], type_)).fetchone()
                if row is not None:
                    m[i][j] = row[0]
                else:
                    missing_idx.append(i)
            if missing_idx and use_amap:
                origins = [f"{nodes[i]['lng']},{nodes[i]['lat']}" for i in missing_idx]
                dest_str = f"{dest['lng']},{dest['lat']}"
                results = await amap.distance_batch(origins, dest_str, type_)
                by_oid = {r["origin_id"]: r["duration"] for r in results}
                for k, i in enumerate(missing_idx):
                    dur = by_oid.get(k + 1)
                    if dur is None or dur <= 0:
                        dur = haversine_seconds(nodes[i], dest)
                    m[i][j] = dur
                    conn.execute("INSERT OR REPLACE INTO dist VALUES (?,?,?,?)",
                                 (nodes[i]["poi_id"], dest["poi_id"], type_, dur))
                conn.commit()
            elif missing_idx:
                for i in missing_idx:
                    m[i][j] = haversine_seconds(nodes[i], dest)
        return m
    finally:
        conn.close()
