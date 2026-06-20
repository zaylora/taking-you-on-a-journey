# 旅游规划 App · 后端（M1 骨架）

> 对话式 AI 旅游规划的最简流式链路：FastAPI + LangGraph（dispatch → summarize）+ SSE 逐字输出。
> 对应设计文档 `docs/superpowers/specs/2026-06-17-m1-skeleton-design.md`。

## 能力范围（M1）

- `POST /api/chat`：SSE 流式对话（单轮、无状态、无持久化）。
- `GET /health`：存活探针。
- LangGraph 两节点图：`START → dispatch → summarize → END`。
- 其余 8 个节点为占位（`return {}` + TODO），不接线进 M1 图，保证编译出的图永远可运行。

## 技术栈

Python ≥3.10 · uv · langgraph 1.2.5 · langchain-openai 1.3.2 · langchain-anthropic 1.4.6 ·
fastapi 0.137.1 · uvicorn 0.49.0 · sse-starlette 3.4.4 · pydantic-settings 2.14.1。

## 快速开始

```bash
cd backend
uv sync                       # 创建虚拟环境并按 uv.lock 安装依赖
cp .env.example .env          # PowerShell: Copy-Item .env.example .env
# 编辑 .env，至少填入 OPENAI_API_KEY（可选 OPENAI_BASE_URL 中转地址）
uv run uvicorn app.main:app --reload --port 8000
```

## 验收清单（四步）

1. **装依赖 + 配置**：`cd backend && uv sync && cp .env.example .env`，编辑填入 `OPENAI_API_KEY`（可选 `OPENAI_BASE_URL`）。
2. **起后端 + 健康检查**：`uv run uvicorn app.main:app --reload --port 8000`，访问 `GET http://localhost:8000/health` 返回 `{"status":"ok"}`。
3. **后端独立验流**（绕开前端；PowerShell 的 `curl` 是别名，请用 `curl.exe` 或 git bash）：
   ```bash
   curl.exe -N -X POST http://localhost:8000/api/chat \
     -H "Content-Type: application/json" \
     -d '{"message":"帮我规划三天东京行程"}'
   ```
   `-N` 关闭 curl 缓冲，肉眼确认逐条 `event: token` 流出，末尾有 `event: final`。
4. **端到端**：`cd frontend && bun install && bun run dev`，浏览器输入一句话，确认正文**逐字出现** → ✅ 达成 M1 验收标准。

## SSE 事件契约（前后端共享）

| event | data（JSON 单行） | 含义 |
| ----- | ----------------- | ---- |
| `node_start` | `{"node":"dispatch"}` | 进入节点 |
| `token` | `{"text":"成"}` | LLM 逐字输出 |
| `node_end` | `{"node":"summarize"}` | 节点结束 |
| `final` | `{"answer":"完整回答文本"}` | **结束信号**（前端据此停止；禁用 `[DONE]`） |
| `error` | `{"message":"用户可读的错误"}` | 出错（脱敏，不含 Key/堆栈） |

## M2 验收清单

M2 引入多轮澄清（interrupt）+ 真实高德检索 + 行程编排，核心能力：

- `POST /api/chat`：支持 `thread_id` 跨请求恢复；首次返回 `session`；缺口时返回 `clarify` 询问（可选项）；齐备后逐字流式行程，末尾 `final` 携 `day_plans` 结构化数据。
- `GET /health`：存活探针（M1 沿用）。
- 8 个节点接线图：`clarify` (interrupt) → `dispatch` → 4 并行检索（weather/attractions/restaurants/transport） → `itinerary` 分天聚类 → `summarize` 渲染行程 → END。
- `accommodation`/`budget` 在 M4 接通（见下「M4 验收清单」）。

### 配置与启动（M2）

