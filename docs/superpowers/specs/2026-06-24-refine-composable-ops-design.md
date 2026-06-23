# 设计：refine 可组合原子操作（取代有损的规则解析）

- 日期：2026-06-24
- 分支：m6-v2
- 范围：重写 `refine_existing` 这条路径的「意图解析」与「执行」两层——把基于关键词/正则的封闭词表，换成「LLM 语义理解产出可组合原子操作序列 + 确定性执行器」。不动 plan_new / qa / clarify / 检索 / OR-Tools 编排管线。
- 验收标准：
  1. 「我想把第一天改成黄埔」能真正把第 1 天的 center 迁到黄埔区，并围绕新 center 重检索景点+餐饮、重排当天。
  2. 「替换为黄埔区，重新搜索安排景点餐厅」等不同措辞，地名不再丢失，得到同等效果。
  3. 复合请求「第一天改黄埔并且少排一个景点」一轮内同时生效。
  4. 系统听不懂时，反问澄清，而不是默默把当天倒序后谎称「已调整」。
  5. 现有 refine 行为（relax / reorder / change_budget / change_hotel）在新形状下行为不变。

## 决策摘要

| 决策点 | 选择 | 说明 |
|---|---|---|
| 路线 | B：可组合原子操作 | 新说法靠组合已有原语覆盖，而非每种说法加一个 op，避免无限打地鼠 |
| 意图解析 | LLM 结构化输出（仅 refine 分支） | plan_new 已用此模式；refine 当初纯正则是 M5 权宜，无硬约束。保留廉价的规则分类器做 refine/plan_new/qa 三分 |
| 标志位 | 执行器确定性推导 | `needs_search` / `needs_budget_recheck` / `needs_accommodation` 不问 LLM，由 op 集合推出，保证可测 |
| 兜底 | 澄清而非破坏 | 解析不出 op → 反问用户；删除原 `reorder` 破坏性兜底 |
| 执行语义 | 工作副本 + 尽力而为 + 诚实回报 | 单个 op 失败则跳过并记 warning，绝不半残；如实告知改了/跳过了什么 |
| schema 形状 | 单一扁平 Operation 模型 | 跨 provider 的 function-calling 对 discriminated union 不稳，扁平模型更鲁棒，执行器侧按 op 校验 |

## 1. 当前问题与根因

用户「把第一天改成黄埔」，系统回「已根据你的要求调整第1天」，但第 1 天的区域并未变。根因不是「少了一个 change_area op」，而是 refine 这条路径**把无穷的用户意图，经两道写死的字符串规则，压进一张只有 9 个值的封闭词表**，信息在解析阶段即被销毁：

- **第一道闸 · 意图→op**（`dispatch_agent._infer_op`）：7 个 `if 关键词` 的瀑布，兜底 `return "reorder"`。reorder 是真实的破坏性操作（当天倒序），不是「没听懂」。「改成黄埔」无「换」字 → 掉进兜底，于是被解读成「把第 1 天倒序」。
- **第二道闸 · 句子→constraints**（`dispatch_agent._parse_refine`）：唯一能流到执行器的信息是正则 `(?:换成|改成|换个|改为)` 后那一个词，其余整句丢弃。「替换为」不在这四个前缀里，「黄埔」当场蒸发。
- **第三层 · 执行器封闭且浅**（`refine.py`）：只会做 9 件事；`reorder` 只是 `reversed()`，`change_meal` 用的是**全城** `search_poi` 而非圆心 `search_around`——压根没有「地理区域」维度；op 之间不能组合。

合起来，用户→执行器的信息通道带宽 ≈「9 选 1 + 最多 1 个词」。补一个 change_area 只是堵一个漏点，下一句话从别处再漏。

> 反讽：策划书 §「结构化输出」明确要求所有中间 Agent 用 function calling / structured output 强约束，并给 dispatch / clarify / summarize 都配了强模型；唯独 refine 的解析走了纯正则。它是全项目唯一不守家规的地方。

复现对照（LangSmith thread `019ef4c5`）：

| 字段 | 「改成黄埔」 | 「替换为黄埔区，重新搜索安排景点餐厅」 |
|---|---|---|
| op | reorder（掉兜底） | change_meal（"餐厅"+"替换"含"换"） |
| constraints | keywords: 黄埔（但被 reorder 无视） | {}（"替换为"不匹配正则，黄埔丢失） |
| 第 1 天 center | 未变 | 未变 |

## 2. 目标与非目标

**目标**：把解析层换成语义理解，把执行层换成「正交原语 + 可组合 + 确定性 + 尽力而为 + 诚实回报」，使形形色色的修改请求被统一接住。

