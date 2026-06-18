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

# 图节点全集（桥接层据此过滤 on_chain_start/end 名）
NODES = {"clarify", "dispatch", "weather", "attractions",
         "restaurants", "transport", "itinerary", "accommodation", "budget", "summarize"}

# node_start 携带的友好阶段文案（前端进度条展示，不暴露中间 LLM token）
NODE_LABELS = {
    "clarify": "正在理解你的需求…",
    "dispatch": "正在梳理需求要点…",
    "weather": "正在查询目的地天气…",
    "attractions": "正在检索热门景点…",
    "restaurants": "正在挑选餐厅…",
    "transport": "正在规划交通…",
    "itinerary": "正在按顺路编排每日行程…",
    "accommodation": "正在挑选住宿…",
    "budget": "正在核算预算…",
    "summarize": "正在生成攻略…",
}

MAX_CLARIFY_ROUNDS = 4   # clarify 自循环轮次上限，超限取兜底放行