```bash
cd backend
uv sync
cp .env.example .env                     # PowerShell: Copy-Item .env.example .env
# 编辑 .env，填入以下环境变量：
# OPENAI_API_KEY=sk-...（或中转 OPENAI_BASE_URL）
# AMAP_WEB_KEY=<高德 Web 服务 Key>（新增 M2 必需）

uv run uvicorn app.main:app --reload --port 8000
# 浏览器访问：GET http://localhost:8000/health → {"status":"ok"}
```

### 多轮澄清流验证（curl）

首轮：模糊输入 → 后端返回会话 id 与澄清问题。

```bash
curl -N -X POST http://localhost:8000/api/chat -H "Content-Type: application/json" \
  -d '{"message":"我想出去玩"}'
```

**期望响应**（逐行，每行是一条 SSE 事件）：
- `event: session` → `data: {"thread_id":"<uuid>"}`（复制此 id）
- `event: node_start` → `data: {"node":"clarify","label":"正在理解你的需求…"}`
- `event: clarify` → `data: {"field":"city","question":"去哪座城市？","options":[...]}`（或其他缺口字段）

二轮：带 thread_id 作答 → 后端恢复图，继续评估或放行编排。

```bash
curl -N -X POST http://localhost:8000/api/chat -H "Content-Type: application/json" \
  -d '{"message":"成都，3天，2人，爱吃辣，预算人均2000","thread_id":"<上一步的id>"}'
```

**期望响应**（缺口齐备后）：
- （可选）更多 `clarify`（若还有未回答的字段）
- `event: node_start` → dispatch/weather/attractions/... → summarize（4 个检索并行，各自 node_start/end）
- `event: token` → `data: {"text":"成都..."}` 逐字流出（仅 summarize 节点）
- `event: final` → `data: {"answer":"完整攻略...","day_plans":[...]}`（结束）

**说明**：PowerShell 的 `curl` 是别名，请用 `curl.exe` 或 git bash 确保 `-N` 参数被正确识别。

### 端到端验收（前端）

在 backend 已启动的前提下，新开终端：

```bash
cd frontend
bun install                    # 首次
bun run dev
# 浏览器访问 http://localhost:5173
```

**用户交互流程**：
1. 输入模糊需求，如"想在北京玩，时间不定"。
2. **澄清阶段**：对话区出现 AI 追问气泡（如"旅行时长？"）与选项按钮；点选或自由文本回答。
3. **进度可视化**：Agent 进度栏亮起（依次 clarify → dispatch → 并行检索 → itinerary → summarize）。
4. **结果呈现**：逐字渲染完整行程攻略（每天时间线、景点、餐厅、交通方案）；状态管理更新 `day_plans` 供 M3 地图消费。
5. **✅ 验收**：澄清、进度、逐字攻略三个环节顺利完成。

### 测试

```bash
cd backend
uv run pytest -q               # 对 LLM + 高德 tool 打桩，不依赖真实 Key/网络
# 期望：全绿（含 clarify interrupt、并行检索、聚类、end-to-end 流）
```

**关键测试覆盖**：
- `test_clarify_interrupt.py`：interrupt 与 resume 跨请求恢复。
- `test_parallel_retrieval.py`：4 并行节点各写独立字段，单节点失败不阻断其余。
- `test_cluster_by_day.py`：按天聚类逻辑（均衡分布、簇内顺路）。
- `test_itinerary.py`：行程编排产出 `day_plans` 符合结构。
- `test_chat_stream_m2.py`：完整 SSE 流 session → clarify → 并行 → final。

## M3 验收清单

M3 为纯前端里程碑：消费 M2 产出的 `day_plans`，实现高德地图打点 + 行程卡片 + 卡片↔地图双向联动。后端无改动（`map_proxy.py` 仍为空壳，POI 代理延后至 M5）。