**非目标（YAGNI，首版不做，待这套原语跑通后按需加）**：
- 跨天移动单个 POI（`move A from day1 to day2`）
- 时间点级微调（「博物馆挪到下午」）
- 整天对调
- 全城/跨城重规划（属 plan_new）

## 3. 指令集（8 个正交原语）

每个原语职责单一、可独立测试。`day` 为目标天（部分原语为全局）。

| 原语 | 字段 | 执行器行为 | 用户说法举例 |
|---|---|---|---|
| `set_region` | day, area | `geocode(area)` → 重设当天 center → 围绕新 center `search_around` 拉景点池+餐饮池 → 就近排序成行 → `insert_transport` → 重算 center；默认沿用原景点数量 | 「第一天改成黄埔」「第二天去番禺玩」「挪到珠江新城一带」 |
| `add_poi` | day, query, kind(attraction/meal) | `search_around(center, query)` → 插入 | 「第二天加个博物馆」「再加一顿早茶」 |
| `remove_poi` | day, selector | 解析 selector → 删除 | 「删掉武侯祠」「第一天少一个景点」「把最远那个去掉」 |
| `replace_poi` | day, selector, query, kind | remove + add | 「晚餐换成火锅」「用宽窄巷子替掉锦里」 |
| `reorder` | day, strategy(optimize/reverse) | optimize=就近重排；reverse=倒序 | 「第一天顺序调一下」「先去远的」 |
| `set_pace` | day, direction(relax/tighten) | 删到符合时间预算（沿用 `_relax_until_budget`） | 「第二天太赶了，轻松点」 |
| `set_budget` | amount | 改预算上限，交 budget 核算（行程不动） | 「预算改成3000」 |
| `set_hotel` | days?, criteria | 标记过夜日，交 accommodation 重排 | 「换个离地铁近的酒店」 |

**组合性（B 的灵魂）**：「第一天改黄埔并且少排一个」→ `[set_region(1,"黄埔"), set_pace(1,relax)]`，执行器按序应用。

**selector 模型**（remove/replace 定位目标项）：
- 按名字：对 `item.name` 做模糊包含匹配。
- 按 类型+序号：`kind` + `index`（`index=-1` 表示最后一个）。
- 命不中 → 跳过该 op + 记 warning，绝不乱删。

## 4. 解析器（dispatch_agent）

保留 `_rule_based_intent` 做 refine/plan_new/qa 三分类（廉价、够用）。**仅替换** refine 分支里的 `_parse_refine`：判定为 `refine_existing` 时，调一次 LLM 结构化输出，产出：

```
RefinePlan {
  operations: [ Operation, ... ]   # 第 3 节 8 个原语的有序列表
  clarification: str | None         # 听不懂时要问用户的话
}
```

- 喂给 LLM 的上下文：用户原话 + **当前 day_plans 摘要**（每天有哪些项、第几天——selector 与 target_day 靠它）+ 会话摘要。
- `needs_search` / `needs_budget_recheck` / `needs_accommodation` **不问 LLM**，由执行器按 op 集合确定性推导。
- `operations == []` 且有 `clarification` → 置 `last_intent="qa"` + `refine_clarification`，复用 `→answer→memory_update→END` 路径反问用户；不产生破坏性默认。
- **schema 形状**：采用单一扁平 Operation 模型（所有字段可选 + `op` 字面量），执行器侧按 op 校验。理由：跨 provider 的 function-calling 对 discriminated union 支持不稳。
- 删除 `dispatch_agent._infer_op` / `_parse_refine`，及 `refine.py` 内重复的 `_infer_op`。

## 5. 执行器（refine 节点重写）

核心从「按单个 op 分支」变为「在工作副本上按序应用一串 op」：

1. `deepcopy(day_plans)` 作工作副本；ops 按天分组（`set_budget` / `set_hotel` 为全局）。
2. 逐个应用，**每个 op 尽力而为**：geocode 失败 / 检索为空 / selector 命不中 → 跳过并记一条 warning，继续下一个，绝不让行程半残。
3. 某天的结构 op 全部应用完后，**统一重建一次交通段 + 重算一次 center**（不再每 op 重建）。这顺带修复一个潜伏 bug：现状 center 从不更新，改完即脏。
4. 收尾派生标志：`changed_days`、`needs_budget_recheck`（任一结构/预算/酒店 op）、`needs_accommodation`（任一 `set_hotel`）、`needs_search`（任一 `set_region`/`add`/`replace`，仅作观测——检索已在各 handler 内联完成，路由不依赖它）；有结构变化才 `plan_version += 1`；`set_budget` 回写 `budget`，`set_hotel` 回写过夜日。
5. **诚实回报**：返回 `refine_notes {applied:[...], skipped:[...]}`。

