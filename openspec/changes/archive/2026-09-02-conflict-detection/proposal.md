## Why

记忆会随会话增多产生**前后矛盾**（规则改版但旧规则仍在、选型冲突），影响召回与决策可信度。ROADMAP v1 已列"记忆冲突检测与档案刷新"。用户确认需要。成熟方案（Generative Agents / LangMem）标配 contradiction handling。

## What Changes

- **`find_conflicts(conn, project_id)`**：扫描 active insight，找出语义相近（向量相似度 ≥ 阈值）的候选对，用 LLM 判定是否真矛盾（返回 JSON），输出 `{a, b, content_a, content_b, reason, hint}`。只提示候选、不自动改记忆；是否处理由用户定。dummy 后端不判矛盾（退回无候选）。
- **CLI**：`lclone conflicts`（`--project`）。
- **MCP**：`conflicts` 工具（`project` 可选）。

## Capabilities

- `memory-capture`：ADDED `记忆矛盾检测` 需求。

## Impact

- 代码：`lclone/memory.py`（`find_conflicts`）、`lclone/cli.py`（`conflicts`）、`lclone/mcp_server.py`（`conflicts` 工具）。
- 测试：`tests/test_offline.py` 新增 2 条（mock chat_json 判矛盾 + CLI 冒烟），106 全绿。
