## Why

记忆会随着会话累积产生大量「语义相近、说的是同一件事」的碎片（如「模块归属」的多个版本、「归属判定」的多条规则、自筛规则的多条描述），加载时扁平列出既冗余又难读。需要两件事：① 在 web 提供「整理」把相近记忆合并成一条；② 加载记忆时按「项目 → 模块」分类展示，而非扁平列表。

## What Changes

- **记忆整理合并（LLM 语义合并，一键）**：新增 `memory.organize()`，用 LLM 把「语义相近」的记忆合并成一条综合描述；**硬约束：只能合并同项目 + 同等级(decision/note) + 同模块的记忆，跨项目/跨等级/跨模块一律不合并**（LLM 输出后由代码强制校验拒绝）。
- **Web「整理」按钮**：工作台工具栏加「整理」按钮，调 `/api/organize`，一键执行合并并刷新。
- **分类加载**：`bootstrap`/`recall` 加载记忆时按「项目 → 模块」分组展示（全局层按等级），不再扁平列出。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `memory-capture`: 新增「记忆整理合并」「分类加载」两条需求。

## Impact

- 代码：`lclone/llm.py`（`chat_json`）、`lclone/memory.py`（`organize`、bootstrap/recall 分组）、`lclone/mcp_server.py`、`lclone/cli.py`、`lclone/web.py`
- 接口：新增 `/api/organize`；`bootstrap`/`recall` 输出格式从扁平改为分组
- 依赖：无

## 方案

### 整理合并（organize）

```python
def organize(conn):
    rows = 所有 active 记忆 (id, project_id, level, module, content)
    # 一次 LLM 调用: 语义相近的合并, 输出 [{"content": 合并后, "ids": [原id...]}]
    # 代码校验: 每个 group 的成员必须 project_id+level+module 三者全同, 否则拒绝
    # 应用: insert 合并后一条, delete 原 ids (含 memory_links 清理)
```

- 合并约束（不能跨区域）：`(project_id, level, module)` 三元组完全相同才允许合并。
- 合并内容由 LLM 覆盖各条要点，中文，不遗漏。

### 分类加载（bootstrap/recall 分组）

- `bootstrap`：【全局记忆】按 level；【相关记忆】按 `项目 → 模块` 分组。
- `recall`（MCP/CLI 输出）同样按 `项目 → 模块` 分组。

## Spec Constraints

- `memory-capture` > 模块归属 > 记录无模块：note 不挂模块。
- `memory-capture` > 记忆分类与确认 > 自筛低价值：只提长期价值内容。
