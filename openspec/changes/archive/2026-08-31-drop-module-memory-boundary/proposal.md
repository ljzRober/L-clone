## Why

`memory-capture` 的"模块"轴（项目×模块）是项目内二级分类，但实战里它**只服务了 lclone 一个项目**（其他项目全是空模块），分类名靠 LLM 生成且与 openspec spec 词表**漂移**（spec `dsh-web-dashboard` ↔ 模块 `dsh-plugin`；spec `server-api` ↔ 模块 `server`），还产生了垃圾桶（`core` 装 5 条）和跨项目一长串 0 条 module——分类成本已超过召回收益。同时，project↔spec 的边界只靠脆弱的 `DID_MARKERS` 关键词启发式约束，**会漏**（契约类内容被当成 decision 记忆）。本变更移除 module 轴，并给 project↔spec 边界一条确定性规则。

## What Changes

- **BREAKING**：删除 `memories.module` 列与 `modules` 表；既有 module 标签被丢弃（决策记忆降回项目层，仍保留）。
- 代码移除 module：`db.py`（schema+迁移）、`memory.py`（`_normalize_module`/`_list_module_names`/`_resolve_module`/`GENERIC_MODULES`、`remember`/`capture` 参数、`organize`/`_format_grouped`/各 SELECT）、`projects.py`（`list_modules`/`add_module`/`remove_module`）、`mcp_server.py`+`cli.py`（module 参数）、`web.py`（module UI/API）、`llm.py`（`existing_modules`/module 输出）。
- `memory-capture` spec：移除 `模块归属` 需求；改写 `记忆整理合并`（同项目+同等级，去同模块）、`分类加载`（按项目分组，去模块）、`删除项目与模块`（→ 仅删除项目）；强化 `分工边界`（WHEN/THEN 试金石 + 半契约半理由拆分 + 升格规则）。
- `lclone-memory` skill 说明同步去掉"模块归属"。

## Capabilities

### New Capabilities
- 无

### Modified Capabilities
- `memory-capture`：需求 `分工边界`（强化判定规则）、`模块归属`（移除）、`记忆整理合并`（去同模块约束）、`分类加载`（去模块分组）、`删除项目与模块`（→ `删除项目`）。

## Impact

- 受影响系统：lclone 记忆子系统（`db.py`/`memory.py`/`projects.py`/`web.py`/`mcp_server.py`/`cli.py`/`llm.py`）。
- 受影响数据：`lclone.db` 的 `memories.module` 列 + `modules` 表 + `idx_modules_proj` 索引；迁移脚本需清理既有库。
- 受影响文档：`lclone-memory` skill（操作说明）；openspec `memory-capture` spec。