- **数据契约**：前端 `day_plans` 强类型化（`DayPlan/TripItem/LngLat/DayWeather`），`poi_id` 为联动主键。
- **地图 Key 隔离**：后端 `AMAP_WEB_KEY` 不下发前端；前端用独立 `VITE_AMAP_JS_KEY`（JS API Key，需配域名白名单）。
- **加载守卫**：`VITE_AMAP_JS_KEY` 缺失时地图不加载、显示降级提示，应用其余功能不受影响。
- **布局**：右侧地图铺满，行程为右侧竖向悬浮面板，可收起/展开。

### 配置与启动（M3）

```bash
cd frontend
cp .env.example .env                       # PowerShell: Copy-Item .env.example .env
# 编辑 .env，填入：
# VITE_AMAP_JS_KEY=<高德 JS API Key>       # 控制台「Web端(JS API)」类型，配 localhost 白名单
bun install                                # 首次
bun run dev
# 浏览器访问 http://localhost:5173
```

**说明**：高德 JS API Key 与后端 `AMAP_WEB_KEY`（Web 服务）是两类不同 Key，不可混用。

### 端到端验收（前端）

在 backend 已启动、前端已填 `VITE_AMAP_JS_KEY` 的前提下，走完 M2 对话流生成行程后：

1. **自动打点**：行程生成（`final`）后，地图按 `day_plans` 自动打点并 `setFitView` 自适应视野；同一天的点同色，按天循环配色。
2. **卡片→地图**：点击右侧行程卡片，地图聚焦该 `poi_id`（居中 + 信息窗），卡片高亮。
3. **地图→卡片**：点击地图标记，对应卡片高亮并自动滚动到可视区。
4. **按天切换**：点击 Day Tab 切换当天打点与卡片列表。
5. **收起/展开**：行程面板可收起为「行程」窄条、展开为完整时间线，地图区域不被遮挡。
6. **Key 缺失降级**：清空 `VITE_AMAP_JS_KEY` 重启，地图区显示降级提示，对话/澄清/逐字攻略仍正常。
7. **✅ 验收**：自动打点、双向联动、按天切换、收起展开、缺 Key 降级五点均通过。

### 测试（M3）

M3 无新增单测框架，验证手段为类型检查构建 + 上述手动验收：

```bash
cd frontend
bun run build                  # = vue-tsc -b && vite build，类型契约即测试，须全绿
```

## M4 验收清单

M4 接通住宿 + 预算闭环：`itinerary → accommodation → budget`，超支条件边回退重排；前端展示预算明细、超支提示与每日酒店。

- 图结构：8 节点 + 2 新节点接线 `itinerary → accommodation → budget ─(over&retry<2)→ itinerary / 否则 → summarize → END`。
- 费用：LLM 估单价（`PlanItem.cost` 人均、`Hotel.price` 每晚整间），`budget` 纯函数汇总；`estimated = num_people × Σ(items.cost) + Σ(hotel.price)`。
- 预算口径：`budget` 为总预算（元），`0` 表示不限（不回退）。
- 超支回退：`budget` 算超支额 + 挑「最贵可削减项」入 `budget_advice`，`itinerary` 据此 LLM 重排；`retry_count ≤ 2` 封顶，到顶带「已尽力压缩」说明。
- `final` 事件 data：`{answer, day_plans, budget}`，`day_plans[i].hotel` 嵌入当晚住宿（末日为 null）。

### 多轮 + 预算流验证（curl）

```bash
curl -N -X POST http://localhost:8000/api/chat -H "Content-Type: application/json" \
  -d '{"message":"成都3天2人，爱吃辣，预算4000"}'
```

**期望**（缺口齐备后）：`node_start` 依次经 dispatch → 并行检索 → itinerary → **accommodation → budget** → summarize；`token` 逐字流出；`event: final` 的 data 含 `budget`（limit/estimated/over/breakdown）与 `day_plans`（每天含 `hotel`、每项含 `cost`）。超支（如把预算改小到 1500）时可见 itinerary/accommodation/budget 重跑一轮，final 的 `budget.over=true` 且带 `note`。

