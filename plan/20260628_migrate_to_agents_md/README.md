# 将 CLAUDE.md 迁移为 AGENTS.md 并补写项目规范

## 任务目标

把根目录 `CLAUDE.md` 的项目约定迁移到工具中立的 `AGENTS.md`，并扫描全项目补写一份精简的开发规范（技术栈、目录、命令、代码/安全/测试约定、SSE 契约）。`CLAUDE.md` 保留为指针，确保 Claude Code 仍能自动加载。

## 改动文件清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `AGENTS.md` | 新增 | 项目规范正文：技术栈、目录结构、命令、依赖优先原则、代码约定、安全约定、测试约定、SSE 事件契约、改动记录规则 |
| `CLAUDE.md` | 修改 | 原约定内容迁出，改为指向 AGENTS.md 的指针（`@AGENTS.md` 引用，Claude Code 仍自动加载） |

## 改动详情

- **迁移**：原 `CLAUDE.md` 仅含「依赖优先原则」「改动记录规则」两节，全部并入 `AGENTS.md`。
- **新增规范**：通过扫描 `backend/pyproject.toml`、`frontend/package.json`、`core/config.py`、agent tools、tests、README 等，提炼出真实约定：
  - 技术栈：后端 FastAPI + LangGraph（ReAct）+ uv + pytest；前端 Vue 3 + Vite + bun + Element Plus。
  - 代码约定：tool 用 `@tool`/`async`/返回 `Command`；state 并发字段配 reducer；密钥用 `SecretStr`；纯计算放 `itinerary/`。
  - 安全约定：高德 Key 不下发前端、`.env` 无 BOM 不入库、SSE error 脱敏。
  - SSE 事件契约表（前后端共享）。
- **CLAUDE.md 指针**：选择"保留作指针"方案——Claude Code 默认只自动加载 `CLAUDE.md`，故保留该文件并用 `@AGENTS.md` 引用，兼顾 Codex 等读 `AGENTS.md` 的工具。

## 测试结果

纯文档改动，无需运行测试。`@AGENTS.md` 为 Claude Code 的文件引用语法，加载时会内联 AGENTS.md 内容。

## 相关讨论

- 用户确认：CLAUDE.md 保留作指针（而非 symlink 或删除）；规范保持精简核心。
- 未用 symlink 是因为 git 跨平台符号链接易出问题，指针 + `@` 引用更稳。
