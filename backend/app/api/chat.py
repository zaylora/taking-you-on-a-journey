"""POST /api/chat —— SSE 流式对话端点。"""
from fastapi import APIRouter, Request
from sse_starlette import EventSourceResponse

from app.schemas.chat import ChatRequest
from app.graph.stream import sse_events

router = APIRouter()


@router.post("/api/chat")
async def chat(req: ChatRequest, request: Request):
    # ping=15：每 15s 发一条 SSE 注释心跳，保活连接（前端按 ':' 开头忽略）
    return EventSourceResponse(sse_events(req.message, request), ping=15)
