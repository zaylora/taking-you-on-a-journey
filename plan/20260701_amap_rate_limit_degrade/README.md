# 高德限流降级处理

## 任务目标

修复高德 POI 检索返回 `infocode=10021 / CUQPS_HAS_EXCEEDED_THE_LIMIT` 时，Agent 把限流当成普通空结果并持续重试，最终触发 LangGraph `GraphRecursionError` 的问题。

成功标准：

1. 高德 POI 限流不再被吞成普通空数组。
2. 景点/餐厅检索工具向 Agent 返回明确的 `amap_rate_limited` 信号。
3. 普通网络错误、正常空结果仍保持原有降级行为。
4. 后端测试全绿。

## 改动文件清单

| 文件 | 说明 |
| --- | --- |
| `backend/app/utils/amap.py` | 新增 `AmapRateLimitError`，在 POI 检索遇到 `10021` 时抛出限流异常。 |
| `backend/app/agent/tools/trip.py` | 景点/餐厅工具捕获限流异常，返回结构化错误，提示停止继续检索并降级。 |
| `backend/app/agent/prompt.py` | 补充外部地图服务限流时停止同类检索、降级回答的行为约束。 |
| `backend/tests/test_amap.py` | 覆盖底层高德 POI 限流识别。 |
| `backend/tests/agent/test_tools.py` | 覆盖景点/餐厅工具的限流信号返回。 |

## 改动详情

- `search_poi` 仍对普通网络异常返回 `[]`，保持既有失败降级契约。
- 仅对高德 `infocode=10021` 做特殊处理，抛出 `AmapRateLimitError`，避免上层误判为“没有结果”。
- `search_attractions` 和 `search_restaurants` 将限流异常转换为：

```json
{
  "ok": false,
  "error": {
    "code": "amap_rate_limited",
    "message": "高德地图服务当前请求过于频繁，请停止继续检索，基于已有信息降级回答或提示稍后重试。"
  }
}
```

- 没有选择提高 `recursion_limit`，因为这只是延后 ReAct 循环失败；根因是工具层缺少“别再重试”的业务信号。

## 测试结果

```bash
cd backend
uv run pytest tests/test_amap.py -q
# 6 passed

uv run pytest tests/agent/test_tools.py -q
# 48 passed, 3 warnings

uv run pytest tests/agent/test_prompt.py -q
# 10 passed, 3 warnings

uv run pytest -q
# 144 passed, 4 warnings
```

## 相关讨论

- 高德 `10021` 属于账号接口 QPS/配额限制，不是地点关键词错误。
- SSE 失败的直接原因是 LangGraph 达到默认递归上限；更上游的触发点是 POI 工具在限流后持续表现为普通空结果。
- 后续若还遇到高德其他配额错误码，可按同一模式扩展为明确的外部服务降级信号。