`set_region` 是最重 handler，复用 `app/itinerary/geometry.py` 现成件（`build_day_stops` / `pick_nearest` / `insert_transport`）+ `amap.geocode` / `amap.search_around`，**不碰 OR-Tools 多天管线**。center 重算复用 assembler 的质心逻辑（停靠点坐标均值）。

## 6. 拓扑与契约影响

- **契约**：`refine_request` 内部从扁平 `{op, target_day, constraints, …}` → `{operations:[…], clarification, + 派生标志}`。读它的只有 dispatch_agent（产）/ refine（消）/ routing（读标志）三处。`/api/plan/refine` 是空壳 endpoint，无影响。`state.refine_request` 仍是无类型 dict，无需改类型。
- **路由解耦**：`routing.route_after_plan` 现读 `req["op"]=="change_hotel"`；改为读派生标志 `req["needs_accommodation"]`，使路由与 op 列表彻底解耦。`route_after_accommodation` 仅用 `needs_budget_recheck`，不变。
- **澄清路由**：`answer` 节点加一个小分支——发现 `state["refine_clarification"]` 即原样返回该句、跳过 LLM、`changed_days=[]`。不新增图的边。
- **诚实回报**：`summarize` 的 payload 带上 `refine_notes`，让攻略如实陈述改了什么/跳过什么。

### 改动文件清单（7 处）

| 文件 | 改动 |
|---|---|
| `app/graph/nodes/dispatch_agent.py` | 保留规则分类；refine 分支换成 LLM 解析→RefinePlan；删 `_infer_op`/`_parse_refine`；处理 clarification |
| `app/graph/nodes/refine.py` | 重写为序列执行器 + 8 handler + selector 解析 + center 重算 + 派生标志 + refine_notes；删重复 `_infer_op` |
| `app/graph/nodes/refine_ops.py`（新增，或并入 refine.py） | Operation / RefinePlan 扁平模型 |
| `app/graph/nodes/routing.py` | `op` 判断 → 读 `needs_accommodation` 标志 |
| `app/graph/nodes/answer.py` | clarification 原样返回分支 |
| `app/graph/nodes/summarize.py` | payload 带 refine_notes |
| `app/graph/state.py` | 加 `refine_notes`、`refine_clarification` 字段 |

## 7. 测试与迁移

- **翻转/删除**：`test_refine_turn_parses_by_rule_without_llm` 改用 `conftest.make_fake_build_llm` 伪造 LLM 产出 RefinePlan；删除 `test_parse_refine_*`、`test_refine_flags_by_op`（函数已移除/逻辑迁到 refine 派生）。
- **重写保留行为**：`test_refine_node.py` 按新 operations 形状重写，保留断言：relax 只动目标天 / reorder 倒序 / change_budget 不动行程 / change_hotel 标记过夜日。
- **新增**：
  - 复合 op（`set_region` + `set_pace`）一轮同时生效；
  - `set_region`（mock `geocode` + `search_around`）：验 center 迁移、POI 重检索；
  - selector：按名 / 按序 / 命不中→跳过+warning；
  - 空 ops + clarification → 路由到 answer 原样反问；
  - 诚实 notes：skipped 被记录并出现在回报里。
- **审计迁移**：`test_refine_budget`、`test_refine_search`、`test_refine_transport`、`test_multiturn_refine` 按新形状迁移，正确的旧行为予以保留。

## 8. 风险与缓解

| 风险 | 缓解 |
|---|---|
| LLM 把 op 解析错（如选错天、选错 selector） | day_plans 摘要喂给 LLM 降低歧义；selector 命不中跳过+warning；诚实回报让用户能立刻发现并纠正 |
| 每轮 refine 多一次 LLM 调用，增加延迟 | 仅 refine 分支调用；qa/plan_new 路径不变；用户已确认可接受 |
| `set_region` 单天重排质量不如 OR-Tools | 首版用就近排序（geometry 现成件）即可满足「迁到正确区域」的核心诉求；OR-Tools 单天重入留作后续增强 |
| 扁平 Operation 模型字段松散导致脏数据 | 执行器侧按 op 严格校验必填字段，缺失即视为该 op 解析失败 → 跳过+warning |
| 跨 provider 结构化输出差异 | 复用 plan_new 已验证的 `build_llm(...).with_structured_output(method="function_calling")` 路径 |
