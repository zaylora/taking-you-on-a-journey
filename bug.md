# 行程修改失败诊断：第一天无法改成黄埔区

## 问题描述
用户在 trip 行程规划 Agent 中输入"我想把第一天改成黄埔"，系统回复"已根据你的要求调整第1天"，但第一天的目的地区域实际并未变更为黄埔区。

## 执行链路追踪（LangSmith Studio）
Thread: `019ef4c5-4a49-...`

链路节点顺序：`__start__ → memory → dispatch_agent → refine → summarize → memory_update`

## 根因分析

### 核心问题：意图被错误归类，缺少"更换区域/地点"这一操作类型
dispatch_agent 能正确识别"修改已有行程"意图（`last_intent: refine_existing`），并定位到第 1 天（`target_day: 1`），但它输出的 `refine_request.op`（操作类型）无法表达"替换某天所在区域"，只能在有限的几个 op 中硬套。

### 两次复现结果对比

| 字段 | 第一次（"改成黄埔"） | 第二次（"替换为黄埔区，重新搜索安排景点餐厅"） |
| --- | --- | --- |
| `last_intent` | refine_existing | refine_existing |
| `op` | `reorder`（换天顺序） | `change_meal`（换餐厅） |
| `target_day` | 1 | 1 |
| `target_item_name` | 空 | 空 |
| `constraints` | `keywords: 黄埔` | `{}`（"黄埔"丢失） |
| `needs_search` | false | true |
| `needs_budget_recheck` | false | true |
| `plan_version` | 4 | 5 |
| 第一天 center 坐标 | lat 23.1154, lng 113.276 | lat 23.1154, lng 113.276（未变） |

### 关键证据
- 第一天 `center` 坐标在两版中始终为 `lat 23.1154, lng 113.276`，对应广州市区/越秀一带，而非黄埔区（黄埔位于城东，经度约 113.45 以上）。
- 即使第二次 `needs_search=true` 并触发了 budget 重算、plan_version 递增，refine 仅在现有市区候选中微调景点/餐厅，从不重算该天的 center 坐标。
- "黄埔"这一地理约束在第二次解析中完全丢失（constraints 为空）。

## 结论
系统不支持"更换某天地理区域"的意图。`op` 可选值仅为 reorder、change_meal 等"在现有区域内微调"的操作，没有"重设该天 center 并按新区域重新检索 POI"的操作。因此无论用户如何措辞，第一天始终无法迁移到黄埔区。

## 修复建议
1. **dispatch_agent**：新增类似 `change_area` / `relocate_day` 的意图与 op；确保将地名写入 `constraints`（如 `constraints.area: 黄埔区`，或稳定保留 `keywords`），避免地理约束在解析中丢失。
2. **refine**：收到该 op 时，先将目标天的 `center` 重设为新区域坐标，再以新 center 为圆心重新检索 POI 并重排当天行程，最后触发 budget 重算。