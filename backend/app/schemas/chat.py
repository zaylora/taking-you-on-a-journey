"""请求/响应 schema。"""
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="用户输入的一句话")
    thread_id: str | None = Field(default=None, description="会话 id；首次为 null，由后端 session 帧下发")
