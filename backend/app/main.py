"""FastAPI 入口。

- 启动期 fail-fast：默认 provider 的 API Key 为空时直接报错退出，避免运行时才暴露。
- 开 CORSMiddleware：前端直连后端（不走 Vite proxy），放行 settings.cors_origins。
  POST application/json 触发的预检 OPTIONS 由该中间件自动处理。
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.api.chat import router as chat_router
from app.api.plan import router as plan_router
from app.api.map_proxy import router as map_proxy_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # —— 启动期 fail-fast：默认 provider 的 Key 必须存在 ——
    settings = get_settings()
    if not settings.active_api_key():
        raise RuntimeError(
            f"缺少 {settings.llm_provider} 的 API Key，请在 backend/.env 中配置后再启动。"
        )
    if not settings.amap_web_key.get_secret_value():
        raise RuntimeError("缺少 AMAP_WEB_KEY，请在 backend/.env 中配置后再启动。")

    # —— LangSmith 追踪（pydantic-settings 读 .env，但 LangChain 直接读 os.environ）——
    if settings.langchain_tracing_v2:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_API_KEY"] = settings.langchain_api_key.get_secret_value()
        os.environ["LANGCHAIN_PROJECT"] = settings.langchain_project
        os.environ["LANGCHAIN_ENDPOINT"] = settings.langchain_endpoint

    yield


app = FastAPI(title="Trip Planner Backend (M2)", lifespan=lifespan)

_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins,
    allow_credentials=False,  # M1 无 cookie 鉴权，origins 用具体值即可，不用 "*"
    allow_methods=["*"],
    allow_headers=["*"],
)

# 真实路由 + 占位路由（占位 router 暂无 endpoint，不影响 M1 验收路径）
app.include_router(chat_router)
app.include_router(plan_router)
app.include_router(map_proxy_router)


@app.get("/health")
async def health():
    return {"status": "ok"}

def start_dev():
    """用于开发环境启动的便捷入口 (由 uv run dev 调用)"""
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
