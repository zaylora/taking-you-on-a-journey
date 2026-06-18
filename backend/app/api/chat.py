"""POST /api/chat —— SSE 流式对话端点。"""
from fastapi import APIRouter, Request
from sse_starlette import EventSourceResponse

from app.schemas.chat import ChatRequest
from app.graph.stream import sse_events

router = APIRouter()


@router.post("/api/chat")
async def chat(req: ChatRequest, request: Request):
    return EventSourceResponse(sse_events(req.message, req.thread_id, request), ping=15)
