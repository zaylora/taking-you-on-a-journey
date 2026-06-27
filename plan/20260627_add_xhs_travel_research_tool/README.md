# 任务目标

让旅行 agent 能把小红书攻略作为参考资料使用，抽取具体时间建议、路线经验、注意事项和避雷信息，再交给高德地图工具做真实 POI、天气和路线校验。

# 改动文件

- `backend/app/agent/tools/xhs.py`
- `backend/app/agent/tools/__init__.py`
- `backend/app/agent/build.py`
- `backend/app/agent/prompt.py`
- `backend/tests/agent/test_tools.py`

# 改动详情

- 新增组合工具 `research_xhs_travel_guide`：
  - 搜索目的地攻略、美食、天数和旅行偏好关键词。
  - 从搜索结果中提取笔记 ID / URL。
  - 读取前几篇攻略笔记，可选读取评论。
  - 用结构化 LLM 输出提炼旅行 brief。
- brief 包含：
  - `recommended_places`
  - `time_suggestions`
  - `route_patterns`
  - `food_keywords`
  - `tips`
  - `avoid_notes`
  - `amap_query_hints`
- 调整系统提示：新行程如需攻略经验，先做小红书攻略研究，再用高德检索和校验。
- 注册新工具到 agent `_TOOLS`。
- 增加测试覆盖工具注册、搜索结果目标提取和组合工具流程。

# 测试结果

- `uv run pytest tests/agent/test_tools.py tests/agent/test_prompt.py tests/agent/test_build_agent.py`
  - 结果：31 passed, 3 warnings
- `uv run pytest`
  - 结果：63 passed, 3 failed, 5 errors, 4 warnings
  - 失败与本次改动无关：`app.main` 导入了当前不存在的 `app.api.plan` / `app.api.map_proxy`，部分旧测试仍引用旧路径 `app.tools.amap`，`test_amap` 仍监听旧 logger 名称。

# 相关讨论

- 小红书用于“经验研究层”：抽取几点去哪、怎么玩、避雷和真实体验。
- 高德用于“落地校验层”：真实 POI、经纬度、路线、天气。
- 工具避免向最终行程直接照搬长原文，而是输出结构化摘要供后续规划使用。
