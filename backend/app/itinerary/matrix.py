# -*- coding: utf-8 -*-
"""距离矩阵：高德真实街道时间 + SQLite 持久缓存(poi_id 对为键) + haversine 降级。"""
import asyncio
import sqlite3
import time

from app.core.constants import MATRIX_CONCURRENCY, MATRIX_CACHE_TTL_DAYS
from app.itinerary.geometry import haversine_km
from app.tools import amap

_DRIVE_KMH = 30.0  # 降级估速：城市驾车均速


class MatrixCache:
    """(poi_a, poi_b) -> 分钟。带 TTL；城市内 POI 间街道时间近乎不变。"""

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


def _fallback_minutes(a: dict, b: dict) -> float:
    return haversine_km(a, b) / _DRIVE_KMH * 60.0


async def distance_matrix(nodes: list[dict], db_path: str) -> list[list[float]]:
    """N*N 真实街道时间矩阵(分钟)。优先缓存 -> 缺失批量调高德 -> 单弧失败降级 haversine。"""
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