### 端到端验收（前端）

在 backend 已启动、前端已填 `VITE_AMAP_JS_KEY` 前提下走完对话流：

1. **预算总览**：final 后右侧面板顶部出现「已估 ¥X / 预算 ¥Y」+ 门票/住宿/餐饮/交通明细。
2. **每日酒店**：每天时间线末尾出现 🏨 酒店卡（名称 + 档位 + ¥/晚）；末日无酒店卡。
3. **单项费用**：行程项卡片显示 ¥X/人（cost 为 0 时不显示）。
4. **超支提示**：输入偏紧预算（如 1500）→ 总览条变红 + 「⚠ 超支 …（已自动重排 N 次）」，或封顶显示「已尽力压缩」。
5. **不限预算**：不填预算 → 总览条只显示已估总额，无超支提示，不回退。
6. **✅ 验收**：完整 7 步编排跑通；预算明细、每日酒店、超支自动重排均通过。

### 测试（M4）

```bash
cd backend && uv run pytest -q
```

**关键测试覆盖**：
- `test_budget.py`：纯函数核算（分类汇总、不限、超支回退、retry 封顶、路由）。
- `test_accommodation.py`：过夜日分配、档位关键词、嵌入合并、单日无住宿、POI 空降级。
- `test_itinerary.py`：`PlanItem.cost`/`Hotel`/`DayPlan.hotel`、回退建议入 payload。
- `test_builder.py`：图含 accommodation/budget 节点 + 超支条件边（两去向）。
- `test_chat_stream_m4.py`：端到端 final 携 budget + 酒店/费用；超支触发回退并封顶。

## 测试（M1）

```bash
uv run pytest        # 对 LLM 工厂打桩，不依赖真实 Key/网络
```

## 注意事项（落地实测要点）

- **.env 无 BOM**：Windows 下务必保存为 UTF-8（无 BOM），否则解析报错。
- **前端直连 + CORS**：前端不走 Vite proxy，直连本服务（`VITE_API_BASE=http://localhost:8000`）；后端已开 `CORSMiddleware` 放行 `cors_origins`（默认 `http://localhost:5173`）。跨域部署到不同域时按需调整环境变量 `CORS_ORIGINS`（JSON 数组）。
- **Python ≤3.10 流式坑**：`summarize` 节点必须 `async def` + 接收 `config` + `llm.astream(..., config=config)` 显式透传，否则 `on_chat_model_stream` 不冒泡、前端收不到逐字 token（已实测确认）。
- **版本实测**：langgraph 无 `__version__`，用 `importlib.metadata.version("langgraph")` 查版本。
- **M2 特别提示**：
  - 高德 Key 不下发前端，后端代理调用；Key 泄露将导致计费与安全隐患。
  - `clarify` 节点在无缺口时直接放行（退化为 M1 式单轮），有缺口时通过 `interrupt` 暂停，前端接 `clarify` 事件渲染问题 + 选项。
  - 中间节点（dispatch/weather/... 等）产生的 LLM token 不暴露给前端；仅 summarize 节点的 token 逐字流出。
  - 单个并行检索节点失败（如高德超时）走降级策略（返回空或季节气候），不阻断其余节点与后续编排。

## M5 fix 验收清单

把 M5 编排重构为「单一 dispatch_agent 前置派发 + refine 局部重排 + 住宿/预算按需重排」。

- 拓扑：`START → memory → dispatch_agent ─{plan_new→reset→clarify⟲→retrieve→并行检索→itinerary, refine→refine, qa→answer}`；`itinerary`/`refine → route_after_plan{accommodation,budget,summarize}`；`accommodation → route_after_accommodation{budget,summarize}`；`budget → route_after_budget{itinerary(仅plan_new超支),summarize}`。
- 判断为规则路由（不调 LLM）：`route_after_plan`/`route_after_accommodation` 读 `last_intent` + `refine_request.op`。
- refine 局部重排（async，只改 target_day）：relax/remove/reorder 本地改；change_meal→`restaurants` 检索、add/replace→`attractions` 检索后局部插入；change_budget 改预算上限走 budget；change_hotel 交 accommodation 重排。

