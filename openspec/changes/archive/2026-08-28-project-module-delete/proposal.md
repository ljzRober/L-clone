## Why

记忆工作台目前只支持添加项目/模块，**没有删除能力**——用户无法移除已不需要的项目或模块（如模块重组、项目废弃）。需补齐项目/模块的删除功能。

## What Changes

- **lclone Web 面板**（`lclone/web.py`）：
  - 项目树节点新增「删除项目」按钮（墓碑式：项目从列表消失、记忆停止加载，数据保留、可撤销）
  - 模块树节点新增「删除模块」按钮（连带删除该模块下的所有决策记忆，不可恢复）
  - 每个删除操作带确认弹窗，删除后 `loadAll()` 刷新视图
- **后端**（`lclone/projects.py`）：新增 `remove_module(conn, project_id, name)`——删除模块行 + 连带删除该模块下的 decision 记忆（note 无模块不受影响）。
- **HTTP API**（`lclone/web.py`）：
  - `POST /api/projects/{pid}/modules/delete`（删模块，连带记忆，body `{name}`）
  - `POST /api/projects/{pid}/remove`（墓碑式移除项目，复用 `remove_project`）
  - `POST /api/projects/{pid}/restore`（复活已移除项目）

## Capabilities

- **New Capabilities**: 无
- **Modified Capabilities**:
  - `web-hierarchy`：记忆工作台补「删除项目」「删除模块」交互（树节点删除按钮 + 确认弹窗 + 刷新）
  - `memory-capture`：模块归属补充「删除模块连带删除其下决策记忆」边界；项目移除边界确认墓碑式（不删行可恢复）

## Impact

- **代码**：`lclone/web.py`（API + 前端删除 UI）、`lclone/projects.py`（remove_module）
- **依赖**：无新增
- **行为**：项目删除为墓碑式（可撤销）；模块删除连带删除其下决策记忆（用户拍板语义）；删除后刷新视图
