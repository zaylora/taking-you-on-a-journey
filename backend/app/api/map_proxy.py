"""占位：高德地图代理（M3）。

router 已建但暂不挂任何 endpoint，main.py include 后不影响 M1 验收路径。
"""
from fastapi import APIRouter

router = APIRouter()

# TODO(M3): 高德 REST 代理（隐藏 key、绕过浏览器配额/跨域）
