# Agent 上下文压缩策略

## 背景

当前旅行 Agent 使用 `create_agent` + checkpointer 持久化 `messages`，同一会话会不断累积用户消息、AI 决策消息和工具结果。旅行规划的主要上下文压力来自工具输出：高德 POI、路线结果、住宿候选、预算结果以及后续可能接入的小红书攻略内容。

压缩目标不是替代业务状态。结构化行程仍以 `day_plans`、`budget_check`、`plan_version` 等 state 字段为准；上下文治理只负责避免旧消息和旧工具结果把模型输入撑爆。

## 当前配置

配置位置：`backend/app/agent/build.py`

使用两层 LangChain middleware：

1. `ContextEditingMiddleware`
   - 触发阈值：约 `16_000` tokens
   - 至少清理：`5_000` tokens
   - 保留最近：`4` 个工具结果
   - 不清理工具：`finalize_plan`、`compute_budget_tool`

2. `SummarizationMiddleware`
   - 触发阈值：`40_000` tokens 或 `28` 条消息
   - 摘要后保留最近：`10_000` tokens 原文
   - 摘要输入上限：`16_000` tokens
   - 摘要提示词：`backend/app/agent/prompt.py` 中的 `TRIP_SUMMARY_PROMPT`

## 为什么这样设置

工具结果清理可以比摘要更早触发。旧工具结果通常已经被 Agent 消化进最终回复、`day_plans` 或预算状态，继续完整保留收益不高，但 token 成本很高。因此在 `16k` 左右先清理旧工具输出，保留最近 4 个工具结果支撑当前推理。

对话摘要会有信息损耗，所以更晚触发。旅行会话里的用户偏好、否定约束、最近修改意图都很重要，过早摘要容易丢掉细节。`40k tokens` 或 `28 messages` 基本对应多轮规划、修改、问答之后，此时再摘要更合理。

摘要后保留最近 `10k tokens` 原文，是为了覆盖当前一轮修改上下文、最近工具链和最终回复，避免用户刚说的“把第二天那个餐厅换掉”之类指代被摘要吞掉。

## 摘要必须保留的信息

`TRIP_SUMMARY_PROMPT` 要求保留：

- 用户旅行目标：目的地、天数、日期、人数、预算、住宿档位
- 偏好与约束：节奏、同行人群、饮食、交通、必须去/不想去、避雷和预算红线
- 当前已确认行程：每天核心景点、餐厅、酒店和重要时间安排
- 最近修改意图：替换、删除、重排、放松或加严的部分
- 未决问题：缺失信息、待确认事项和下一步

## 注意事项

`SummarizationMiddleware` 会真实改写 checkpoint 里的 `messages`：旧消息会被移除，替换成一条带 `additional_kwargs={"lc_source": "summarization"}` 的摘要 `HumanMessage`。如果会话历史接口直接渲染所有 `HumanMessage`，压缩后可能会展示摘要文本。后续若发现前端历史里出现摘要，应在 sessions 聚合层过滤或特殊处理该来源。

不要使用 `("fraction", 0.8)` 这类比例阈值作为默认配置。本项目支持 OpenAI、Anthropic 和自定义 `base_url`，模型 profile 不一定提供可靠的最大输入 token 信息；绝对 token 阈值更稳定。
