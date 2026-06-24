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

# 图节点全集（桥接层据此过滤 on_chain_start/end 名）—— Task 11 切图：6 节点直线拓扑
NODES = {"memory", "understand", "collect_context", "apply", "render", "memory_update"}

# node_start 携带的友好阶段文案（前端进度条展示，不暴露中间 LLM token）
NODE_LABELS = {
    "memory": "正在读取会话上下文…",
    "understand": "正在理解你的需求…",
    "collect_context": "正在检索景点/餐饮/天气…",
    "apply": "正在编排行程…",
    "render": "正在生成攻略…",
    "memory_update": "正在保存会话记忆…",
}

MAX_CLARIFY_ROUNDS = 4   # clarify 自循环轮次上限，超限取兜底放行

# —— itinerary 重做相关阈值常量 ——
# 求解
SOLVE_TIME_LIMIT_S: float = 5.0       # OR-Tools 单次求解时限(秒)
RELAX_BUDGET_FACTOR: float = 1.5      # 三级放松 L2：DAY_BUDGET × 此系数

# 候选预筛
PER_DAY_CAP: int = 5                  # 每天景点经验上限
CANDIDATE_MULTIPLIER: float = 1.5     # 预筛上限 = days × PER_DAY_CAP × 此系数

# 距离矩阵
MATRIX_CONCURRENCY: int = 3           # 高德 distance 并发上限(避 QPS 超限)
MATRIX_CACHE_TTL_DAYS: int = 30       # 距离缓存有效期(天)

# 交通方式分档(沿用 m6)
WALK_KM: float = 1.0                  # <1km 步行
TRANSIT_KM: float = 5.0               # 1~5km 公交；>5km 驾车
AROUND_RADIUS_M: int = 3000           # 周边餐厅搜索半径(米)
