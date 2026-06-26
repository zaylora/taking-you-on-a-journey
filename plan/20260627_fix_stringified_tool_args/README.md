# 修复字符串化工具参数

## 任务目标

修复 LangSmith 最近会话中 `assign_hotels` 工具调用失败的问题：模型把 `daily_centers` 以字符串形式传入，导致 Pydantic 在工具执行前报 `Input should be a valid list`。

## 改动文件

- `backend/app/agent/tools.py`
- `backend/tests/agent/test_tools.py`

## 改动详情

- 在工具参数 schema 边界新增 `_parse_jsonish_string`，优先解析标准 JSON，失败后用 `ast.literal_eval` 兼容 LangSmith 截图里出现的 Python 字面量风格字符串，例如单引号字典列表、`None`、`False`。
- 为 `AssignHotelsArgs.daily_centers` 增加 `field_validator(mode="before")`，把字符串化的活动中心数组恢复成真实 list 后再进入原有 schema 校验。
- 同步为 `AssembleItineraryArgs.budget_advice` 增加同类 validator，避免下一轮预算建议对象被字符串化时触发相邻字段错误。
- 新增两个回归测试，分别覆盖字符串化 `daily_centers` 和字符串化 `budget_advice`。

## 测试结果

- `uv run pytest -q tests/agent/test_tools.py::test_assign_hotels_accepts_stringified_daily_centers`：先失败，错误为 `daily_centers Input should be a valid list`；修复后通过。
- `uv run pytest -q tests/agent/test_tools.py::test_assemble_itinerary_accepts_stringified_budget_advice`：先失败，错误为 `budget_advice Input should be a valid dictionary`；修复后通过。
- `uv run pytest -q tests/agent/test_tools.py`：13 passed。
- `uv run pytest -q tests/agent`：43 passed。

## 相关讨论

- 只靠 prompt/schema description 提醒模型“不要传字符串”不足以保证真实工具调用一定正确；这里把容错放在 Pydantic schema 的入参边界，工具主体逻辑仍保持原来的 list/dict 契约。
- 解析后仍交给 Pydantic 校验目标类型，因此无效字符串不会被静默吞掉。
