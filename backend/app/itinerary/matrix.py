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
        # asyncio 单线程下当前安全，加 check_same_thread=False 防御后续引入 run_in_executor 时的 ProgrammingError
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
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

    def get_many(self, poi_b: str, src_ids: list[str]) -> dict[str, float]:
        """批量读「各 src -> poi_b」的有效缓存。一次 SQL，TTL 在内存过滤。"""
        if not src_ids:
            return {}
        placeholders = ",".join("?" * len(src_ids))
        cur = self._conn.execute(
            f"SELECT poi_a, minutes, ts FROM distance_cache "
            f"WHERE poi_b=? AND poi_a IN ({placeholders})",
            (poi_b, *src_ids))
        ttl = MATRIX_CACHE_TTL_DAYS * 86400
        now = time.time()
        return {a: m for a, m, ts in cur.fetchall() if now - ts <= ttl}

    def put_many(self, rows: list[tuple[str, str, float]]) -> None:
        """批量写入 (poi_a, poi_b, minutes)。"""
        if not rows:
            return
        now = time.time()
        self._conn.executemany(
            "INSERT OR REPLACE INTO distance_cache VALUES (?,?,?,?)",
            [(a, b, m, now) for a, b, m in rows])
        self._conn.commit()


def _fallback_minutes(a: dict, b: dict) -> float:
    return haversine_km(a, b) / _DRIVE_KMH * 60.0


def _unstable(poi_id: str) -> bool:
    """poi_id 不稳定的虚拟节点（如 depot=__depot__，坐标随会话/城市变）不进缓存。"""
    return not poi_id or poi_id.startswith("__")


async def distance_matrix(nodes: list[dict], db_path: str) -> list[list[float]]:
    """N*N 真实街道时间矩阵(分钟)。优先缓存 -> 缺失批量调高德 -> 单弧失败降级 haversine。"""
    # 构造里有 connect + CREATE TABLE 等同步 sqlite 调用，一并移出事件循环
    cache = await asyncio.to_thread(MatrixCache, db_path)
    n = len(nodes)
    mat = [[0.0] * n for _ in range(n)]
    sem = asyncio.Semaphore(MATRIX_CONCURRENCY)
    # 同步 sqlite 连接非线程安全，串行化所有 DB 段；DB 操作仅微秒级，不损并发收益
    db_lock = asyncio.Lock()

    async def _cache_get(poi_b: str, src_ids: list[str]) -> dict[str, float]:
        if not src_ids:
            return {}
        async with db_lock:  # to_thread 把同步 sqlite 移出事件循环，避免阻塞
            return await asyncio.to_thread(cache.get_many, poi_b, src_ids)

    async def _cache_put(rows: list[tuple[str, str, float]]) -> None:
        if not rows:
            return
        async with db_lock:
            await asyncio.to_thread(cache.put_many, rows)

    async def fill_dest(j: int) -> None:
        dest_node = nodes[j]
        dest_id = dest_node["poi_id"]
        # depot 等 poi_id 不稳定的虚拟节点（坐标随会话变）不读缓存，避免跨会话脏读
        stable_src = ([nodes[i]["poi_id"] for i in range(n)
                       if i != j and not _unstable(nodes[i]["poi_id"])]
                      if not _unstable(dest_id) else [])
        hits = await _cache_get(dest_id, stable_src)
        missing_idx, missing_orig = [], []
        for i in range(n):
            if i == j:
                continue
            cached = hits.get(nodes[i]["poi_id"])
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
        to_write: list[tuple[str, str, float]] = []
        for k, i in enumerate(missing_idx):
            s = secs[k] if k < len(secs) else None
            minutes = (s / 60.0) if s is not None else _fallback_minutes(nodes[i], dest_node)
            mat[i][j] = minutes
            # 同理：depot 弧不落缓存（坐标会变，缓存会污染下次规划）
            if not (_unstable(nodes[i]["poi_id"]) or _unstable(dest_id)):
                to_write.append((nodes[i]["poi_id"], dest_id, minutes))
        await _cache_put(to_write)

    await asyncio.gather(*(fill_dest(j) for j in range(n)))
    return mat
