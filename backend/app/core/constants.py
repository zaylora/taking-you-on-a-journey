"""SSE 事件名常量 —— 前后端共享契约。

前端对应一份 frontend/src/types/index.ts，两边名字必须一致，避免拼写漂移。
约定：所有 data 一律 json.dumps(..., ensure_ascii=False) 为单行；结束信号用 final，禁用 [DONE]。
"""

EVENT_NODE_START = "node_start"  # data: {"node": "dispatch"}
EVENT_TOKEN = "token"            # data: {"text": "成"}
EVENT_NODE_END = "node_end"      # data: {"node": "summarize"}
EVENT_FINAL = "final"            # data: {"answer": "完整回答文本"} —— 结束信号
EVENT_ERROR = "error"            # data: {"message": "用户可读的错误"}（脱敏）

EVENT_SESSION = "session"   # data: {"thread_id": "<hex>"} —— 新会话首帧
EVENT_CLARIFY = "clarify"   # data: {"field","question","options"} —— 暂停等澄清
EVENT_TITLE = "title"       # data: {"thread_id","title"} —— 会话标题更新
EVENT_INTENT = "intent"     # data: {"intent"} —— M5 意图调试/进度
EVENT_PLAN_PATCH = "plan_patch"  # data: {"plan_version","changed_days"} —— 局部更新提示

# 图节点全集（create_agent 内部节点：model 决策/回复、tools 执行）
NODES = {"agent", "model", "tools"}

# node_start 携带的友好阶段文案（agent 内部节点较少，仅作兜底）
NODE_LABELS = {
    "agent": "正在思考...",
    "model": "正在思考...",
    "tools": "正在调用工具...",
}
