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

EVENT_THINKING = "thinking"        # data: {"text"} —— 推理模型思考过程增量（reasoning_content）
EVENT_TOOL_CALL = "tool_call"      # data: {"tool","label"} —— 工具开始执行
EVENT_TOOL_RESULT = "tool_result"  # data: {"tool","label"} —— 工具执行结束

# 图节点全集（create_agent 内部节点：model 决策/回复、tools 执行）
NODES = {"agent", "model", "tools"}

# node_start 携带的友好阶段文案（agent 内部节点较少，仅作兜底）
NODE_LABELS = {
    "agent": "正在思考...",
    "model": "正在思考...",
    "tools": "正在调用工具...",
}

# 工具名 → 前端展示的友好中文文案（用于 tool_call / tool_result 过程链）
TOOL_LABELS = {
    "search_attractions": "搜索景点",
    "search_restaurants": "搜索餐厅",
    "get_weather": "查询天气",
    "plan_route": "规划交通",
    "assemble_itinerary": "编排逐日行程",
    "assign_hotels": "安排住宿",
    "compute_budget_tool": "核算预算",
    "ask_user": "向你确认信息",
    "finalize_plan": "确认行程",
}
