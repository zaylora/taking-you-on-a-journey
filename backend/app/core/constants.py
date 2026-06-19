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

# 图节点全集（桥接层据此过滤 on_chain_start/end 名）
NODES = {"memory", "intent", "clarify", "dispatch", "weather", "attractions",
         "restaurants", "transport", "itinerary", "refine", "answer",
         "accommodation", "budget", "summarize", "memory_update"}

# node_start 携带的友好阶段文案（前端进度条展示，不暴露中间 LLM token）
NODE_LABELS = {
    "clarify": "正在理解你的需求…",
    "memory": "正在读取会话上下文…",
    "intent": "正在判断本轮意图…",
    "dispatch": "正在梳理需求要点…",
    "weather": "正在查询目的地天气…",
    "attractions": "正在检索热门景点…",
    "restaurants": "正在挑选餐厅…",
    "transport": "正在规划交通…",
    "itinerary": "正在按顺路编排每日行程…",
    "refine": "正在局部调整行程…",
    "answer": "正在基于当前方案回答…",
    "accommodation": "正在挑选住宿…",
    "budget": "正在核算预算…",
    "summarize": "正在生成攻略…",
    "memory_update": "正在保存会话记忆…",
}

MAX_CLARIFY_ROUNDS = 4   # clarify 自循环轮次上限，超限取兜底放行