### 测试（M5 fix）

```bash
cd backend && uv run pytest -q
```

关键覆盖：`test_dispatch_agent`（合并判意图+解析）、`test_dispatch_topology`（前半拓扑）、`test_need_routing`（两按需路由）、`test_refine_node`（本地 op）、`test_refine_search`（补检索）、`test_m5fix_e2e`（端到端按 op 选择性重排/跳过）。

## M6 验收清单（路线规划：行程地理质量）

把 `itinerary` 节点从「LLM 出整张行程」改为「**算法主导几何 + LLM 只填软字段**」，根治路线乱七八糟（餐厅折返市中心、交通段瞎编、顺路序被丢弃）。设计见 `docs/superpowers/specs/2026-06-20-route-planning-m6-design.md`。

- **算法权威**：`cluster_by_day` 顺路分天 → 每天 `amap.search_around(簇中心,"餐饮")` 取就近餐厅（空则兜底 `state["restaurants"]` 全城池）→ `build_day_stops` 顺路插午/晚餐（离当前位置最近、去重）→ `insert_transport` 在每对相邻停靠点间插交通段。
- **交通段**：真实起讫坐标（沿用相邻点）+ 真实 `from/to` 名 + 按直线距离定 `mode`（<1km 步行 / 1~5km 公交 / >5km 驾车）+ `cost` 按 mode 估（步行 0/公交 3/驾车 2+2×km）。每对相邻点都有段、不接酒店（跨天酒店腿不再产生）。
- **LLM 软填**：仅回填 `start/end/cost/indoor/note`，按 `poi_id` 合并、非空才覆盖；顺序/坐标/交通段一律以算法为准（`merge_soft_fields` 保证 LLM 乱动被丢弃）。LLM 调用 try/except 包裹，失败不阻断（几何已就绪）。
- **mode 字符串契约**：`步行`/`公交`/`驾车` 与前端 `useAMap.ts` 选插件关键字（Walking/Transfer/Driving）一一对应。
- **前端**：数据修好后现有分段总览路线自动连成完整路线、按天配色、无 7km 步行怪线；前端**无需改代码**（`vue-tsc -b` 通过）。

### 测试（M6）

```bash
cd backend && uv run pytest -q
```

关键覆盖（`test_amap.py` + `test_itinerary.py`）：`search_around` 正常/降级；`haversine_km`/`mode_by_distance` 边界；`pick_nearest` 就近去重；`build_day_stops` 午/晚餐插位与去重；`insert_transport` 全连通 + mode + cost；`merge_soft_fields` 仅并软字段、几何不可被 LLM 污染（对抗性测试）；`test_itinerary_algorithm_owns_geometry` 节点级集成（餐厅来自周边池 + 交通段存在 + 软字段合并）。

### 端到端验收（前端，需 `VITE_AMAP_JS_KEY` + 后端 Key）

```bash
cd backend && uv run uvicorn app.main:app --reload      # 终端 1
cd frontend && bun run dev                              # 终端 2
```

输入「广州 玩 3 天」，行程生成后肉眼核对：

1. **总览路线连续**：每天路线连成一条（不再只连一段），按天配色。
2. **餐厅贴景点**：用餐点落在当天景点簇附近，无「玩完郊区景点折返市中心吃饭」的长腿。
3. **交通段选中**：点某交通段 → 只显示起讫两点 + 该段路线，mode 与卡片一致（7km 不再标步行）。
4. **按天视图**：切到单天，路线与餐厅就近均正确。
5. **✅ 验收**：餐厅就近、每跳有段且方式合理、总览路线连续不折返。
