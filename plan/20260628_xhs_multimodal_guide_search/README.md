# 任务目标

升级小红书旅行研究能力：检索关键词默认使用攻略型描述，并对图文笔记中的图片做多模态 LLM 解析，避免遗漏图片里的店名、路线、菜单、价格、时间和避雷信息。

# 改动文件

- `backend/app/agent/tools/xhs.py`
- `backend/app/agent/prompt.py`
- `backend/tests/agent/test_tools.py`
- `backend/tests/agent/test_prompt.py`
- `docs/superpowers/plans/2026-06-28-xhs-multimodal-guide-search.md`
- `plan/20260628_xhs_multimodal_guide_search/README.md`

# 改动详情

- 新增攻略型关键词生成和普通旅行关键词补齐逻辑，让旅行检索优先走 `目的地 + 攻略` 查询。
- `xhs_search_notes` 会把旅行相关泛词如 `顺德美食`、`东京亲子游` 归一化为攻略型关键词。
- `research_xhs_travel_guide` 的搜索关键词统一由 `_build_xhs_guide_keywords` 生成，第一个查询保持 `{city}旅游攻略`。
- 新增小红书笔记图片 URL 抽取，覆盖 `note_card.image_list`、`cover` 等常见结构，并过滤头像、图标、视频 URL 和重复图片。
- 新增多模态图文解析辅助函数，使用现有 `build_llm` 和 LangChain 多模态消息块，不引入新依赖。
- 新增 `XhsVisualBrief` 和 `visual_clues` 字段，把图片里的地点、店名、菜单、价格、营业时间、路线和避雷线索纳入旅行研究摘要输入。
- `xhs_read_note` 默认在原始 CLI 响应外壳之外附加 `image_analysis` 和 `meta.image_analysis`。
- `research_xhs_travel_guide` 默认把每篇笔记的图片解析结果纳入最终旅行研究摘要输入，并在 `meta` 里记录图片解析数量。
- 图文解析失败时返回警告并继续文本研究，不阻断旅行规划。
- 更新系统提示，要求小红书检索使用攻略型关键词，并将图片解析结果视为待地图或正文校验的线索。

# 测试结果

- `cd backend && uv run pytest tests/agent/test_tools.py tests/agent/test_prompt.py tests/agent/test_build_agent.py -q`
  - 结果：49 passed, 3 warnings。
- `cd backend && uv run pytest -q`
  - 结果：95 passed, 2 failed, 4 warnings。
  - 失败 1：`tests/agent/test_matrix.py::test_duration_matrix_uses_cache_second_call` 仍 patch 旧路径 `app.tools.amap.distance_batch`，当前项目没有 `app.tools` 模块。
  - 失败 2：`tests/test_amap.py::test_search_poi_logs_empty_diagnostics` 仍监听旧 logger `app.tools.amap`，当前实现日志不进入该 logger。
  - 两个失败都不在本次小红书改动路径内，和历史记录中提到的旧路径/旧 logger 问题一致。

# 相关讨论

- 小红书工具继续保持只读边界，不接入发布、点赞、收藏或评论等账号写操作。
- 图片解析结果只作为攻略研究线索，最终地点、地址和坐标仍需高德校验。
- 默认最多解析每篇笔记 4 张图，硬上限 6 张，避免成本和上下文膨胀。
